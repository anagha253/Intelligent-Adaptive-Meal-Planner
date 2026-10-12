from datetime import date

import pytest

from src.planning.meal_slot import (
    generate_meal_slots,
)

from src.planning.plan_state import (
    PlanState,
)

from src.planning.plan_validator import (
    validate_plan,
)

from src.planning.multi_meal_planner import (
    MultiMealPlanner,
)

from src.input_parser.natural_language_parser import UserInputParser

# ======================================================
# FAKES
# ======================================================


class FakeRecipeAgent:
    def __init__(self):
        self.calls = []

    def run(
        self,
        user_state,
        meal_slot,
        selected_recipe_ids=None,
        recent_cuisines=None,
        max_candidates=None,
    ):
        selected_recipe_ids = selected_recipe_ids or []

        self.calls.append(
            {
                "user_state": user_state,
                "meal_slot": meal_slot,
                "selected_recipe_ids": selected_recipe_ids,
                "max_candidates": max_candidates,
            }
        )

        candidates = [
            "R001",
            "R002",
            "R003",
            "R004",
            "R005",
            "R006",
            "R007",
        ]

        candidates = [
            recipe_id
            for recipe_id in candidates
            if recipe_id not in selected_recipe_ids
        ]

        if max_candidates is not None:
            candidates = candidates[:max_candidates]

        return {
            "agent": "recipe",
            "status": "success",
            "data": {"candidate_recipe_ids": candidates},
            "warnings": [],
            "errors": [],
        }


class FakeManager:
    def __init__(self):
        self.recipe_agent = FakeRecipeAgent()
        self.calls = []

    def evaluate_candidate(
        self,
        recipe_id,
        user_state,
        meal_context,
        defer_budget_to_planner=False,
    ):
        self.calls.append(recipe_id)

        if recipe_id == "R001":
            return {
                "recipe_id": recipe_id,
                "status": "rejected",
                "reasoning": {
                    "status": "rejected",
                    "hard_constraints": [
                        {
                            "constraint": "allergy",
                            "status": "fail",
                            "reason": "Peanut allergy",
                        }
                    ],
                    "failed_constraints": ["allergy"],
                },
            }

        # Give each recipe a distinct test ingredient.
        ingredient_id = f"ING_{recipe_id}"
        ingredient_name = f"test_ingredient_{recipe_id}"

        return {
            "recipe_id": recipe_id,
            "status": "feasible",
            "overall_score": 0.8,
            "recipe": {
                "recipe_id": recipe_id,
                "calories_per_serving": 450.0,
                "protein_g_per_serving": 20.0,
                "carbs_g_per_serving": 55.0,
                "fat_g_per_serving": 15.0,
            },
            "reasoning": {
                "status": "feasible",
                "hard_constraints": [
                    {
                        "constraint": "diet",
                        "status": "pass",
                    },
                    {
                        "constraint": "allergy",
                        "status": "pass",
                    },
                    {
                        "constraint": "cooking_time",
                        "status": "pass",
                    },
                    {
                        "constraint": "ingredient_feasibility",
                        "status": "pass",
                    },
                ],
            },
            "ingredient": {
                "recipe_id": recipe_id,
                "required_ingredients": [
                    {
                        "ingredient_id": ingredient_id,
                        "ingredient_name": ingredient_name,
                        "quantity": 100.0,
                        "unit": "g",
                    }
                ],
            },
            "grocery": {
                "recipe_id": recipe_id,
                "items": [
                    {
                        "ingredient_id": ingredient_id,
                        "ingredient": ingredient_name,
                        "required_quantity": 100.0,
                        "required_unit": "g",
                        "product_name": ingredient_name,
                        "package_quantity": 100.0,
                        "package_unit": "g",
                        "packages_needed": 1,
                        "price_per_package": 5.0,
                        "total_cost": 5.0,
                    }
                ],
                "known_cost": 5.0,
                "all_items_priced": True,
                "projected_cost": 5.0,
                "projected_cost_complete": True,
            },
        }


# ======================================================
# MEAL SLOT TESTS
# ======================================================


def test_generate_six_slots():

    slots = generate_meal_slots(
        start_date=date(
            2026,
            10,
            5,
        ),
        days=3,
        meal_types=[
            "lunch",
            "dinner",
        ],
    )

    assert len(slots) == 6

    assert slots[0].meal_type == "lunch"

    assert slots[1].meal_type == "dinner"


def test_slot_ids_are_unique():

    slots = generate_meal_slots(
        start_date=date(
            2026,
            10,
            5,
        ),
        days=3,
        meal_types=[
            "lunch",
            "dinner",
        ],
    )

    ids = [slot.slot_id for slot in slots]

    assert len(ids) == len(set(ids))


# ======================================================
# PLAN STATE TESTS
# ======================================================


