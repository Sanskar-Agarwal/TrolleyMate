"""«worker» NutritionComplianceAgent — cascading allergen & dietary checks, nutritional
adequacy, and escalation of uncertain cases (UC-06, 1.2.10, 1.2.11, 1.2.15).

Safety-first rules:
  - an ingredient (or any sub-ingredient, recursively) carrying a restricted tag → violation
  - a "may contain" warning for a severe allergy → violation; otherwise → uncertain
  - missing or empty ingredient list → uncertain
  - a record that can't be read, or a composite that contains itself → uncertain (UC-06 failure scenario)
  - vague label terms ("natural flavours") → the LLM judges the risk; low confidence → uncertain
  - uncertain items are never auto-accepted: they are withheld and escalated to a dietitian
  - a dietitian's past decision on the same product for the same household is reused

Nutritional adequacy (1.2.11): energy, protein, vegetables and staples against targets scaled to
the household and meals; gaps come with compliant candidate repairs, and a gap only stops
counting once the shopper explicitly accepts it.

Taste & preference memory (1.2.12): reports what each remembered preference does to later
baskets, with mandatory restrictions first (rules in services/preference_memory.py).

The verdict it returns is specified in services/compliance_verdict.py.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select

from app.agents.base import Agent
from app.core.config import get_settings
from app.domain import Basket, ComplianceVerdict, EscalationCase, Household, Ingredient, Product
from app.domain.enums import CaseStatus, ItemCompliance, Severity, VerdictStatus
from app.optimisation.types import Requirements
from app.services.catalogue import disliked_by, optimisable_products
from app.services.compliance_verdict import VerdictEvidence, outcome
from app.services.dietary_rules import label, normalise_restriction, violating_tags
from app.services.nutrition_targets import TARGETS_VERSION
from app.services.preference_memory import KINDS, favoured_by, matches, restriction_hint

# (ingredient, restriction, provider) → LLM judgement. Shared across requests: label
# semantics don't change, and this keeps real-LLM screening fast.
_INGREDIENT_CACHE: dict[tuple[str, str, str], dict] = {}
_SEVERITY_RANK = {Severity.severe: 3, Severity.moderate: 2, Severity.mild: 1, Severity.preference: 0}
# Food group whose products best close each nutrition gap.
_GAP_GROUP = {"protein_g": "protein", "veg_serves": "veg", "staple_serves": "carb"}


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
    MAX_REPAIR_PACKS = 6  # a repair needing more packs than this is offered as a partial fix

    def __init__(self, ctx):
        super().__init__(ctx)
        self.safety_threshold = get_settings().compliance_safety_threshold

    # --- Restrictions ------------------------------------------------------

    def restrictions_for(self, household: Household, payload: dict | None) -> list[dict]:
        """Household mandatory restrictions ∪ request restrictions, keeping the strictest severity."""
        rank = _SEVERITY_RANK
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
        elif not product.ingredients:
            f.add(ItemCompliance.uncertain, 0.4, kind="missing_data", detail="No ingredients listed, so safety can't be confirmed")
        for path, problem in self._integrity_problems(product):
            f.add(ItemCompliance.uncertain, 0.4, kind="data_error", detail=problem, **({"ingredient": path} if path else {}))

        for r in restrictions:
            rid, tags = r["restriction"], violating_tags(r["restriction"])
            for ingredient in product.ingredients:
                for path, ing, cycle in self._walk(ingredient):
                    if cycle:
                        continue  # already checked above it in the path; reported by _integrity_problems
                    hit = tags.intersection(_readable(ing.tags) or ())
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
            for warn in tags.intersection(_readable(product.may_contain) or ()):
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
        """1.2.11 — compares what the (non-withheld) basket provides against the requirements, which
        are already scaled to the household size and meal schedule. A gap only counts as acceptable
        while an exception the shopper accepted still covers it (see accept_nutrition_exception)."""
        provided = {k: 0.0 for k in ("kcal", "protein_g", "veg_serves", "staple_serves", "fibre_g")}
        for item in b.items:
            if not item.withheld:
                for k in provided:
                    provided[k] += _contribution(item.product, k) * item.quantity
        required = {"kcal": req.kcal, "protein_g": req.protein_g, "veg_serves": req.veg_serves, "staple_serves": req.carb_servings}
        exceptions = list((b.notes or {}).get("nutrition_exceptions", []))
        accepted_short = {e["nutrient"]: e["short_by"] for e in exceptions}
        coverage = []
        for k, v in required.items():
            short = round(v - provided[k], 1)
            met = provided[k] + 1e-6 >= v
            coverage.append({
                "nutrient": k, "required": round(v, 1), "provided": round(provided[k], 1),
                "coverage_pct": round(100 * provided[k] / v) if v else 100, "met": met,
                "accepted": not met and k in accepted_short and short <= accepted_short[k],
            })
        gaps = [
            {"nutrient": c["nutrient"], "required": c["required"], "provided": c["provided"],
             "short_by": round(required[c["nutrient"]] - provided[c["nutrient"]], 1)}
            for c in coverage if not c["met"]
        ]
        return {
            "adequate": all(c["met"] or c["accepted"] for c in coverage),
            "provided": {k: round(v, 1) for k, v in provided.items()},
            "required": {k: round(v, 1) for k, v in required.items()},
            "coverage": coverage,
            "gaps": gaps,
            "suggestions": [_gap_suggestion(g["nutrient"]) for g in gaps],
            "targets": TARGETS_VERSION,
            "exceptions": exceptions,
        }

    def current_nutrition(self, b: Basket) -> dict | None:
        """1.2.11 for the basket as it is now, against the requirements saved with it (None if it has
        none). The summary stored in notes goes stale when a dietitian releases or removes an item,
        or when extras are added after a rebuild."""
        req = saved_requirements(b)
        return self.assess_nutrition(b, req) if req else None

    def require_nutrition_adequate(self, b: Basket) -> None:
        """Gate for accepting a basket (1.2.11): every target met or explicitly accepted. Checked on the
        basket as it is now, so a stale summary can neither block a basket nor let one through."""
        nutrition = self.current_nutrition(b)
        if nutrition is None:
            return
        if not nutrition["adequate"]:
            raise ValueError(
                "Meet or accept the nutrition gaps before you accept the basket ("
                + "; ".join(_describe_gap(g) for g in _open_gaps(nutrition)) + ")."
            )
        b.notes = {**(b.notes or {}), "nutrition": nutrition}

    def nutrition_repairs(self, b: Basket, nutrition: dict, household: Household, payload: dict, limit: int = 3) -> list[dict]:
        """Candidate repairs for each open gap (1.2.11 "suggests changes"). Only products that pass
        every mandatory restriction for this household are offered (never an uncertain one), and
        not ones already in the basket or that the household dislikes. Nothing is changed."""
        open_gaps = {g["nutrient"]: g["short_by"] for g in _open_gaps(nutrition)}
        if not open_gaps:
            return []
        restrictions = self.restrictions_for(household, payload)
        preferences = payload.get("preferences", [])
        held = {i.product_id for i in b.items}
        pool = [p for p in optimisable_products(self.db) if p.id not in held and not disliked_by(p, preferences)]
        safe = [p for p in pool if self.screen_product(p, restrictions, household.id).status == ItemCompliance.compliant]
        offers = self.ctx.analyst.offers(safe)
        spare = None if b.budget is None else b.budget - b.total
        repairs: list[dict] = []
        for nutrient, short in open_gaps.items():
            options = []
            for o in offers:
                per_pack = _contribution(o.product, nutrient)
                if per_pack <= 0:
                    continue
                needed = math.ceil(short / per_pack - 1e-9)
                qty = min(needed, self.MAX_REPAIR_PACKS)
                cost = round(o.price * qty, 2)
                options.append({
                    "nutrient": nutrient, "product_id": o.product.id, "product": o.product.name, "quantity": qty,
                    "adds": round(per_pack * qty, 1), "closes_gap": qty == needed, "cost": cost,
                    "retailer": o.retailer.name, "within_budget": spare is None or cost <= spare + 1e-6,
                })
            # Suggest foods from the matching group first (protein for a protein gap, not 2 kg of rice).
            group = _GAP_GROUP.get(nutrient)
            category = {o.product.id: o.product.category for o in offers}
            options.sort(key=lambda r: (category[r["product_id"]] != group if group else False,
                                        not r["closes_gap"], not r["within_budget"], r["cost"]))
            repairs += options[:limit]
        self.log(
            "suggest_repairs", f"{len(repairs)} candidate repair(s) for {', '.join(open_gaps)}",
            rationale="Only products that pass every mandatory restriction for the household are suggested.",
            basket_id=b.id, session_id=b.session_id,
        )
        return repairs

    def accept_nutrition_exception(self, b: Basket, req: Requirements, nutrients: list[str], note: str = "") -> dict:
        """Record gaps the shopper explicitly accepts (UC-02 ext 4b). Only a current gap can be
        accepted, and this never touches allergen or dietary compliance."""
        gaps = {g["nutrient"]: g for g in self.assess_nutrition(b, req)["gaps"]}
        wanted = list(dict.fromkeys(nutrients))
        if not wanted or any(n not in gaps for n in wanted):
            not_gaps = [n for n in wanted if n not in gaps] or ["nothing"]
            raise ValueError(f"Only a current nutrition gap can be accepted; {', '.join(not_gaps)} is not one.")
        user = self.ctx.user
        when = datetime.now().isoformat(timespec="seconds")
        added = [
            {"nutrient": n, "short_by": gaps[n]["short_by"], "accepted_by": user.display_name if user else "unknown",
             "accepted_by_id": user.id if user else None, "accepted_at": when, "note": note.strip()[:300]}
            for n in wanted
        ]
        kept = [e for e in (b.notes or {}).get("nutrition_exceptions", []) if e["nutrient"] not in wanted]
        b.notes = {**(b.notes or {}), "nutrition_exceptions": kept + added}
        nutrition = self.assess_nutrition(b, req)
        b.notes = {**b.notes, "nutrition": nutrition}
        reason = note.strip() or "No reason given."
        self.log(
            "accept_nutrition_exception",
            "Shopper accepted the nutrition gap: " + "; ".join(f"{e['nutrient']} short by {e['short_by']:g}" for e in added),
            rationale=reason + ("" if reason[-1] in ".!?" else ".") + " Allergen and dietary restrictions are unchanged.",
            basket_id=b.id, session_id=b.session_id, confidence=1.0,
            payload={"exceptions": added, "adequate": nutrition["adequate"]},
        )
        return nutrition

    # --- Taste & preference memory (1.2.12) -------------------------------------

    def favoured_products(self, products: list[Product], screening: dict[int, Finding], preferences: list[str]) -> dict[int, str]:
        """Products a like or preferred brand nudges the optimiser towards, each with the reason to show.
        Only products screened compliant qualify, so a preference never pulls in a product that breaks a
        mandatory restriction or can't be confirmed safe."""
        favoured = {}
        for p in products:
            reason = favoured_by(p, preferences) if screening[p.id].status == ItemCompliance.compliant else None
            if reason:
                favoured[p.id] = reason
        return favoured

    def describe_preferences(self, household: Household) -> list[dict]:
        """Each remembered preference and what it does to later baskets. Mandatory restrictions come
        first: a liked product that breaks one, or can't be confirmed safe, is listed as blocked, and
        a like left with nothing else to match is `overridden`."""
        restrictions = self.restrictions_for(household, None)
        members = {r["restriction"]: r["members"] for r in household.mandatory_restrictions()}
        catalogue = optimisable_products(self.db)
        out = []
        for pref in household.preferences:
            known = pref.kind in KINDS  # anything else (e.g. older data) is still listed, so it can be forgotten
            kind = KINDS[pref.kind] if known else {"label": pref.kind.replace("_", " ").capitalize(), "effect": "unknown"}
            matched = [p for p in catalogue if matches(p, pref.kind, pref.value)] if known else []
            blocked: dict[int, dict] = {}
            if kind["effect"] == "favour":
                for p in matched:
                    f = self.screen_product(p, restrictions, household.id)
                    if f.status != ItemCompliance.compliant:
                        blocked[p.id] = {"product": p.name, "reason": _blocking_reason(f, members)}
            usable = [p.name for p in matched if p.id not in blocked]
            status = "no_match" if not matched else "applied" if usable else "overridden"
            out.append({
                "id": pref.id, "kind": pref.kind, "value": pref.value, "source": pref.source,
                "label": kind["label"], "effect": kind["effect"], "status": status,
                "matches": usable[:5], "match_count": len(usable), "blocked": list(blocked.values())[:5],
                "hint": restriction_hint(pref.kind, pref.value, set(members)),
                "created_at": pref.created_at.isoformat(timespec="seconds") if pref.created_at else None,
                "updated_at": (pref.meta or {}).get("updated_at"),
            })
        return out

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
        """Yield (path, ingredient, cycle) for the ingredient and every sub-ingredient (cascading check).
        `cycle` is True when the ingredient already appears above itself in the path; it isn't expanded again."""
        here = (*path, ingredient.name)
        if ingredient.id in seen:
            yield here, ingredient, True
            return
        yield here, ingredient, False
        for child in ingredient.components:
            yield from self._walk(child, here, seen | {ingredient.id})

    def _integrity_problems(self, product: Product) -> list[tuple[str, str]]:
        """(ingredient path, problem) for evidence that can't be trusted — the UC-06 failure
        scenario, 9.4 dataSourceError. The rest of the record is still checked."""
        problems = []
        if _readable(product.may_contain) is None:
            problems.append(("", "The label's may-contain statement can't be read"))
        for ingredient in product.ingredients:
            for path, ing, cycle in self._walk(ingredient):
                if cycle:
                    problems.append((" → ".join(path), f"{ing.name} lists itself as a sub-ingredient, so the record is corrupt"))
                elif _readable(ing.tags) is None:
                    problems.append((" → ".join(path), f"The ingredient record for {ing.name} can't be read"))
        return problems

    def _judge(self, product: Product, ingredient: Ingredient, restriction: str) -> dict:
        key = (ingredient.name, restriction, self.llm.provider_name)
        if key not in _INGREDIENT_CACHE:
            result = self.think("assess_ingredient", {"product": product.name, "ingredient": ingredient.name, "restriction": restriction})
            # A real model may answer 85 for 85%; the verdict contract only accepts 0-1.
            judgement = {**result.data, "confidence": min(max(float(result.data["confidence"]), 0.0), 1.0)}
            _INGREDIENT_CACHE[key] = judgement
            self.log(
                "assess_ingredient",
                f"'{ingredient.name}' vs {restriction}: {judgement['risk']}",
                rationale=judgement["reasoning"], confidence=judgement["confidence"], llm=result,
            )
        return _INGREDIENT_CACHE[key]

    def _prior_decision(self, product_id: int, household_id: int, restrictions: list[dict]) -> EscalationCase | None:
        """Latest dietitian decision for this product and household — only if it was made
        against every restriction that applies now, at the same severity or stricter. A decision
        reviewed before a new allergy was added, or before one became more severe, says nothing
        about the stricter rule, so it must not be reused."""
        def covers(case: EscalationCase) -> bool:
            reviewed = {r["restriction"]: _SEVERITY_RANK.get(r.get("severity"), 0) for r in case.requirements}
            return all(
                r["restriction"] in reviewed and reviewed[r["restriction"]] >= _SEVERITY_RANK.get(r.get("severity"), 3)
                for r in restrictions
            )

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
            if covers(case):
                return case
        return None


