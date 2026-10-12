"""
Day 5 End-to-End Integration Test

Runs the real multi-meal planning pipeline:

User State
    -> MultiMealPlanner
    -> Recipe Agent
    -> Manager
    -> Ingredient Agent
    -> Grocery Agent
    -> Reasoning Engine
    -> Inventory/Nutrition updates
    -> Final Grocery Basket
    -> Plan Validator

Run from project root:

    python3 scripts/run_day5_e2e.py
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from src.grocery.ollama_fallback_service import (
    OllamaFallbackGroceryService,
)

# ============================================================
# PROJECT IMPORTS
# ============================================================

from src.agents.manager import ManagerAgent
from src.agents.recipe_agent import RecipeAgent
from src.agents.ingredient_agent import IngredientAgent
from src.agents.grocery_agent import GroceryAgent

from src.planning.multi_meal_planner import MultiMealPlanner

# ============================================================
# CONFIGURATION
# ============================================================

DAYS = 3

MEAL_TYPES = [
    "lunch",
    "dinner",
]

MAX_CANDIDATES_PER_SLOT = 10


# ============================================================
# TEST USER
# ============================================================

USER_STATE = {
    "user_id": "DAY5_E2E_USER",
    # -----------------------------------------
    # Budget
    # -----------------------------------------
    "budget": 60.0,
    "remaining_budget": 60.0,
    # -----------------------------------------
    # Dietary requirements
    # -----------------------------------------
    "dietary_restrictions": [
        "vegetarian",
    ],
    "allergies": [
        "peanut",
    ],
    # -----------------------------------------
    # Preferences
    # -----------------------------------------
    "preferred_cuisines": [
        "asian",
    ],
    "preferred_meal_types": [
        "lunch",
        "dinner",
    ],
    "disliked_ingredients": [],
    # -----------------------------------------
    # Cooking
    # -----------------------------------------
    # Your existing user model stores cooking
    # preference in hours.
    "cook_time_preference_hrs": 0.5,
    # -----------------------------------------
    # Pantry
    # -----------------------------------------
    "pantry": [
        {
            "ingredient_name": "rice",
            "quantity": 500,
            "unit": "g",
        },
        {
            "ingredient_name": "oil",
            "quantity": 250,
            "unit": "ml",
        },
    ],
    # -----------------------------------------
    # Nutrition
    # -----------------------------------------
    "nutrition_targets": {
        "calories": 1800,
        "protein_g": 70,
    },
}


# ============================================================
# SCHEDULE
# ============================================================

START_DATE = date(
    2026,
    10,
    7,
)

SCHEDULE = {
    "2026-10-07": {
        "lunch": {
            "max_cooking_time": 30,
        },
        "dinner": {
            "max_cooking_time": 30,
        },
    },
    "2026-10-08": {
        "lunch": {
            "max_cooking_time": 30,
        },
        "dinner": {
            "max_cooking_time": 20,
        },
    },
    "2026-10-09": {
        "lunch": {
            "max_cooking_time": 30,
        },
        "dinner": {
            "max_cooking_time": 30,
        },
    },
}


# ============================================================
# BUILD REAL SYSTEM
# ============================================================


def build_system():
    """
    Build the REAL Day-5 system using the project's
    existing agents and Manager.

    Reasoning functions are already injected into
    ManagerAgent through its default constructor arguments.
    """

    print("\n[SETUP] Initializing real components...")

    # ========================================================
    # 1. RECIPE AGENT
    # ========================================================

    recipe_agent = RecipeAgent(max_candidates=MAX_CANDIDATES_PER_SLOT)

    # ========================================================
    # 2. INGREDIENT AGENT
    # ========================================================

    ingredient_agent = IngredientAgent()

    # ========================================================
    # 3. GROCERY AGENT
    # ========================================================

    grocery_agent = GroceryAgent(grocery_service=OllamaFallbackGroceryService())
    # ========================================================
    # 4. RECIPE LOOKUP
    # ========================================================

    # Reuse the repository already owned by RecipeAgent.
    repository = recipe_agent.repository

    def recipe_lookup(
        recipe_id: str,
    ) -> dict | None:

        return repository.get_recipe(recipe_id)

    # ========================================================
    # 5. MANAGER
    # ========================================================

    manager = ManagerAgent(
        recipe_agent=recipe_agent,
        ingredient_agent=ingredient_agent,
        grocery_agent=grocery_agent,
        recipe_lookup=recipe_lookup,
        allow_provisional_budget=True,
    )

    # ========================================================
    # 6. MULTI-MEAL PLANNER
    # ========================================================

    planner = MultiMealPlanner(
        manager=manager,
        max_candidates_per_slot=(MAX_CANDIDATES_PER_SLOT),
    )

    print("[SETUP] Components initialized.")

    return planner


# ============================================================
# DISPLAY HELPERS
# ============================================================


def print_heading(title: str) -> None:

    print("\n")
    print("=" * 70)
    print(title)
    print("=" * 70)


def print_selected_meals(
    plan: dict,
) -> None:

    print_heading("SELECTED MEALS")

    selected = plan.get(
        "selected_meals",
        [],
    )

    print(f"Meals selected: " f"{len(selected)}")

    for index, meal in enumerate(
        selected,
        start=1,
    ):

        slot = meal.get(
            "slot",
            {},
        )

        print(f"\n{index}. " f"{slot.get('date')} " f"{slot.get('meal_type')}")

        print(
            "   Recipe:",
            meal.get("recipe_id"),
        )

        print(
            "   Estimated cost:",
            meal.get("estimated_cost"),
        )


def print_rejections(
    plan: dict,
) -> None:

    print_heading("REJECTIONS / RETRIES")

    rejected = plan.get(
        "rejected_candidates",
        [],
    )

    uncertain = plan.get(
        "uncertain_candidates",
        [],
    )

    print(
        "Rejected candidates:",
        len(rejected),
    )

    for item in rejected:

        print(
            "-",
            item.get("recipe_id"),
            "| slot:",
            item.get("slot_id"),
            "| reason:",
            item.get("reason"),
        )

    print(
        "\nUncertain candidates:",
        len(uncertain),
    )

    for item in uncertain:

        print(
            "-",
            item.get("recipe_id"),
            "| slot:",
            item.get("slot_id"),
            "| reason:",
            item.get("reason"),
        )



def print_budget(plan: dict, result: dict) -> None:
    print_heading("BUDGET")

    budget = plan.get("budget", {})
    basket = result.get("grocery_basket", {})

    initial = budget.get("initial", 0.0)
    projected = basket.get("projected_cost")
    complete = basket.get("projected_cost_complete") is True

    all_usable = basket.get(
        "all_items_have_usable_cost",
        False,
    )

    print(f"Initial budget: S${initial:.2f}")

    if complete and projected is not None:
        print(f"Total Grocery Cost: S${projected:.2f}")
        print(
            f"Remaining Budget: "
            f"S${initial - projected:.2f}"
        )
    else:
        print("Total Grocery Cost: Incomplete")
        print("Remaining Budget: Unknown")

    print(
        "All Ingredients Have Prices:",
        "Yes" if all_usable else "No",
    )

    print(
        "Grocery Pricing:",
        "Complete"
        if complete and all_usable
        else "Incomplete",
    )

    print(
        "Unpriced Items:",
        basket.get("unpriced_items", []),
    )


def print_inventory(
    plan: dict,
) -> None:

    print_heading("INVENTORY")

    inventory = plan.get(
        "inventory",
        {},
    )

    print("\nInitial inventory:")

    print(
        json.dumps(
            inventory.get(
                "initial",
                {},
            ),
            indent=2,
            default=str,
        )
    )

    print("\nFinal inventory:")

    print(
        json.dumps(
            inventory.get(
                "current",
                {},
            ),
            indent=2,
            default=str,
        )
    )


def print_nutrition(
    result: dict,
) -> None:

    print_heading("NUTRITION")

    print("Summary:")

    print(
        json.dumps(
            result.get(
                "nutrition_summary",
                {},
            ),
            indent=2,
            default=str,
        )
    )

    print("\nDeviation:")

    print(
        json.dumps(
            result.get(
                "nutrition_deviation",
                {},
            ),
            indent=2,
            default=str,
        )
    )


def print_grocery_basket(
    result: dict,
) -> None:

    print_heading("FINAL GROCERY BASKET")

    basket = result.get(
        "grocery_basket",
        {},
    )

    items = basket.get(
        "items",
        [],
    )

    print(
        "Number of grocery items:",
        len(items),
    )

    for item in items:

        print(
            "\n-",
            (item.get("ingredient_name") or item.get("ingredient") or item.get("name")),
        )

        print(
            "  Required:",
            item.get("required_quantity"),
            item.get("required_unit"),
        )

        print(
            "  Package:",
            item.get("package_quantity"),
            item.get("package_unit"),
        )

        print(
            "  Packages:",
            (item.get("packages_needed") or item.get("packages")),
        )

        cost = item.get("effective_purchase_cost")

        if cost is None:
            cost = item.get("purchase_cost")

        if cost is None:
            cost = item.get("estimated_purchase_cost")

        print(f"  Cost: S${cost:.2f}" if cost is not None else "  Cost: Unavailable")


def print_execution_trace(
    plan: dict,
) -> None:

    print_heading("EXECUTION TRACE")

    trace = plan.get(
        "execution_trace",
        [],
    )

    for index, event in enumerate(
        trace,
        start=1,
    ):

        print(
            f"{index}.",
            json.dumps(
                event,
                default=str,
            ),
        )


# ============================================================
# ACCEPTANCE CHECKS
# ============================================================


def run_acceptance_checks(
    result: dict,
) -> None:

    print_heading("DAY 5 ACCEPTANCE CHECKS")

    plan = result.get(
        "plan",
        {},
    )

    validation = result.get(
        "validation",
        {},
    )

    basket = result.get(
        "grocery_basket",
        {},
    )

    slots = plan.get(
        "slots",
        [],
    )

    selected = plan.get(
        "selected_meals",
        [],
    )

    used_ids = plan.get(
        "used_recipe_ids",
        [],
    )

    checks = []

    # --------------------------------------------------------
    # 1. Six slots generated
    # --------------------------------------------------------

    checks.append(
        (
            "6 meal slots generated",
            len(slots) == 6,
        )
    )

    # --------------------------------------------------------
    # 2. No duplicate selected recipes
    # --------------------------------------------------------

    # Recipe repetition is allowed.
    # A meal slot must still be assigned at most once.

    selected_slot_ids = [meal["slot"]["slot_id"] for meal in selected]

    checks.append(
        (
            "No duplicate meal-slot assignments",
            len(selected_slot_ids) == len(set(selected_slot_ids)),
        )
    )

    # --------------------------------------------------------
    # 3. Inventory exists
    # --------------------------------------------------------

    checks.append(
        (
            "Inventory state available",
            "inventory" in plan,
        )
    )

    # --------------------------------------------------------
    # 4. Nutrition exists
    # --------------------------------------------------------

    checks.append(
        (
            "Nutrition summary available",
            result.get("nutrition_summary") is not None,
        )
    )

    # --------------------------------------------------------
    # 5. Final grocery basket exists
    # --------------------------------------------------------

    checks.append(
        (
            "Final grocery basket available",
            isinstance(
                basket,
                dict,
            ),
        )
    )

    # --------------------------------------------------------
    # 6. Pricing completeness explicitly known
    # --------------------------------------------------------

    checks.append(
        (
            "Pricing completeness available",
            "all_items_priced" in basket,
        )
    )

    checks.append(
        (
            "At least one meal selected",
            len(selected) > 0,
        )
    )

    checks.append(
        (
            "All requested meal slots filled",
            len(selected) == len(slots),
        )
    )

    # --------------------------------------------------------
    # 7. Final validation status
    # --------------------------------------------------------

    allowed_statuses = {
        "feasible",
        "uncertain",
        "partial",
        "infeasible",
    }

    checks.append(
        (
            "Valid final plan status",
            validation.get("status") in allowed_statuses,
        )
    )

    # --------------------------------------------------------
    # Print results
    # --------------------------------------------------------

    all_passed = True

    for label, passed in checks:

        marker = "PASS" if passed else "FAIL"

        print(f"[{marker}] {label}")

        if not passed:
            all_passed = False

    print()

    if all_passed:

        print("DAY 5 STRUCTURAL " "E2E CHECKS PASSED.")

    else:

        print("DAY 5 E2E HAS " "FAILED CHECKS.")


# ============================================================
# MAIN
# ============================================================


def main():

    print_heading("DAY 5 REAL END-TO-END RUN")

    planner = build_system()

    print("\nPlanning:" f" {DAYS} days x " f"{len(MEAL_TYPES)} meals")

    print(
        "Expected slots:",
        DAYS * len(MEAL_TYPES),
    )

    # --------------------------------------------------------
    # Execute real planner
    # --------------------------------------------------------

    result = planner.plan_meals(
        user_state=USER_STATE,
        start_date=START_DATE,
        days=DAYS,
        meal_types=MEAL_TYPES,
        schedule=SCHEDULE,
        nutrition_targets=(USER_STATE.get("nutrition_targets")),
    )

    # --------------------------------------------------------
    # Display results
    # --------------------------------------------------------

    plan = result.get(
        "plan",
        {},
    )

    print_heading("FINAL PLAN STATUS")

    print(
        json.dumps(
            result.get(
                "validation",
                {},
            ),
            indent=2,
            default=str,
        )
    )

    print_selected_meals(plan)

    print_rejections(plan)

    print_budget(
        plan,
        result,
    )

    print_inventory(plan)

    print_nutrition(result)

    print_grocery_basket(result)

    print_execution_trace(plan)

    run_acceptance_checks(result)

    # --------------------------------------------------------
    # Save complete output for inspection/reporting
    # --------------------------------------------------------

    output_path = Path("reports/day5_e2e_output.json")

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path.write_text(
        json.dumps(
            result,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    print(
        "\nFull output saved to:",
        output_path,
    )


if __name__ == "__main__":
    main()
