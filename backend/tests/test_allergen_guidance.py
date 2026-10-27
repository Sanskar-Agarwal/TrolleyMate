"""1.2.10: ingredient checks are grounded in retrieved allergen guidance, including E-number additives."""

import pytest
from sqlalchemy import select

from app.agents.context import AgentContext
from app.core.db import SessionLocal
from app.domain import Product
from app.domain.enums import ItemCompliance
from app.llm import get_llm
from app.llm.tasks import assess_ingredient
from app.services.allergen_guidance import retrieve


@pytest.mark.parametrize("term,restriction,expected", [
    ("emulsifier (322)", "soy", "lecithin"),
    ("whey powder", "lactose", "whey"),
    ("glazing agent (904)", "vegan", "shellac"),
    ("colour (120)", "vegetarian", "carmine"),
    ("red curry paste", "shellfish", "curry-paste"),
])
def test_retrieval_finds_the_relevant_note(term, restriction, expected):
    assert [n.id for n in retrieve(term, restriction)][:1] == [expected]


def test_generic_words_alone_dont_match():
    assert retrieve("emulsifier (471)", "soy") == []
    assert retrieve("rice", "gluten") == []


def test_guidance_is_given_to_the_model():
    notes = [{"id": n.id, "text": n.text, "risk": n.risk} for n in retrieve("emulsifier (322)", "soy")]
    prompt = assess_ingredient.build_user({"product": "Dark Chocolate", "ingredient": "emulsifier (322)", "restriction": "soy",
                                           "guidance": notes, "source": "FSANZ"})
    assert "Emulsifier 322 is lecithin" in prompt


def _screen(sku: str, restriction: str) -> str:
    with SessionLocal() as db:
        product = db.scalar(select(Product).where(Product.sku == sku))
        agent = AgentContext(db=db, llm=get_llm()).compliance
        return agent.screen_product(product, [{"restriction": restriction, "severity": "severe", "label": restriction}]).status


@pytest.mark.parametrize("sku,restriction,status", [
    ("SNK-JEL-150", "vegetarian", ItemCompliance.violation),    # gelatine (441)
    ("SNK-MNT-35", "lactose", ItemCompliance.violation),        # sweetener (966) is lactitol
    ("SNK-CHO-45", "soy", ItemCompliance.uncertain),            # emulsifier (322) may be soy lecithin
    ("SNK-CHO-45", "lactose", ItemCompliance.compliant),
])
def test_e_number_additives_screen_correctly(client, sku, restriction, status):
    assert _screen(sku, restriction) == status
