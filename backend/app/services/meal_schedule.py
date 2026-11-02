"""One deterministic meal schedule shared by basket sizing and meal planning."""

import math


def meal_schedule(days: int, meals_per_day: float, meal_count: int | None = None) -> list[list[str]]:
    if not 1 <= days <= 31 or not math.isfinite(meals_per_day) or not 0 < meals_per_day <= 5:
        raise ValueError("Plan 1 to 31 days with more than zero and at most 5 meals per day.")
    names = {0: [], 1: ["Dinner"], 2: ["Lunch", "Dinner"],
             3: ["Breakfast", "Lunch", "Dinner"],
             4: ["Breakfast", "Lunch", "Dinner", "Extra meal 1"],
             5: ["Breakfast", "Lunch", "Dinner", "Extra meal 1", "Extra meal 2"]}
    schedule = [names[math.ceil(day * meals_per_day - 1e-9) - math.ceil((day - 1) * meals_per_day - 1e-9)]
                for day in range(1, days + 1)]
    if meal_count is None:
        return schedule
    if not 1 <= meal_count <= sum(map(len, schedule)):
        raise ValueError("Meal count must fit the requested schedule.")
    remaining = meal_count
    limited = []
    for slots in schedule:
        taken = slots[:remaining]
        limited.append(taken)
        remaining -= len(taken)
        if remaining == 0:
            break
    return limited
