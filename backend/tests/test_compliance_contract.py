"""KAN-19: the compliance verdict contract (sequence 8.4, state machine 9.4), the adversarial
fixture catalogue in fixtures/compliance_cases.json, and the prototype nutrition targets."""

import dataclasses
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.agents import nutrition_compliance
from app.agents.context import AgentContext
from app.core.db import SessionLocal, reset_db
from app.domain import DietaryProfile, Household, HouseholdMember, Ingredient, Product
from app.domain.enums import VerdictStatus
from app.llm import get_llm
from app.llm.tasks import TASKS
from app.optimisation.types import Requirements
from app.services.compliance_verdict import NutritionCoverage, ProductResult, VerdictEvidence, outcome
from app.services.dietary_rules import RESTRICTION_RULES, normalise_restriction
from app.services.nutrition_targets import TARGETS, TARGETS_VERSION
from tests.test_basket_flow import confirmed_session

CATALOGUE = json.loads((Path(__file__).parent / "fixtures" / "compliance_cases.json").read_text(encoding="utf-8"))
CASES = CATALOGUE["cases"]
CATEGORIES = {"hidden_ingredient", "composite", "missing_information", "conflicting_restrictions"}


# --- Fixture catalogue ---------------------------------------------------------


def test_catalogue_covers_every_category_with_known_data():
    ids = [c["id"] for c in CASES]
    assert len(ids) == len(set(ids))
    counts = {cat: sum(c["category"] == cat for c in CASES) for cat in CATEGORIES}
    assert {c["category"] for c in CASES} == CATEGORIES
    assert all(n >= 3 for n in counts.values()), counts

    known = {i["name"] for i in CATALOGUE["ingredients"]}
    for i in CATALOGUE["ingredients"]:
        assert set(i.get("components", [])) <= known, i["name"]
    for c in CASES:
        assert set(c["product"]["ingredients"]) <= known, c["id"]
        stated = [r for held in c.get("members", {}).values() for r in held] + list(c.get("request", {}))
        assert all(normalise_restriction(r) in RESTRICTION_RULES for r in stated), c["id"]


def load_ingredients(db) -> dict[str, Ingredient]:
    """The catalogue's ingredient knowledge base, in an empty database."""
    ingredients = {
        i["name"]: Ingredient(name=i["name"], tags=i["tags"], ambiguous=i.get("ambiguous", False))
        for i in CATALOGUE["ingredients"]
    }
    for i in CATALOGUE["ingredients"]:
        ingredients[i["name"]].components = [ingredients[n] for n in i.get("components", [])]
    db.add_all(ingredients.values())
    db.flush()
    return ingredients


def make_product(ingredients: dict[str, Ingredient], spec: dict, sku: str) -> Product:
    return Product(
        sku=sku, name=spec["name"], category="pantry", pack_size=1, unit="each", tags=spec.get("tags", []),
        may_contain=spec.get("may_contain", []), data_complete=spec.get("data_complete", True),
        ingredients=[ingredients[n] for n in spec["ingredients"]],
    )


def make_household(members: dict[str, dict[str, str]]) -> Household:
    return Household(name="Fixture household", members=[
        HouseholdMember(name=name, dietary_profiles=[
            DietaryProfile(restriction=r, severity=s, kind=RESTRICTION_RULES[normalise_restriction(r)]["kind"])
            for r, s in held.items()
        ])
        for name, held in members.items()
    ])


def request_payload(case: dict) -> dict:
    return {"restrictions": [{"restriction": r, "severity": s} for r, s in case.get("request", {}).items()]}


@pytest.fixture()
def screen():
    """Load the fixture catalogue into an empty database and screen one case against it."""
    reset_db()
    with SessionLocal() as db:
        ingredients = load_ingredients(db)
        agent = AgentContext(db=db, llm=get_llm()).compliance

        def run(case: dict):
            product = make_product(ingredients, case["product"], "FX-1")
            db.add(product)
            db.flush()
            restrictions = agent.restrictions_for(make_household(case.get("members", {})), request_payload(case))
            return restrictions, agent.screen_product(product, restrictions)

        yield run
        db.rollback()


def _param(case: dict):
    marks = [pytest.mark.xfail(reason=case["pending"], strict=True)] if "pending" in case else []
    return pytest.param(case, id=case["id"], marks=marks)


@pytest.mark.parametrize("case", [_param(c) for c in CASES])
def test_fixture_case(screen, case):
    restrictions, finding = screen(case)
    expect = case["expect"]

    result = ProductResult.model_validate(finding.as_dict())  # every result honours the contract
    assert result.status == expect["status"]
    assert {e.kind for e in result.findings} == set(expect["kinds"])
    assert {e.restriction for e in result.findings if e.restriction} == set(expect["restrictions"])
    assert set(expect.get("paths", [])) <= {e.ingredient for e in result.findings}
    if "applied" in expect:
        assert {r["restriction"]: r["severity"] for r in restrictions} == expect["applied"]


@pytest.mark.parametrize("restriction", ["vegetarian", "vegan"])
def test_animal_rennet_is_excluded_for_both_diets(screen, restriction):
    _, finding = screen({
        "product": {"name": "Animal-rennet ingredient", "ingredients": ["animal rennet"]},
        "members": {"Shopper": {restriction: "moderate"}},
    })
    assert finding.status == "violation"
    assert any(f.get("restriction") == restriction for f in finding.findings)


