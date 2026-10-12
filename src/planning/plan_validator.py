
from src.planning.plan_state import PlanState
import math


def validate_plan(
    plan_state: PlanState,
    all_items_priced: bool = True,
    final_grocery_cost: float | None = None,
    projected_cost_complete: bool | None = None,
) -> dict:
    """
    Validate meal-plan feasibility using available grocery
    planning costs, including Tavily and Ollama estimates.

    Price estimates are accepted for planning but are not
    represented as verified retailer prices.
    """

    total_slots = len(plan_state.slots)
    selected_slots = len(plan_state.selected_meals)
    issues = []

    if selected_slots < total_slots:
        issues.append(
            f"Only {selected_slots}/{total_slots} meal slots were filled."
        )

    valid_cost = (
        final_grocery_cost is not None
        and isinstance(final_grocery_cost, (int, float))
        and not isinstance(final_grocery_cost, bool)
        and math.isfinite(final_grocery_cost)
        and final_grocery_cost >= 0
    )

    # A complete projected basket is usable for planning.
    # Preserve backward compatibility with existing callers.
    pricing_complete = (
        projected_cost_complete
        if projected_cost_complete is not None
        else all_items_priced
    )

    if valid_cost and final_grocery_cost > plan_state.initial_budget:
        issues.append("Final grocery cost exceeds budget.")
        return {"status": "infeasible", "issues": issues}

    if selected_slots == 0:
        return {"status": "infeasible", "issues": issues}

    if selected_slots < total_slots:
        if not pricing_complete or not valid_cost:
            issues.append("Some grocery costs are unavailable.")

        return {"status": "partial", "issues": issues}

    if not pricing_complete or not valid_cost:
        issues.append("Complete grocery planning cost is unavailable.")
        return {"status": "uncertain", "issues": issues}

    return {"status": "feasible", "issues": []}
