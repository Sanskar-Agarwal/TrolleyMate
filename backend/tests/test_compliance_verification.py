"""KAN-20: cascading allergen and dietary checks over whole baskets (UC-06, activity 7.4,
state machine 9.4). Each basket is built from fixtures/compliance_cases.json products, verified,
and checked for the verdict, which items are withheld, the evidence, and escalation."""

import pytest
from sqlalchemy import select

from app.agents.context import AgentContext
from app.core.db import SessionLocal, reset_db
from app.domain import Basket, BasketItem, EscalationCase, User
from app.llm import get_llm
from app.services.compliance_verdict import VerdictEvidence
from tests.test_compliance_contract import CASES, load_ingredients, make_household, make_product

PRODUCTS = {c["id"]: c["product"] for c in CASES}


@pytest.fixture()
def verify():
    """Verify a basket of fixture products for a household, in an empty database."""
    reset_db()
    with SessionLocal() as db:
        ingredients = load_ingredients(db)
        agent = AgentContext(db=db, llm=get_llm()).compliance

        def run(case_ids: list[str], members: dict, request: dict | None = None):
            household = make_household(members)
            household.shopper = User(email="shopper@fixture.test", display_name="Fixture shopper", password_hash="-")
            basket = Basket(session_id=0, constraint_set_id=0, goal="balanced")
            for n, case_id in enumerate(case_ids):
                basket.add_item(BasketItem(
                    product=make_product(ingredients, PRODUCTS[case_id], f"FX-{n}"), retailer_id=0,
                    quantity=1, pack_price=1.0, line_total=1.0,
                ))
            db.add_all([household, basket])
            db.flush()
            payload = {"restrictions": [{"restriction": r, "severity": s} for r, s in (request or {}).items()]}
            verdict = agent.verify(basket, household, payload)
            cases = db.scalars(select(EscalationCase).where(EscalationCase.basket_id == basket.id)).all()
            return verdict, basket, cases

        yield run
        db.rollback()


COCONUT = "name-says-milk-but-is-not-dairy"  # a compliant product to sit alongside the others


@pytest.mark.parametrize(
    ("case_ids", "members", "request_", "expected_verdict", "expected_items"),
    [
        pytest.param(
            ["hidden-whey-in-crackers", "hidden-casein-under-dairy-free-label", COCONUT], {"Jamie": {"milk": "severe"}}, None,
            "failed", {"Sour Cream Rice Crackers": "violation", "Dairy-Free Cheese Slices": "violation", "Coconut Milk 400ml": "compliant"},
            id="hidden-allergen",
        ),
        pytest.param(
            ["composite-three-levels-shellfish", "composite-soy-sauce-gluten", COCONUT],
            {"Jamie": {"shellfish": "severe"}, "Sam": {"coeliac": "severe"}}, None,
            "failed", {"Thai Red Curry Simmer Sauce": "violation", "Teriyaki Marinade": "violation", "Coconut Milk 400ml": "compliant"},
            id="composite",
        ),
        pytest.param(
            ["conflict-severity-across-members", COCONUT], {"Jamie": {"peanuts": "severe"}, "Sam": {"peanuts": "mild"}}, {"peanuts": "mild"},
            "failed", {"Honey Muesli Bar": "violation", "Coconut Milk 400ml": "compliant"},
            id="conflicting-rule",
        ),
        pytest.param(
            ["missing-ingredient-list", "missing-empty-list-marked-complete", COCONUT], {"Jamie": {"peanuts": "severe"}}, None,
            "escalated", {"Value Fish Fingers": "uncertain", "Mystery Snack Mix": "uncertain", "Coconut Milk 400ml": "compliant"},
            id="missing-evidence",
        ),
        pytest.param(
            ["missing-corrupt-ingredient-record", "composite-cycle-is-corrupt-data", COCONUT], {"Jamie": {"milk": "severe"}}, None,
            "escalated", {"Imported Biscuits": "uncertain", "Gravy Granules": "uncertain", "Coconut Milk 400ml": "compliant"},
            id="corrupt-evidence",
        ),
        pytest.param(
            ["hidden-whey-in-crackers", "missing-ingredient-list"], {"Jamie": {"milk": "severe"}}, None,
            "failed", {"Sour Cream Rice Crackers": "violation", "Value Fish Fingers": "uncertain"},
            id="violation-outranks-uncertainty",
        ),
    ],
)
def test_basket_verdict(verify, case_ids, members, request_, expected_verdict, expected_items):
    verdict, basket, cases = verify(case_ids, members, request_)

    assert verdict.status == expected_verdict
    assert {i.product.name: i.compliance for i in basket.items} == expected_items
    # Uncertain or missing evidence blocks automatic insertion (UC-06 ext 2a), whatever the verdict.
    assert {i.product.name for i in basket.items if i.withheld} == {n for n, s in expected_items.items() if s == "uncertain"}

    # Evidence and uncertainty come back in the structured verdict for the other agents
    # (the contract itself requires every non-compliant product to carry its findings).
    evidence = VerdictEvidence.model_validate(verdict.evidence)
    assert {p.product: p.status for p in evidence.products} == expected_items

    # Only an escalated verdict requests human review — one case per withheld item.
    expected_cases = {n for n, s in expected_items.items() if s == "uncertain"} if expected_verdict == "escalated" else set()
    assert {c.product.name for c in cases} == expected_cases


def test_conflicting_rules_keep_the_strictest_severity_in_the_verdict(verify):
    verdict, _, _ = verify(["conflict-severity-across-members"], {"Jamie": {"peanuts": "severe"}, "Sam": {"peanuts": "mild"}}, {"peanuts": "mild"})
    applied = {r.restriction: r.severity for r in VerdictEvidence.model_validate(verdict.evidence).restrictions}
    assert applied == {"peanuts": "severe"}


def test_corrupt_record_is_reported_with_its_path(verify):
    verdict, _, cases = verify(["composite-cycle-is-corrupt-data"], {"Jamie": {"milk": "severe"}})
    (product,) = VerdictEvidence.model_validate(verdict.evidence).products
    assert [(e.kind, e.ingredient) for e in product.findings] == [("data_error", "stock base → flavour base → stock base")]
    assert cases and "lists itself as a sub-ingredient" in cases[0].reason  # the dietitian sees why
