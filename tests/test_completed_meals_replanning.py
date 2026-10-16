"""Completed meals, skipped slots and leftovers through the unchanged
Streamlit replanning page (see tests/streamlit_flow.py).

Plan 15-19 Oct 2026, lunch + dinner. Thursday and Friday are marked
eaten, one serving of Thursday dinner is recorded as a leftover,
Saturday dinner is skipped with the leftover approved.
"""
import copy
from datetime import date

import pytest

from tests.planning_harness import repository
from tests.streamlit_flow import Flow

EATEN = {"2026-10-15_lunch", "2026-10-15_dinner", "2026-10-16_lunch", "2026-10-16_dinner"}
SKIPPED = "2026-10-17_dinner"
LATER_SKIP = "2026-10-18_dinner"


def run_flow(state_dir, use_by, save_completed=True, second_skip=False):
    with pytest.MonkeyPatch.context() as mp:
        flow = Flow(state_dir, mp).open().generate()
        generated = copy.deepcopy(flow.plan)
        if save_completed:
            flow.save_completed(["Thu,", "Fri,"])
        else:
            flow.select_completed(["Thu,", "Fri,"])  # selected, never saved
        after_completed = {"current": flow.current_meal_slots,
                           "history": flow.history_meal_slots}
        cooked = flow.meal("2026-10-15_dinner")["recipe_id"]
        flow.record_leftover(cooked, date(2026, 10, 15), use_by)
        flow.skip("Sat, 17 Oct 2026 · Dinner")
        first = copy.deepcopy(flow.plan)
        observed = {"current": flow.current_meal_slots, "history": flow.history_meal_slots}
        if second_skip:
            flow.skip("Sun, 18 Oct 2026 · Dinner")
        flow.run().run()  # plain reruns
        reruns = {"current": flow.current_meal_slots, "history": flow.history_meal_slots,
                  "completed": flow.completed}
        return {"flow": flow, "generated": generated, "first": first, "cooked": cooked,
                "after_completed": after_completed, "observed": observed,
                "reruns": reruns, "final": copy.deepcopy(flow.plan),
                "result": copy.deepcopy(flow.at.session_state["planner_result"]),
                "saved": flow.saved_workspace()}


@pytest.fixture(scope="module")
def saved(tmp_path_factory):
    return run_flow(tmp_path_factory.mktemp("saved"), date(2026, 10, 18), second_skip=True)


@pytest.fixture(scope="module")
def expired(tmp_path_factory):
    return run_flow(tmp_path_factory.mktemp("expired"), date(2026, 10, 15))


def by_slot(plan):
    return {m["slot"]["slot_id"]: m for m in plan["selected_meals"]}


def active(plan, completed):
    skipped = {s["slot_id"] for s in plan["skipped_slots"]}
    return [s["slot_id"] for s in plan["slots"]
            if s["slot_id"] not in completed and s["slot_id"] not in skipped]


# ============================================================
# Completed meals
# ============================================================

def test_completed_meals_stay_in_history_unchanged(saved):
    before, after = by_slot(saved["generated"]), by_slot(saved["final"])
    for slot_id in EATEN:
        assert after[slot_id] == before[slot_id]


def test_completed_meals_leave_current_meals(saved):
    assert saved["after_completed"]["history"] == sorted(EATEN, key=lambda s: (s[:10], "d" in s[11:]))
    assert not EATEN & set(saved["after_completed"]["current"])
    assert not EATEN & set(saved["observed"]["current"])
    assert set(saved["observed"]["history"]) == EATEN


def test_replan_receives_saved_completed_ids(saved):
    rebuilt = [e for e in saved["final"]["execution_trace"] if e["event"] == "plan_rebuilt_after_skip"]
    assert [set(e["completed_slot_ids"]) for e in rebuilt] == [EATEN, EATEN]


def test_current_meals_are_exactly_the_unfinished_active_slots(saved):
    assert saved["observed"]["current"] == active(saved["first"], EATEN)
    assert saved["reruns"]["current"] == active(saved["final"], EATEN)


def test_reruns_do_not_restore_completed_or_skipped_meals(saved):
    assert saved["reruns"]["completed"] == EATEN
    assert not EATEN & set(saved["reruns"]["current"])
    assert SKIPPED not in saved["reruns"]["current"]
    assert LATER_SKIP not in saved["reruns"]["current"]


# ============================================================
# Skipped meals
# ============================================================

def test_skipped_slots_stay_excluded_and_unfilled(saved):
    plan = saved["final"]
    assert [s["slot_id"] for s in plan["skipped_slots"]] == [SKIPPED, LATER_SKIP]
    assert not {SKIPPED, LATER_SKIP} & set(by_slot(plan))
    sources = {s["slot_id"] for r in saved["result"]["grocery_basket"]["purchase_requirements"]
               for s in r["source_requirements"]}
    assert not {SKIPPED, LATER_SKIP} & sources


# ============================================================
# Leftovers
# ============================================================