def saved_requirements(b: Basket) -> Requirements | None:
    """The scaled meal requirements saved when the basket was built, or None when there are none or
    they no longer fit Requirements (saved before a field was added). Callers then fall back to the
    stored summary instead of failing every read of an older basket."""
    saved = (b.notes or {}).get("requirements")
    if not isinstance(saved, dict) or not saved:
        return None
    fields = Requirements.__dataclass_fields__
    try:
        return Requirements(**{k: v for k, v in saved.items() if k in fields})
    except TypeError:
        return None


def _open_gaps(nutrition: dict) -> list[dict]:
    """Gaps the shopper hasn't explicitly accepted."""
    accepted = {c["nutrient"] for c in nutrition["coverage"] if c.get("accepted")}
    return [g for g in nutrition["gaps"] if g["nutrient"] not in accepted]


_GAP_NAMES = {"kcal": ("energy", "kcal"), "protein_g": ("protein", "g"), "veg_serves": ("vegetables", "serves"),
              "staple_serves": ("staples", "serves")}


def _describe_gap(gap: dict) -> str:
    name, unit = _GAP_NAMES.get(gap["nutrient"], (gap["nutrient"], ""))
    return f"{name} short by {gap['short_by']:,g} {unit}".rstrip()


def _contribution(product: Product, nutrient: str) -> float:
    """What one pack adds to a nutrient. Staples are counted as the optimiser counts them:
    servings of a grain or starch ("carb") pack."""
    if nutrient == "staple_serves":
        return float(product.servings) if product.category == "carb" else 0.0
    val = product.nutrition.get(nutrient, 0)
    return float(val if val is not None else 0)