def test_seed_parmesan_cascade_includes_animal_rennet(client):
    from sqlalchemy import select

    with SessionLocal() as db:
        parmesan = db.scalar(select(Ingredient).where(Ingredient.name == "parmesan"))
        product = Product(sku="TEST-PARMESAN", name="Seed parmesan", category="dairy", pack_size=1, unit="each",
                          tags=[], may_contain=[], data_complete=True, ingredients=[parmesan])
        db.add(product)
        db.flush()
        finding = AgentContext(db=db, llm=get_llm()).compliance.screen_product(
            product, [{"restriction": "vegetarian", "severity": "moderate"}])
        assert finding.status == "violation"
        assert any(f.get("ingredient") == "parmesan → animal rennet" for f in finding.findings)


# --- Verdict contract -----------------------------------------------------------


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        (["compliant", "compliant"], VerdictStatus.passed),
        (["compliant", "uncertain"], VerdictStatus.escalated),
        (["uncertain", "violation", "compliant"], VerdictStatus.failed),  # a violation outranks uncertainty
    ],
)
def test_outcome_follows_state_machine_9_4(statuses, expected):
    assert outcome(statuses) == expected


def test_contract_rejects_unexplained_or_unknown_evidence():
    with pytest.raises(ValidationError, match="at least one finding"):
        ProductResult(product_id=1, product="Bread", status="uncertain", confidence=0.4)
    with pytest.raises(ValidationError):
        ProductResult(product_id=1, product="Bread", status="passed", confidence=1.0)  # basket status, not a product one
    with pytest.raises(ValidationError):
        ProductResult(
            product_id=1, product="Bread", status="violation", confidence=1.0,
            findings=[{"kind": "contains", "detail": "Contains wheat", "surprise": True}],
        )


@pytest.mark.parametrize("risk", ["none", "possible"])
def test_out_of_range_llm_confidence_is_unchecked(screen, monkeypatch, risk):
    """A real model may answer 85 meaning 85%. That must not break the contract (and with it
    basket verification), and the vague ingredient must still be withheld as uncertain."""
    reply = {"risk": risk, "confidence": 85, "reasoning": "Replied in percent."}
    monkeypatch.setitem(TASKS, "assess_ingredient", dataclasses.replace(TASKS["assess_ingredient"], mock=lambda ctx: reply))
    monkeypatch.setattr(nutrition_compliance, "_INGREDIENT_CACHE", {})

    _, finding = screen(next(c for c in CASES if c["id"] == "hidden-natural-flavours-for-milk"))
    result = ProductResult.model_validate(finding.as_dict())
    assert result.status == "uncertain"
    assert result.confidence == 0.4


def test_stored_verdict_matches_the_contract(client, alex):
    sid = confirmed_session(client, alex, "$120 for the week, two meals a day")
    basket = client.post(f"/api/sessions/{sid}/basket", json={"goal": "lowest_cost"}, headers=alex).json()["basket"]
    verdicts = client.get(f"/api/baskets/{basket['id']}/verdicts", headers=alex).json()
    assert verdicts
    for v in verdicts:
        evidence = VerdictEvidence.model_validate(v["evidence"])
        assert v["status"] == outcome(p.status for p in evidence.products)
        assert {r.restriction for r in evidence.restrictions} >= {"lactose", "tree_nuts"}  # Alex's household
        assert evidence.nutrition is not None and evidence.nutrition.targets == TARGETS_VERSION


# --- Nutrition coverage and targets ---------------------------------------------


def test_nutrition_coverage_reports_every_target():
    def item(nutrition, quantity=1, withheld=False, category="carb", servings=4):
        product = SimpleNamespace(nutrition=nutrition, category=category, servings=servings)
        return SimpleNamespace(product=product, quantity=quantity, withheld=withheld)

    basket = SimpleNamespace(notes={}, items=[
        item({"kcal": 2300, "protein_g": 100, "veg_serves": 2}, quantity=2),
        item({"kcal": 9000, "protein_g": 900, "veg_serves": 90}, withheld=True),  # withheld items don't count
    ])
    req = SimpleNamespace(kcal=4400, protein_g=176, veg_serves=16, carb_servings=8, extra_minimums={})
    with SessionLocal() as db:
        report = NutritionCoverage.model_validate(AgentContext(db=db, llm=get_llm()).compliance.assess_nutrition(basket, req))

    coverage = {c.nutrient: (c.coverage_pct, c.met) for c in report.coverage}
    assert coverage == {"kcal": (105, True), "protein_g": (114, True), "veg_serves": (25, False), "staple_serves": (100, True)}
    assert [(g.nutrient, g.short_by) for g in report.gaps] == [("veg_serves", 12.0)]
    assert not report.adequate
    assert report.targets == TARGETS_VERSION


def test_requirements_scale_the_documented_targets():
    for t in TARGETS.values():
        assert t.reference and t.source and t.assumption, t.nutrient

    req = Requirements.from_constraints(SimpleNamespace(payload={"household_size": 2, "days": 7, "meals_per_day": 2}))
    assert req.kcal == TARGETS["kcal"].amount * req.person_meals
    assert req.protein_g == TARGETS["protein_g"].amount * req.main_meals
    assert req.veg_serves == TARGETS["veg_serves"].amount * req.main_meals
    assert req.carb_servings == TARGETS["staple_serves"].amount * req.main_meals