def test_plan_state_budget():

    slots = generate_meal_slots(
        date(
            2026,
            10,
            5,
        ),
        1,
        ["lunch"],
    )

    state = PlanState(
        slots=slots,
        initial_budget=50.0,
    )

    state.add_selected_meal(
        slot=slots[0],
        recipe_id="R001",
        decision={"status": "feasible"},
        estimated_cost=12.0,
    )

    assert state.estimated_spent == 12.0

    assert state.remaining_budget == 38.0


def test_recipe_marked_used():

    slots = generate_meal_slots(
        date(
            2026,
            10,
            5,
        ),
        1,
        ["lunch"],
    )

    state = PlanState(
        slots=slots,
        initial_budget=50,
    )

    state.add_selected_meal(
        slots[0],
        "R100",
        {"status": "feasible"},
        5,
    )

    assert "R100" in state.used_recipe_ids


# ======================================================
# VALIDATOR TESTS
# ======================================================


def test_complete_plan_feasible():

    slots = generate_meal_slots(
        date(
            2026,
            10,
            5,
        ),
        1,
        ["lunch"],
    )

    state = PlanState(
        slots=slots,
        initial_budget=50,
    )

    state.add_selected_meal(
        slots[0],
        "R001",
        {"status": "feasible"},
        10,
    )

    result = validate_plan(
        state,
        all_items_priced=True,
        final_grocery_cost=10,
    )

    assert result["status"] == "feasible"


def test_over_budget_plan_infeasible():

    slots = generate_meal_slots(
        date(
            2026,
            10,
            5,
        ),
        1,
        ["lunch"],
    )

    state = PlanState(
        slots=slots,
        initial_budget=10,
    )

    state.add_selected_meal(
        slots[0],
        "R001",
        {"status": "feasible"},
        5,
    )

    result = validate_plan(
        state,
        all_items_priced=True,
        final_grocery_cost=20,
    )

    assert result["status"] == "infeasible"


def test_unknown_price_plan_uncertain():

    slots = generate_meal_slots(
        date(
            2026,
            10,
            5,
        ),
        1,
        ["lunch"],
    )

    state = PlanState(
        slots=slots,
        initial_budget=50,
    )

    state.add_selected_meal(
        slots[0],
        "R001",
        {"status": "feasible"},
        5,
    )

    result = validate_plan(
        state,
        all_items_priced=False,
        final_grocery_cost=5,
    )

    assert result["status"] == "uncertain"


# ======================================================
# MULTI-MEAL PLANNER
# ======================================================


def test_three_day_six_meal_plan():

    manager = FakeManager()

    planner = MultiMealPlanner(
        manager=manager,
        max_candidates_per_slot=7,
    )

    result = planner.plan_meals(
        user_state={
            "budget_remaining": 50,
        },
        start_date=date(
            2026,
            10,
            5,
        ),
        days=3,
        meal_types=[
            "lunch",
            "dinner",
        ],
    )

    plan = result["plan"]

    assert len(plan["slots"]) == 6

    assert len(plan["selected_meals"]) == 6

    assert result["validation"]["status"] == "feasible"


def test_rejected_candidate_retries():

    manager = FakeManager()

    planner = MultiMealPlanner(manager)

    result = planner.plan_meals(
        user_state={"budget_remaining": 50},
        start_date=date(
            2026,
            10,
            5,
        ),
        days=1,
        meal_types=["lunch"],
    )

    plan = result["plan"]

    # R001 should fail allergy

    assert any(item["recipe_id"] == "R001" for item in plan["rejected_candidates"])

    # Planner should retry and select R002

    assert plan["selected_meals"][0]["recipe_id"] == "R002"


def test_repeated_recipe_can_fill_multiple_slots():
    class SingleRecipeAgent:
        def run(
            self,
            user_state,
            meal_slot,
            selected_recipe_ids=None,
            recent_cuisines=None,
            max_candidates=None,
        ):
            return {
                "candidate_recipe_ids": (
                    ["R002"] if "R002" not in (selected_recipe_ids or []) else []
                )
            }

    manager = FakeManager()
    manager.recipe_agent = SingleRecipeAgent()

    planner = MultiMealPlanner(
        manager=manager,
        max_candidates_per_slot=5,
    )

    result = planner.plan_meals(
        user_state={
            "budget_remaining": 100,
            "max_recipe_repetitions": 3,
        },
        start_date=date(2026, 10, 5),
        days=3,
        meal_types=["lunch"],
    )

    selected = result["plan"]["selected_meals"]

    assert len(selected) == 3
    assert [meal["recipe_id"] for meal in selected] == ["R002", "R002", "R002"]

    slot_ids = [meal["slot"]["slot_id"] for meal in selected]
    assert len(slot_ids) == len(set(slot_ids))


