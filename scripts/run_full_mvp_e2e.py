"""Full MVP smoke test: input -> planning -> skip -> replan."""

from copy import deepcopy
from datetime import date

from src.input_parser.natural_language_parser import UserInputParser
from src.planning.plan_state import PlanState
from scripts.run_day5_e2e import build_system, USER_STATE


def main():
    print("\n=== 1. PARSE USER REQUEST ===")

    request = (
        "I have a budget of 100 dollars. "
        "I am vegetarian and allergic to peanuts. "
        "I prefer Asian food and can cook for 30 minutes. "
        "I can cook twice a week."
    )

    parsed = UserInputParser().parse(request)

    assert parsed.valid, parsed.errors

    # Use known test defaults for fields not supplied in text.
    user_state = deepcopy(USER_STATE)
    user_state.update(
        {
            key: value
            for key, value in parsed.data.items()
            if value is not None and value != [] and value != {}
        }
    )

    assert parsed.data["cook_frequency"] == 2

    assert user_state["cook_frequency"] == 2
    assert (
        user_state.get("cooking_sessions_per_week") is None
        or user_state["cooking_sessions_per_week"] == 2
    )
    print("Cooking frequency:", user_state["cook_frequency"])

    print("PASS: Input parsed and validated")

    print("\n=== 2. GENERATE INITIAL PLAN ===")

    planner = build_system()

    initial = planner.plan_meals(
        user_state=user_state,
        start_date=date(2026, 10, 7),
        days=2,
        meal_types=["lunch", "dinner"],
        nutrition_targets=user_state.get("nutrition_targets"),
    )

    initial_plan = initial["plan"]
    cooking = initial_plan["cooking_schedule"]

    print("Cooking sessions:", cooking["session_count"])
    print("Weekly counts:", cooking["weekly_session_counts"])
    print("Cooking schedule valid:", cooking["valid"])

    assert cooking["max_sessions_per_week"] == 2

    assert (
        all(count <= 2 for count in cooking["weekly_session_counts"].values())
        == cooking["valid"]
    )

    if not cooking["valid"]:
        assert initial["validation"]["status"] == "infeasible"

    assert sum(session["portions_prepared"] for session in cooking["sessions"]) == len(
        initial_plan["selected_meals"]
    )

    selected = initial_plan["selected_meals"]

    assert len(initial_plan["slots"]) == 4
    assert len(selected) >= 2, "Need at least two selected meals for this scenario"

    print(f"PASS: {len(selected)}/4 meals selected")

    print("\n=== 3. RESTORE PLAN STATE ===")

    restored = PlanState.from_dict(initial_plan)

    assert restored.to_dict() == initial_plan

    print("PASS: PlanState round-trip")

    print("\n=== 4. SKIP A FUTURE MEAL ===")

    completed_id = selected[0]["slot"]["slot_id"]
    skipped_id = selected[1]["slot"]["slot_id"]

    original_completed = deepcopy(selected[0])

    updated = planner.skip_and_replan(
        user_state=user_state,
        plan_state=restored,
        slot_id=skipped_id,
        completed_slot_ids={completed_id},
        nutrition_targets=user_state.get("nutrition_targets"),
    )

    updated_plan = updated["plan"]
    updated_meals = updated_plan["selected_meals"]

    updated_cooking = updated_plan["cooking_schedule"]

    assert updated_cooking["max_sessions_per_week"] == 2

    assert (
        all(count <= 2 for count in updated_cooking["weekly_session_counts"].values())
        == updated_cooking["valid"]
    )

    assert sum(
        session["portions_prepared"] for session in updated_cooking["sessions"]
    ) == len(updated_meals)

    if not updated_cooking["valid"]:
        assert updated["validation"]["status"] == "infeasible"

    print("Updated cooking sessions:", updated_cooking["session_count"])
    print("Updated cooking schedule valid:", updated_cooking["valid"])

    updated_by_slot = {meal["slot"]["slot_id"]: meal for meal in updated_meals}

    assert completed_id in updated_by_slot
    assert updated_by_slot[completed_id] == original_completed

    assert skipped_id not in updated_by_slot

    assert any(item["slot_id"] == skipped_id for item in updated_plan["skipped_slots"])

    assert len(updated_by_slot) == len(updated_meals)

    print("PASS: Completed meal preserved")
    print("PASS: Skipped meal removed")
    print("PASS: No duplicate meal assignments")

    print("\n=== 5. VALIDATE UPDATED PLAN ===")

    basket = updated["grocery_basket"]
    validation = updated["validation"]

    assert isinstance(basket, dict)
    assert isinstance(updated_plan["inventory"], dict)
    assert updated["nutrition_summary"] is not None

    assert validation["status"] in {"feasible", "uncertain", "partial", "infeasible"}

    print("\n=== INVENTORY RECONCILIATION DEBUG ===")

    for event in updated_plan["execution_trace"]:
        if event.get("event") == "inventory_reconciliation_failed":
            print("Reason:", event.get("reason"))
            print("Unresolved count:", event.get("unresolved_count"))
            print("Error count:", event.get("error_count"))

            for detail in event.get("details", []):
                print(
                    "Recipe:",
                    detail.get("recipe_id"),
                    "| Ingredient:",
                    detail.get("ingredient_name"),
                    "| Error:",
                    detail.get("reason"),
                )
    assert not any(
        event.get("event") == "inventory_reconciliation_failed"
        for event in updated_plan["execution_trace"]
    ), "Inventory reconciliation failed"

    projected = basket.get("projected_cost")

    if basket.get("projected_cost_complete") is True:
        assert projected is not None
        assert float(projected) <= float(updated_plan["budget"]["initial"]) + 1e-6

    assert initial_plan["selected_meals"] == selected

    print("Updated validation:", validation)
    print("Updated projected cost:", projected)
    print("PASS: Basic replanning invariants")

    print("\nFULL MVP SMOKE TEST PASSED")


if __name__ == "__main__":
    main()
