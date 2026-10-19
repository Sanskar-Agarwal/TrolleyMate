"""«worker» NutritionComplianceAgent — cascading allergen & dietary checks, nutritional
adequacy, and escalation of uncertain cases (UC-06, 1.2.10, 1.2.11, 1.2.15).

Safety-first rules:
  - an ingredient (or any sub-ingredient, recursively) carrying a restricted tag → violation
  - a "may contain" warning for a severe allergy → violation; otherwise → uncertain
  - missing ingredient data → uncertain
  - vague label terms ("natural flavours") → the LLM judges the risk; low confidence → uncertain
  - uncertain items are never auto-accepted: they are withheld and escalated to a dietitian
  - a dietitian's past decision on the same product for the same household is reused

The verdict it returns is specified in services/compliance_verdict.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select

from app.agents.base import Agent
from app.core.config import get_settings
from app.domain import Basket, ComplianceVerdict, EscalationCase, Household, Ingredient, Product
from app.domain.enums import CaseStatus, ItemCompliance, Severity, VerdictStatus
from app.optimisation.types import Requirements
from app.services.compliance_verdict import VerdictEvidence, outcome
from app.services.dietary_rules import label, normalise_restriction, violating_tags
from app.services.nutrition_targets import TARGETS_VERSION

# (ingredient, restriction, provider) → LLM judgement. Shared across requests: label
# semantics don't change, and this keeps real-LLM screening fast.
_INGREDIENT_CACHE: dict[tuple[str, str, str], dict] = {}


@dataclass
class Finding:
    product_id: int
    product: str
    status: str = ItemCompliance.compliant
    confidence: float = 1.0
    findings: list[dict] = field(default_factory=list)

    def add(self, status: str, confidence: float, **detail) -> None:
        self.findings.append(detail)
        rank = {ItemCompliance.compliant: 0, ItemCompliance.uncertain: 1, ItemCompliance.violation: 2}
        if rank[status] > rank[self.status]:
            self.status = status
        self.confidence = min(self.confidence, confidence)

    def as_dict(self) -> dict:
        return {"product_id": self.product_id, "product": self.product, "status": self.status, "confidence": round(self.confidence, 2), "findings": self.findings}


class NutritionComplianceAgent(Agent):
    role_name = "AI Nutrition & Compliance"
    key = "nutrition_compliance"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.safety_threshold = get_settings().compliance_safety_threshold

    # --- Restrictions ------------------------------------------------------

    def restrictions_for(self, household: Household, payload: dict | None) -> list[dict]:
        """Household mandatory restrictions ∪ request restrictions, keeping the strictest severity."""
        rank = {Severity.severe: 3, Severity.moderate: 2, Severity.mild: 1, Severity.preference: 0}
        merged: dict[str, dict] = {}
        for r in household.mandatory_restrictions() + list((payload or {}).get("restrictions", [])):
            rid = normalise_restriction(r["restriction"])
            sev = r.get("severity", Severity.severe)
            if rid not in merged or rank.get(sev, 0) > rank.get(merged[rid]["severity"], 0):
                merged[rid] = {"restriction": rid, "severity": sev, "label": label(rid)}
        return list(merged.values())

    # --- Screening (Activity 7.4) -----------------------------------------

    def screen_product(self, product: Product, restrictions: list[dict], household_id: int | None = None) -> Finding:
        f = Finding(product.id, product.name)
        if not restrictions:
            return f

        prior = self._prior_decision(product.id, household_id, restrictions) if household_id else None
        if prior is not None:
            status = ItemCompliance.compliant if prior.resolution == VerdictStatus.passed else ItemCompliance.violation
            f.add(status, 1.0, kind="human_review", detail=f"Dietitian decision: {prior.resolution} — {prior.resolution_note or 'no note'}")
            return f

        if not product.data_complete:
            f.add(ItemCompliance.uncertain, 0.4, kind="missing_data", detail="Ingredient list missing from the retailer feed")

        for r in restrictions:
            rid, tags = r["restriction"], violating_tags(r["restriction"])
            for ingredient in product.ingredients:
                for path, ing in self._walk(ingredient):
                    hit = tags.intersection(ing.tags)
                    if hit:
                        f.add(
                            ItemCompliance.violation, 1.0, kind="contains", restriction=rid,
                            ingredient=" → ".join(path), detail=f"Contains {ing.name} ({', '.join(sorted(hit))})",
                        )
                    elif ing.ambiguous:
                        judgement = self._judge(product, ing, rid)
                        if judgement["risk"] == "likely":
                            f.add(ItemCompliance.violation, 0.9, kind="ambiguous", restriction=rid, ingredient=" → ".join(path), detail=judgement["reasoning"])
                        elif judgement["risk"] == "possible":
                            f.add(
                                ItemCompliance.uncertain, round(1 - judgement["confidence"] * 0.5, 2), kind="ambiguous",
                                restriction=rid, ingredient=" → ".join(path), detail=judgement["reasoning"],
                            )
            for warn in tags.intersection(product.may_contain):
                if r["severity"] == Severity.severe:
                    f.add(ItemCompliance.violation, 0.95, kind="may_contain", restriction=rid, detail=f"Label says it may contain {warn.replace('_', ' ')}")
                else:
                    f.add(ItemCompliance.uncertain, 0.7, kind="may_contain", restriction=rid, detail=f"May contain traces of {warn.replace('_', ' ')}")

        if f.status == ItemCompliance.compliant and f.confidence < self.safety_threshold:
            f.status = ItemCompliance.uncertain
        return f

    def screen(self, products: list[Product], restrictions: list[dict], *, household_id: int | None = None,
               session_id: int | None = None) -> dict[int, Finding]:
        results = {p.id: self.screen_product(p, restrictions, household_id) for p in products}
        counts = {s: sum(1 for f in results.values() if f.status == s) for s in ItemCompliance}
        self.log(
            "screen_candidates",
            f"{counts[ItemCompliance.compliant]} compliant, {counts[ItemCompliance.violation]} excluded, "
            f"{counts[ItemCompliance.uncertain]} uncertain of {len(products)}",
            rationale="Checked against: " + (", ".join(r["label"] for r in restrictions) or "no restrictions"),
            session_id=session_id,
            payload={"excluded": [f.as_dict() for f in results.values() if f.status == ItemCompliance.violation][:30],
                     "uncertain": [f.as_dict() for f in results.values() if f.status == ItemCompliance.uncertain]},
        )
        return results

    # --- Basket verification (UC-06) --------------------------------------

    def verify(self, b: Basket, household: Household, payload: dict, req: Requirements | None = None) -> ComplianceVerdict:
        restrictions = self.restrictions_for(household, payload)
        products = {item.product_id: item.product for item in b.items}
        results = {pid: self.screen_product(p, restrictions, household.id) for pid, p in products.items()}

        for item in b.items:
            item.compliance = results[item.product_id].status
            item.withheld = item.compliance == ItemCompliance.uncertain
        violations = [f for f in results.values() if f.status == ItemCompliance.violation]
        uncertain = [f for f in results.values() if f.status == ItemCompliance.uncertain]
        nutrition = self.assess_nutrition(b, req) if req else None

        status = outcome(f.status for f in results.values())
        confidence = min([f.confidence for f in results.values()] or [1.0])
        evidence = VerdictEvidence(
            restrictions=restrictions, products=[f.as_dict() for f in results.values()], nutrition=nutrition,
        )
        verdict = ComplianceVerdict(
            basket_id=b.id, status=status, confidence=round(confidence, 2), evidence=evidence.model_dump(mode="json"),
        )
        self.db.add(verdict)
        self.db.flush()
        self.log(
            "verify_basket",
            f"Verdict {status}: {len(violations)} violation(s), {len(uncertain)} uncertain",
            confidence=verdict.confidence, basket_id=b.id, session_id=b.session_id,
            rationale="; ".join(fd["detail"] for f in uncertain + violations for fd in f.findings)[:600],
        )

        if status == VerdictStatus.escalated:
            from app.workflows import escalation

            for item in b.items:
                if item.withheld:
                    escalation.raise_case(self, verdict, item, household, results[item.product_id], restrictions)
        return verdict

    def assess_nutrition(self, b: Basket, req: Requirements) -> dict:
        """1.2.11 — compares what the (non-withheld) basket provides against the requirements."""
        provided = {k: 0.0 for k in ("kcal", "protein_g", "veg_serves", "fibre_g")}
        for item in b.items:
            if not item.withheld:
                for k in provided:
                    provided[k] += float(item.product.nutrition.get(k, 0)) * item.quantity
        required = {"kcal": req.kcal, "protein_g": req.protein_g, "veg_serves": req.veg_serves}
        coverage = [
            {
                "nutrient": k, "required": round(v, 1), "provided": round(provided[k], 1),
                "coverage_pct": round(100 * provided[k] / v) if v else 100, "met": provided[k] + 1e-6 >= v,
            }
            for k, v in required.items()
        ]
        gaps = [
            {"nutrient": c["nutrient"], "required": c["required"], "provided": c["provided"],
             "short_by": round(required[c["nutrient"]] - provided[c["nutrient"]], 1)}
            for c in coverage if not c["met"]
        ]
        return {
            "adequate": not gaps,
            "provided": {k: round(v, 1) for k, v in provided.items()},
            "required": {k: round(v, 1) for k, v in required.items()},
            "coverage": coverage,
            "gaps": gaps,
            "suggestions": [_gap_suggestion(g["nutrient"]) for g in gaps],
            "targets": TARGETS_VERSION,
        }

    def supply_information(self, case: EscalationCase, question: str) -> str:
        p = case.product
        record = {
            "name": p.name, "brand": p.brand, "ingredients": [i.name for i in p.ingredients],
            "may_contain": p.may_contain, "data_complete": p.data_complete, "evidence": case.evidence,
        }
        result = self.think("supply_information", {"question": question, "product": record})
        self.log("supply_information", result.data[:300], basket_id=case.basket_id, llm=result)
        return result.data

    # --- helpers -------------------------------------------------------------

    def _walk(self, ingredient: Ingredient, path: tuple[str, ...] = (), seen: frozenset[int] = frozenset()):
        """Yield (path, ingredient) for the ingredient and every sub-ingredient (cascading check)."""
        if ingredient.id in seen:
            return
        here = (*path, ingredient.name)
        yield here, ingredient
        for child in ingredient.components:
            yield from self._walk(child, here, seen | {ingredient.id})

    def _judge(self, product: Product, ingredient: Ingredient, restriction: str) -> dict:
        key = (ingredient.name, restriction, self.llm.provider_name)
        if key not in _INGREDIENT_CACHE:
            result = self.think("assess_ingredient", {"product": product.name, "ingredient": ingredient.name, "restriction": restriction})
            _INGREDIENT_CACHE[key] = result.data
            self.log(
                "assess_ingredient",
                f"'{ingredient.name}' vs {restriction}: {result.data['risk']}",
                rationale=result.data["reasoning"], confidence=result.data["confidence"], llm=result,
            )
        return _INGREDIENT_CACHE[key]

    def _prior_decision(self, product_id: int, household_id: int, restrictions: list[dict]) -> EscalationCase | None:
        """Latest dietitian decision for this product and household — only if it was made
        against every restriction that applies now. A decision reviewed before a new
        allergy was added says nothing about that allergy, so it must not be reused."""
        current = {r["restriction"] for r in restrictions}
        cases = self.db.scalars(
            select(EscalationCase)
            .where(
                EscalationCase.product_id == product_id,
                EscalationCase.household_id == household_id,
                EscalationCase.status == CaseStatus.resolved,
            )
            .order_by(EscalationCase.resolved_at.desc())
        )
        for case in cases:
            if current <= {r["restriction"] for r in case.requirements}:
                return case
        return None


def _gap_suggestion(nutrient: str) -> str:
    return {
        "protein_g": "Add a protein such as eggs, lentils or chicken.",
        "veg_serves": "Add a bag of frozen mixed vegetables or fresh greens.",
        "kcal": "Add a staple such as rice, oats or potatoes.",
    }.get(nutrient, "Add more variety.")