def test_skip_and_replan_preserves_completed_meal_and_skips_requested_slot():
    planner = MultiMealPlanner(manager=FakeManager(), max_candidates_per_slot=7)
    planner.plan_meals(
        user_state={"budget_remaining": 100},
        start_date=date(2026, 10, 5),
        days=3,
        meal_types=["lunch"],
    )

    original_state = planner.last_plan_state
    assert original_state is not None
    assert len(original_state.selected_meals) == 3

    slots = original_state.slots
    completed_id = slots[0].slot_id
    skipped_id = slots[1].slot_id
    remaining_id = slots[2].slot_id

    completed_recipe = next(
        meal["recipe_id"]
        for meal in original_state.selected_meals
        if meal["slot"]["slot_id"] == completed_id
    )

    rebuilt = planner.skip_and_replan(
        user_state={"budget_remaining": 100},
        plan_state=original_state,
        slot_id=skipped_id,
        completed_slot_ids={completed_id},
    )

    plan = rebuilt["plan"]
    selected_by_slot = {
        meal["slot"]["slot_id"]: meal for meal in plan["selected_meals"]
    }

    assert selected_by_slot[completed_id]["recipe_id"] == completed_recipe
    assert skipped_id not in selected_by_slot
    assert remaining_id in selected_by_slot
    assert {item["slot_id"] for item in plan["skipped_slots"]} == {skipped_id}
    assert any(
        event["event"] == "plan_rebuilt_after_skip" for event in plan["execution_trace"]
    )
    assert len(original_state.selected_meals) == 3
    assert not original_state.skipped_slots


def test_reconcile_inventory_records_qualitative_requirements():
    planner = MultiMealPlanner(manager=FakeManager())

    slots = generate_meal_slots(
        date(2026, 10, 5),
        1,
        ["lunch"],
    )
    state = PlanState(
        slots=slots,
        initial_budget=50,
        initial_inventory={
            "rice": {"quantity": 500.0, "unit": "g"},
            "salt": {"quantity": 100.0, "unit": "g"},
        },
    )
    state.selected_meals = [
        {
            "slot": slots[0].to_dict(),
            "recipe_id": "R001",
            "decision": {
                "ingredient": {
                    "required_ingredients": [
                        {
                            "ingredient_name": "rice",
                            "quantity": "100",
                            "unit": "g",
                        },
                        {
                            "ingredient_name": "salt",
                            "quantity": "required",
                            "unit": "to taste",
                        },
                    ]
                }
            },
        }
    ]

    result = planner._reconcile_final_inventory(
        state,
        {"items": []},
    )

    assert result is True
    assert state.current_inventory["rice"]["quantity"] == pytest.approx(400.0)
    assert any(
        event.get("event") == "qualitative_requirement_unresolved"
        and event.get("ingredient_name") == "salt"
        for event in state.execution_trace
    )
    assert not any(
        event.get("event") == "inventory_reconciled" for event in state.execution_trace
    )


def test_beam_search_respects_cooking_frequency():
    manager = FakeManager()

    planner = MultiMealPlanner(
        manager=manager,
        max_candidates_per_slot=7,
    )

    result = planner.plan_meals(
        user_state={
            "budget_remaining": 100,
            "cook_frequency": 2,
            "max_recipe_repetitions": 4,
        },
        start_date=date(2026, 10, 12),
        days=2,
        meal_types=["lunch", "dinner"],
    )

    plan = result["plan"]
    cooking = plan["cooking_schedule"]

    assert len(plan["selected_meals"]) == 4
    assert cooking["valid"] is True

    assert all(count <= 2 for count in cooking["weekly_session_counts"].values())

    assert sum(session["portions_prepared"] for session in cooking["sessions"]) == 4

    assert result["validation"]["status"] == "feasible"


def test_beam_search_does_not_exceed_cooking_limit():
    manager = FakeManager()

    planner = MultiMealPlanner(
        manager=manager,
        max_candidates_per_slot=7,
    )

    result = planner.plan_meals(
        user_state={
            "budget_remaining": 100,
            "cook_frequency": 1,
            "max_recipe_repetitions": 1,
        },
        start_date=date(2026, 10, 12),
        days=2,
        meal_types=["lunch", "dinner"],
    )

    plan = result["plan"]
    cooking = plan["cooking_schedule"]

    assert cooking["valid"] is True

    assert all(count <= 1 for count in cooking["weekly_session_counts"].values())

    assert len(plan["selected_meals"]) < 4
    assert result["validation"]["status"] in {
        "partial",
        "infeasible",
    }


def test_parser_cooking_frequency_reaches_planner():
    parser = UserInputParser()

    parsed = parser.parse("I have a budget of 100 dollars. " "I can cook twice a week.")

    assert parsed.valid, parsed.errors
    assert parsed.data["cook_frequency"] == 2

    planner = MultiMealPlanner(
        manager=FakeManager(),
        max_candidates_per_slot=7,
    )

    result = planner.plan_meals(
        user_state={
            **parsed.data,
            "budget_remaining": 100,
            "max_recipe_repetitions": 4,
        },
        start_date=date(2026, 10, 12),
        days=2,
        meal_types=["lunch", "dinner"],
    )

    cooking = result["plan"]["cooking_schedule"]

    assert cooking["max_sessions_per_week"] == 2
    assert cooking["valid"] is True
    assert len(result["plan"]["selected_meals"]) == 4
