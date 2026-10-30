"""Regression tests for the code-review fixes: path traversal, stale dietitian decisions,
the negotiation budget under Best Nutrition, and offline routing of budget edits."""


from app.agents.context import AgentContext
from app.core.db import SessionLocal
from app.domain import DietaryProfile, EscalationCase, Household, Product, User
from app.domain.enums import CaseStatus
from app.llm import get_llm
from app.llm.tasks.classify_intent import mock as classify
from app.llm.tasks.parse_edit import mock as parse_edit
from app.services.review_evidence import product_fingerprint
from tests.test_basket_flow import confirmed_session


def test_spa_route_cannot_escape_dist(tmp_path):
    from app.main import spa_file

    dist = (tmp_path / "dist").resolve()
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html>index")
    (dist / "assets" / "app.js").write_text("js")
    (tmp_path / "secret.env").write_text("LLM_API_KEY=leak")

    # The decoded form of GET /..%2fsecret.env — the HTTP client can't normalise it away here.
    assert spa_file(dist, "../secret.env") == dist / "index.html"
    assert spa_file(dist, "assets/../../secret.env") == dist / "index.html"
    assert spa_file(dist, "assets/app.js") == dist / "assets" / "app.js"
    assert spa_file(dist, "shop") == dist / "index.html"


def test_stale_dietitian_approval_is_not_reused_after_new_allergy(client, alex):
    with SessionLocal() as db:
        alex_user = db.query(User).filter_by(email="alex@trolleymate.demo").one()
        household = db.query(Household).filter_by(shopper_id=alex_user.id).one()
        schnitzel = db.query(Product).filter_by(sku="PRO-SCH-1K").one()
        ctx = AgentContext(db=db, llm=get_llm(), user=alex_user)
        restrictions = ctx.compliance.restrictions_for(household, None)
        db.add(EscalationCase(
            verdict_id=0, basket_id=0, household_id=household.id, product_id=schnitzel.id, reason="test",
            status=CaseStatus.resolved, resolution="passed", requirements=restrictions,
            evidence={"product_fingerprint": product_fingerprint(schnitzel)},
        ))
        db.flush()
        assert ctx.compliance.screen_product(schnitzel, restrictions, household.id).status == "compliant"

        # A coeliac member joins: the old approval never considered gluten.
        household.members[0].dietary_profiles.append(DietaryProfile(restriction="gluten", kind="allergy", severity="severe"))
        db.flush()
        db.refresh(household)
        now = ctx.compliance.restrictions_for(household, None)
        assert ctx.compliance.screen_product(schnitzel, now, household.id).status == "uncertain"
        db.rollback()


def test_best_nutrition_negotiation_offers_a_budget_that_works(client, riley):
    lowest = confirmed_session(client, riley, "$200 for the week, two meals a day for myself")
    floor = client.post(f"/api/sessions/{lowest}/basket", json={"goal": "lowest_cost"}, headers=riley).json()["basket"]["total"]
    tight = int(floor) + 1  # enough for the cheapest basket, not for Best Nutrition's higher bar
    sid = confirmed_session(client, riley, f"${tight} for the week, two meals a day for myself")
    r = client.post(f"/api/sessions/{sid}/basket", json={"goal": "best_nutrition"}, headers=riley).json()
    if r["status"] == "ok":
        return  # catalogue prices moved enough that it fits — nothing to negotiate
    budget_opt = next((o for o in r["negotiation"]["options"] if o["id"] == "increase_budget"), None)
    assert budget_opt is not None, r["negotiation"]["options"]
    r = client.post(f"/api/sessions/{sid}/negotiate", json={"option_id": "increase_budget", "budget": budget_opt["budget"], "goal": "best_nutrition"}, headers=riley).json()
    assert r["status"] == "ok"


def test_offline_router_understands_absolute_budget_edits():
    assert classify({"text": "Actually, make it $80", "state": {"has_basket": True}})["intent"] == "edit_basket"
    assert parse_edit({"text": "Actually, make it $80", "items": []})["budget_change"] == {"mode": "absolute", "amount": 80.0}
