"""One deterministic meal schedule shared by basket sizing and meal planning."""

import math


def meal_schedule(days: int, meals_per_day: float) -> list[list[str]]:
    if not 1 <= days <= 31 or not math.isfinite(meals_per_day) or not 0 < meals_per_day <= 5:
        raise ValueError("Plan 1 to 31 days with more than zero and at most 5 meals per day.")
    names = {0: [], 1: ["Dinner"], 2: ["Lunch", "Dinner"],
             3: ["Breakfast", "Lunch", "Dinner"],
             4: ["Breakfast", "Lunch", "Dinner", "Extra meal 1"],
             5: ["Breakfast", "Lunch", "Dinner", "Extra meal 1", "Extra meal 2"]}
    return [names[math.ceil(day * meals_per_day) - math.ceil((day - 1) * meals_per_day)]
            for day in range(1, days + 1)]
