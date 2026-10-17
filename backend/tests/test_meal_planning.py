"""KAN-4 meal scheduling and stock allocation regression coverage."""

import pytest

from app.domain.requests_constraints import ConstraintSet
from app.optimisation import Requirements
from app.services.meal_schedule import meal_schedule


@pytest.mark.parametrize("rate", [0.5, 1, 1.5, 2, 2.5, 3, 4, 5])
def test_basket_and_plan_agree_on_meal_counts(rate):
    schedule = meal_schedule(3, rate)
    req = Requirements.from_constraints(ConstraintSet.from_payload(
        {"household_size": 2, "days": 3, "meals_per_day": rate, "budget": 100}))
    assert req.person_meals == 2 * sum(map(len, schedule))
    assert req.main_meals + req.breakfast_meals == req.person_meals


def test_fractional_average_is_distributed_instead_of_rounded_daily():
    assert [len(day) for day in meal_schedule(4, 1.5)] == [2, 1, 2, 1]