def test_valid_leftover_is_allocated_once_to_an_active_slot(saved):
    meals = [m for m in saved["final"]["selected_meals"] if m.get("meal_source") == "prepared_leftover"]
    [leftover] = saved["final"]["prepared_leftovers"]

    assert len(meals) == 1
    [meal] = meals
    assert meal["leftover_id"] == leftover["leftover_id"]
    assert meal["recipe_id"] == saved["cooked"] == leftover["recipe_id"]
    assert meal["slot"]["slot_id"] == "2026-10-17_lunch"  # first unfinished slot
    assert date.fromisoformat(leftover["prepared_date"]) <= date(2026, 10, 17) \
        <= date.fromisoformat(leftover["expires_on"])
    assert leftover["servings_remaining"] == 0
    assert meal["slot"]["slot_id"] in saved["reruns"]["current"]


def test_repeated_replanning_does_not_double_consume(saved):
    first = [m for m in saved["first"]["selected_meals"] if m.get("meal_source") == "prepared_leftover"]
    final = [m for m in saved["final"]["selected_meals"] if m.get("meal_source") == "prepared_leftover"]
    assert [m["slot"]["slot_id"] for m in first] == [m["slot"]["slot_id"] for m in final]
    assert saved["first"]["prepared_leftovers"][0]["servings_remaining"] == 0
    assert saved["final"]["prepared_leftovers"][0]["servings_remaining"] == 0


def test_leftover_slot_buys_no_ingredients(saved):
    sources = {(s["slot_id"], s["recipe_id"])
               for r in saved["result"]["grocery_basket"]["purchase_requirements"]
               for s in r["source_requirements"]}
    assert "2026-10-17_lunch" not in {slot for slot, _ in sources}
    assert {slot for slot, rid in sources if rid == saved["cooked"]} == {"2026-10-15_dinner"}


def test_expired_leftover_is_not_allocated(expired):
    plan = expired["final"]

    # Expired leftovers must never be allocated.
    assert all(
        meal.get("meal_source") != "prepared_leftover"
        for meal in plan["selected_meals"]
    )

    # The expired leftover must remain unconsumed.
    assert (
        plan["prepared_leftovers"][0]["servings_remaining"]
        == 1
    )

    # Streamlit excludes expired leftovers before approval.
    # Therefore, no allocation or unused-approval event is expected.
    assert not any(
        event.get("event") in {
            "prepared_leftover_allocated",
            "prepared_leftover_not_used",
        }
        for event in plan["execution_trace"]
    )

    # Completed meals must not reappear as current meals.
    assert not EATEN & set(expired["observed"]["current"])


# ============================================================
# Consistency
# ============================================================

def test_grocery_budget_nutrition_inventory_consistent(saved):
    result = saved["result"]
    basket = result["grocery_basket"]
    assert result["plan"]["budget"]["estimated_spent"] == basket["projected_cost"]
    expected = {}
    for meal in result["plan"]["selected_meals"]:
        day = meal["slot"]["date"]
        kcal = repository().get_recipe(meal["recipe_id"])["calories_per_serving"]
        expected[day] = expected.get(day, 0.0) + kcal
    assert {d: round(v["calories"], 1) for d, v in result["nutrition_summary"].items()} == \
        {d: round(v, 1) for d, v in expected.items()}
    live = saved["flow"].at.session_state["live_plan_state"]
    assert live.initial_inventory == {"olive oil": {"quantity": 30.0, "unit": "ml"}}
    assert all(item["quantity"] >= 0 for item in live.current_inventory.values())


# ============================================================
# Persistence and reload
# ============================================================

def test_workspace_reload_restores_completed_and_skipped(saved, tmp_path, monkeypatch):
    flow = saved["flow"]
    reopened = Flow(flow.state_dir, monkeypatch, workspace=flow.workspace).open()

    assert reopened.completed == EATEN
    assert isinstance(reopened.at.session_state["completed_slot_ids"], set)
    assert [s["slot_id"] for s in reopened.plan["skipped_slots"]] == [SKIPPED, LATER_SKIP]
    assert reopened.current_meal_slots == saved["reruns"]["current"]
    assert set(reopened.history_meal_slots) == EATEN
    assert set(saved["saved"]["completed_slot_ids"]) == EATEN


# ============================================================
# The reported symptom: selection never saved
# ============================================================

def test_unsaved_completed_selection_is_not_treated_as_completed(tmp_path):
    """Only saved completed meals are history. A selection left unsaved
    in "Meals completed" reaches neither session state nor the replan,
    which reproduces the reported workspace: Current meals still starts
    on 15 Oct and the leftover fills 2026-10-15_lunch."""
    unsaved = run_flow(tmp_path, date(2026, 10, 18), save_completed=False)

    assert unsaved["reruns"]["completed"] == set()
    [rebuilt] = [e for e in unsaved["final"]["execution_trace"]
                 if e["event"] == "plan_rebuilt_after_skip"]
    assert rebuilt["completed_slot_ids"] == []
    assert unsaved["observed"]["current"][0] == "2026-10-15_lunch"
    assert by_slot(unsaved["final"])["2026-10-15_lunch"]["meal_source"] == "prepared_leftover"
