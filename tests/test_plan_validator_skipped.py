from datetime import date

from src.planning.meal_slot import MealSlot
from src.planning.plan_state import PlanState
from src.planning.plan_validator import validate_plan


def test_skipped_slot_not_counted_as_unfilled():
    slots = [
        MealSlot(date(2026, 10, 7), "lunch"),
        MealSlot(date(2026, 10, 7), "dinner"),
        MealSlot(date(2026, 10, 8), "lunch"),
    ]

    state = PlanState(
        slots=slots,
        initial_budget=100.0,
    )

    for slot in slots[:2]:
        state.add_selected_meal(
            slot=slot,
            recipe_id="R001",
            decision={},
            estimated_cost=5.0,
        )

    state.mark_slot_skipped(slots[2])

    result = validate_plan(
        plan_state=state,
        all_items_priced=True,
        final_grocery_cost=10.0,
    )

    assert result["status"] == "feasible"
    assert result["issues"] == []