def _blocking_reason(f: Finding, members: dict[str, list[str]]) -> str:
    """Why a liked product will never be offered: the restriction it breaks and whose it is."""
    hits = sorted({fd["restriction"] for fd in f.findings if fd.get("restriction")})
    named = ", ".join(label(r) + (f" ({', '.join(members[r])})" if members.get(r) else "") for r in hits)
    if f.status == ItemCompliance.violation:
        reviewed = any(fd.get("kind") == "human_review" for fd in f.findings)
        return named or ("A dietitian ruled it out for your household" if reviewed else "Breaks a dietary restriction")
    return "Safety can't be confirmed" + (f" for {named}" if named else "")


def _readable(values) -> set[str] | None:
    """A stored tag list as a set, or None when it isn't a list of strings."""
    if isinstance(values, list) and all(isinstance(v, str) for v in values):
        return set(values)
    return None


def _gap_suggestion(nutrient: str) -> str:
    return {
        "protein_g": "Add a protein such as eggs, lentils or chicken.",
        "veg_serves": "Add a bag of frozen mixed vegetables or fresh greens.",
        "kcal": "Add a staple such as rice, oats or potatoes.",
        "staple_serves": "Add a grain or starch for each main meal, such as rice, pasta or bread.",
    }.get(nutrient, "Add more variety.")
