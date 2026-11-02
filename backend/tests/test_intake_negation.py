"""Non-food negations must not become food dislikes in the offline parser."""
import pytest

from app.llm.tasks.extract_constraints import mock


@pytest.mark.parametrize("phrase", ["No allergies", "No dietary restrictions", "No preferences", "No time to cook"])
def test_non_food_negation_is_not_a_dislike(phrase):
    result = mock({"text": "$80 for 3 days, two meals a day for one adult. " + phrase})
    assert result["preferences"] == []

def test_food_dislike_remains_supported():
    assert "dislike:mushroom" in mock({"text": "No mushrooms"})["preferences"]
