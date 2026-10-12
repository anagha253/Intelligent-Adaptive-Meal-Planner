# src/planning/multi_meal_planner.py

from datetime import date

from typing import Any

from src.planning.meal_slot import (

    MealSlot,

    generate_meal_slots,

)

from src.planning.plan_state import (

    PlanState,

)

from src.planning.plan_validator import (

    validate_plan,

)

from src.agents.grocery_agent import calculate_incremental_basket_cost

from src.state.inventory_state import (

    normalize_inventory,

    add_purchase,

    consume_inventory,

)

from src.state.nutrition_tracker import (

    aggregate_nutrition,

    calculate_nutrition_deviation,

    summarize_nutrition,

)

from src.agents.grocery_agent import (

    build_plan_grocery_basket,

)





class MultiMealPlanner:

    """

    Orchestrates planning across multiple meal slots.

    Responsibilities:

    - Generate meal slots

    - Ask Recipe Agent for candidates

    - Evaluate candidates through existing Manager workflow

    - Retry rejected/uncertain candidates

    - Select feasible candidates

    - Update PlanState

    - Validate final plan

    This class DOES NOT implement:

    - Recipe retrieval

    - Ingredient processing

    - Pantry subtraction

    - Grocery search

    - Budget reasoning

    - Allergy/diet reasoning

    """



    def __init__(

        self,

        manager,

        max_candidates_per_slot: int = 5,

    ):

        self.manager = manager

        self.max_candidates_per_slot = max_candidates_per_slot

        self.last_plan_state: PlanState | None = None

    # ============================================================

    # PUBLIC ENTRY POINT

    # ============================================================



    def plan_meals(

        self,

        user_state: dict,

        start_date: date,

        days: int,

        meal_types: list[str],

        schedule: dict | None = None,

        nutrition_targets: dict | None = None,

    ) -> dict:

        # ========================================================

        # 1. GENERATE MEAL SLOTS

        # ========================================================

        print(">>>>>>>>>Getting the meals now!! in plan meals<<<<<<<<<<<,")

        slots = generate_meal_slots(

            start_date=start_date,

            days=days,

            meal_types=meal_types,

            schedule=schedule,

        )

        print(f"Slots>>>>>>>>>>>>>>>{slots}<<<<<<<<<<<<")

        # ========================================================

        # 2. INITIAL BUDGET

        # ========================================================

        initial_budget = self._get_budget(user_state)

        print(f"Getting budget>>>>>>>>>>{initial_budget}<<<<<<<<<\n")

        # ========================================================

        # 3. INITIAL INVENTORY

        # Member 3

        # ========================================================

        raw_pantry = (

            user_state.get("pantry") or user_state.get("ingredient_availability") or {}

        )

        initial_inventory = normalize_inventory(raw_pantry)

        print(f"Getting initial inven: >>>>>>>>>>>{initial_inventory}<<<<<<")

        # ========================================================

        # 4. CREATE PLAN STATE

        # ========================================================

        plan_state = PlanState(

            slots=slots,

            initial_budget=initial_budget,

            initial_inventory=initial_inventory,

            current_inventory=dict(initial_inventory),

        )

        print(f"plan state: >>>>>>>>>>>{plan_state}<<<<<<<<<<<\n")

        # ========================================================

        # 5. OPTIMIZE COMPLETE MEAL PLAN

        # ========================================================

        optimized_state = self._optimize_meal_plan(

            user_state=user_state,

            initial_state=plan_state,

            beam_width=5,

        )

        plan_state = optimized_state

        # Mark slots that were not filled.

        selected_slot_ids = {

            meal["slot"]["slot_id"] for meal in plan_state.selected_meals

        }

        for slot in slots:

            if slot.slot_id not in selected_slot_ids:

                plan_state.mark_slot_infeasible(slot)

        # ========================================================

        # 5B. UPDATE NUTRITION AFTER SELECTION

        # ========================================================

        for selected in plan_state.selected_meals:

            slot_data = selected["slot"]

            matching_slot = next(

                slot for slot in slots if slot.slot_id == slot_data["slot_id"]

            )

            self._update_nutrition(

                plan_state=plan_state,

                slot=matching_slot,

                decision=selected["decision"],

            )

        # ========================================================

        # 6. MEMBER 4

        # BUILD FINAL AGGREGATED GROCERY BASKET

        # ========================================================

        final_grocery_basket = self._build_final_grocery_basket(plan_state)

        print(f"final grocery basket>>>>>{final_grocery_basket}<<<<<<<\n")

        plan_state.final_grocery_basket = final_grocery_basket

        # Reconcile inventory after final basket selection.

        reconciliation_trace_start = len(plan_state.execution_trace)

        inventory_ok = self._reconcile_final_inventory(

            plan_state=plan_state,

            final_grocery_basket=final_grocery_basket,

        )

        inventory_reconciliation_incomplete = any(

            event.get("event") == "inventory_reconciliation_incomplete"

            for event in plan_state.execution_trace[reconciliation_trace_start:]

        )

        # ========================================================

        # 7. NUTRITION SUMMARY

        # ========================================================

        nutrition_summary = summarize_nutrition(plan_state.nutrition_state)

        print(f"nutrition summ. >>>>>{nutrition_summary}<<<<<<<\n")

        nutrition_deviation = None

        if nutrition_targets:

            nutrition_deviation = calculate_nutrition_deviation(

                plan_state.nutrition_state,

                nutrition_targets,

            )

            print(

                f"nutritional devi.>>>>>{nutrition_deviation} and targets : {nutrition_targets}<<<<<<<\n"

            )

        # ========================================================

        # 8. FINAL PLAN VALIDATION

        # ========================================================

        if final_grocery_basket.get("all_items_priced") is True:

            final_cost = final_grocery_basket.get("known_cost")

        elif final_grocery_basket.get("projected_cost_complete") is True:

            final_cost = final_grocery_basket.get("projected_cost")

        else:

            final_cost = None

        all_items_priced = final_grocery_basket.get(

            "all_items_priced",

            False,

        )

        validation = validate_plan(

            plan_state=plan_state,

            all_items_priced=all_items_priced,

            final_grocery_cost=final_cost,

        )

        if not inventory_ok:

            validation["issues"].append("Final inventory reconciliation failed.")

            validation["status"] = "infeasible"

        elif inventory_reconciliation_incomplete:

            validation["issues"].append(

                "Qualitative ingredient quantities remain unresolved."

            )

            if validation["status"] == "feasible":

                validation["status"] = "uncertain"

        print(f"validation of plan >>>>>{validation}<<<<<<<\n")

        plan_state.status = validation["status"]

        self.last_plan_state = plan_state

        # ========================================================

        # 9. RETURN COMPLETE PLAN

        # ========================================================

        return {

            "plan": plan_state.to_dict(),

            "validation": validation,

            "grocery_basket": final_grocery_basket,

            "nutrition_summary": nutrition_summary,

            "nutrition_deviation": nutrition_deviation,

        }

    # ============================================================

    # ADAPTIVE REPLANNING

    # ============================================================



    def skip_and_replan(

        self,

        user_state: dict,

        plan_state: PlanState,

        slot_id: str,

        completed_slot_ids: set[str] | None = None,

        nutrition_targets: dict | None = None,

    ) -> dict:

        """Skip one slot and replan unfinished slots without changing the input state."""

        from copy import deepcopy

        if not isinstance(user_state, dict):

            raise TypeError("user_state must be a dictionary")

        if not isinstance(plan_state, PlanState):

            raise TypeError("plan_state must be a PlanState instance")

        completed_ids = set(completed_slot_ids or set())

        original_slots = list(plan_state.slots)

        slots_by_id = {slot.slot_id: slot for slot in original_slots}

        if slot_id not in slots_by_id:

            raise ValueError(f"Unknown meal slot: {slot_id}")

        unknown_ids = completed_ids - set(slots_by_id)

        if unknown_ids:

            raise ValueError(f"Unknown completed slot IDs: {sorted(unknown_ids)}")

        if slot_id in completed_ids:

            raise ValueError("Cannot skip a meal marked as completed")

        if any(item.get("slot_id") == slot_id for item in plan_state.skipped_slots):

            raise ValueError(f"Meal slot is already skipped: {slot_id}")

        selected_by_slot = {

            meal.get("slot", {}).get("slot_id"): meal

            for meal in plan_state.selected_meals

            if meal.get("slot", {}).get("slot_id")

        }

        missing = completed_ids - set(selected_by_slot)

        if missing:

            raise ValueError(

                f"Completed slots must have selected meals: {sorted(missing)}"

            )

        rebuilt = deepcopy(plan_state)

        rebuilt.mark_slot_skipped(slots_by_id[slot_id])

        skipped_ids = {item["slot_id"] for item in rebuilt.skipped_slots}

        completed_meals = [

            deepcopy(selected_by_slot[slot.slot_id])

            for slot in original_slots

            if slot.slot_id in completed_ids

        ]

        remaining_slots = [

            slot for slot in original_slots

            if slot.slot_id not in completed_ids

            and slot.slot_id not in skipped_ids

        ]

        rebuilt.selected_meals = completed_meals

        rebuilt.used_recipe_ids = {

            meal["recipe_id"] for meal in completed_meals

        }

        rebuilt.rejected_candidates = []

        rebuilt.uncertain_candidates = []

        rebuilt.nutrition_state = {}

        rebuilt.current_inventory = deepcopy(rebuilt.initial_inventory)

        rebuilt.final_grocery_basket = {}

        rebuilt.status = "building"

        # Estimate the combined grocery cost for meals already completed.

        completed_basket = self._build_final_grocery_basket(rebuilt)

        completed_cost = completed_basket.get("projected_cost")

        if completed_cost is None:

            completed_cost = completed_basket.get("known_cost")

        if completed_cost is None:

            completed_cost = sum(

                max(float(meal.get("estimated_cost") or 0.0), 0.0)

                for meal in completed_meals

            )

        rebuilt.estimated_spent = max(float(completed_cost or 0.0), 0.0)

        # Reuse the existing optimizer only for unfinished slots.

        rebuilt.slots = remaining_slots

        optimized = self._optimize_meal_plan(

            user_state=user_state,

            initial_state=rebuilt,

            beam_width=5,

        )

        # Restore the original schedule order and full slot list.

        optimized.slots = original_slots

        selected_by_slot = {

            meal.get("slot", {}).get("slot_id"): meal

            for meal in optimized.selected_meals

            if meal.get("slot", {}).get("slot_id")

        }

        optimized.selected_meals = [

            selected_by_slot[slot.slot_id]

            for slot in original_slots

            if slot.slot_id in selected_by_slot

        ]

        optimized.used_recipe_ids = {

            meal["recipe_id"] for meal in optimized.selected_meals

        }

        selected_ids = set(selected_by_slot)

        for slot in original_slots:

            if slot.slot_id not in selected_ids and slot.slot_id not in skipped_ids:

                optimized.mark_slot_infeasible(slot)

        # Recalculate nutrition for the retained and newly selected meals.

        optimized.nutrition_state = {}

        for meal in optimized.selected_meals:

            meal_slot_id = meal.get("slot", {}).get("slot_id")

            if meal_slot_id in slots_by_id:

                self._update_nutrition(

                    plan_state=optimized,

                    slot=slots_by_id[meal_slot_id],

                    decision=meal.get("decision") or {},

                )

        basket = self._build_final_grocery_basket(optimized)

        optimized.final_grocery_basket = basket

        reconciliation_trace_start = len(optimized.execution_trace)

        inventory_ok = self._reconcile_final_inventory(optimized, basket)

        inventory_reconciliation_incomplete = any(

            event.get("event") == "inventory_reconciliation_incomplete"

            for event in optimized.execution_trace[reconciliation_trace_start:]

        )

        nutrition_summary = summarize_nutrition(optimized.nutrition_state)

        nutrition_deviation = None

        if nutrition_targets:

            nutrition_deviation = calculate_nutrition_deviation(

                optimized.nutrition_state, nutrition_targets

            )

        if basket.get("all_items_priced") is True:

            final_cost = basket.get("known_cost")

        elif basket.get("projected_cost_complete") is True:

            final_cost = basket.get("projected_cost")

        else:

            final_cost = None

        validation = validate_plan(

            plan_state=optimized,

            all_items_priced=basket.get("all_items_priced", False),

            final_grocery_cost=final_cost,

        )

        if not inventory_ok:

            validation["issues"].append("Final inventory reconciliation failed.")

            validation["status"] = "infeasible"

        elif inventory_reconciliation_incomplete:

            validation["issues"].append(

                "Qualitative ingredient quantities remain unresolved."

            )

            if validation["status"] == "feasible":

                validation["status"] = "uncertain"

        optimized.status = validation["status"]

        optimized.execution_trace.append({

            "event": "plan_rebuilt_after_skip",

            "skipped_slot_id": slot_id,

            "completed_slot_ids": sorted(completed_ids),

        })

        self.last_plan_state = optimized

        return {

            "plan": optimized.to_dict(),

            "validation": validation,

            "grocery_basket": basket,

            "nutrition_summary": nutrition_summary,

            "nutrition_deviation": nutrition_deviation,

        }

    # PLAN ONE MEAL SLOT

    # ============================================================



    def _evaluate_candidates_for_slot(

        self,

        user_state: dict,

        slot: MealSlot,

        plan_state: PlanState,

    ) -> list[dict]:

        """

        Evaluate recipe candidates for one meal slot.

        Checks non-budget hard constraints and combined

        grocery basket affordability.

        Returns feasible candidates sorted by total cost.

        Does not select meals or update budget.

        """

        candidate_ids = self._get_candidates(

            user_state=user_state,

            slot=slot,

            plan_state=plan_state,

        )

        feasible_candidates = []

        max_repeats = int(

            user_state.get(

                "max_recipe_repetitions",

                2,

            )

        )

        for recipe_id in candidate_ids:

            recipe_count = sum(

                meal["recipe_id"] == recipe_id for meal in plan_state.selected_meals

            )

            if recipe_count >= max_repeats:

                continue

            decision = self._evaluate_candidate(

                user_state=user_state,

                slot=slot,

                recipe_id=recipe_id,

                plan_state=plan_state,

            )

            reasoning = decision.get("reasoning") or {}

            constraints = reasoning.get("hard_constraints") or []

            non_budget = [

                item for item in constraints if item.get("constraint") != "budget"

            ]

            if not non_budget or any(

                item.get("status") != "pass" for item in non_budget

            ):

                plan_state.add_rejection(

                    slot=slot,

                    recipe_id=recipe_id,

                    reason=non_budget or "Hard constraints not verified",

                )

                continue

            grocery = decision.get("grocery") or {}

            if not grocery.get("projected_cost_complete"):

                plan_state.add_uncertain(

                    slot=slot,

                    recipe_id=recipe_id,

                    reason="Incomplete grocery projection",

                )

                continue

            from copy import deepcopy

            trial_state = deepcopy(plan_state)

            trial_state.selected_meals.append(

                {

                    "slot": slot.to_dict(),

                    "recipe_id": recipe_id,

                    "decision": decision,

                    "estimated_cost": 0.0,

                }

            )

            try:

                trial_basket = self._build_final_grocery_basket(trial_state)

            except ValueError as exc:

                plan_state.add_uncertain(

                    slot=slot,

                    recipe_id=recipe_id,

                    reason={

                        "type": "grocery_aggregation_error",

                        "message": str(exc),

                    },

                )

                continue

            projected_total = trial_basket.get("projected_cost")

            projected_complete = trial_basket.get(

                "projected_cost_complete",

                False,

            )

            if not projected_complete or projected_total is None:

                plan_state.add_uncertain(

                    slot=slot,

                    recipe_id=recipe_id,

                    reason="Combined basket cost incomplete",

                )

                continue

            projected_total = float(projected_total)

            if projected_total > plan_state.initial_budget:

                plan_state.add_rejection(

                    slot=slot,

                    recipe_id=recipe_id,

                    reason={

                        "constraint": "budget",

                        "status": "fail",

                        "projected_plan_cost": projected_total,

                        "budget": plan_state.initial_budget,

                    },

                )

                continue

            # Rebuild the current partial plan's basket.

            # Use the same original pantry for both baskets.

            current_basket = self._build_final_grocery_basket(plan_state)

            if plan_state.selected_meals:

                if (

                    current_basket.get("projected_cost_complete") is not True

                    or current_basket.get("projected_cost") is None

                ):

                    plan_state.add_uncertain(

                        slot=slot,

                        recipe_id=recipe_id,

                        reason="Existing combined basket cost incomplete",

                    )

                    continue

                previous_total = float(current_basket["projected_cost"])

            else:

                previous_total = 0.0

            incremental_cost = round(

                projected_total - previous_total,

                2,

            )

            if incremental_cost < -0.01:

                plan_state.add_uncertain(

                    slot=slot,

                    recipe_id=recipe_id,

                    reason=(

                        "Combined basket cost decreased after "

                        "adding a recipe. Check product consistency."

                    ),

                )

                continue

            incremental_cost = max(0.0, incremental_cost)

            feasible_candidates.append(

                {

                    "recipe_id": recipe_id,

                    "decision": decision,

                    "incremental_cost": incremental_cost,

                    "total_cost": projected_total,

                }

            )

        feasible_candidates.sort(

            key=lambda item: (

                item["total_cost"],

                item["recipe_id"],

            )

        )

        return feasible_candidates

    # Optimise meal plan



    def _optimize_meal_plan(

        self,

        user_state: dict,

        initial_state: PlanState,

        beam_width: int = 5,

    ) -> PlanState:

        """

        Find an affordable meal plan while preferring recipe diversity.



        Ranking:

        1. More meal slots filled.

        2. More unique recipes.

        3. Lower combined projected grocery cost.



        If the default repetition limit leaves slots empty, retry with

        a relaxed limit. Explicit user limits are never overridden.

        """

        from copy import deepcopy



        total_possible_meals = len(initial_state.slots)

        configured_limit = user_state.get("max_recipe_repetitions")

        strict_limit = (

            max(1, int(configured_limit))

            if configured_limit is not None

            else 2

        )



        def ranking_key(state):

            return (

                -len(state.selected_meals),

                -len(state.used_recipe_ids),

                round(state.estimated_spent, 2),

            )



        def search(search_user_state):

            beams = [deepcopy(initial_state)]



            for slot in initial_state.slots:

                next_beams = []



                for state in beams:

                    candidates = self._evaluate_candidates_for_slot(

                        user_state=search_user_state,

                        slot=slot,

                        plan_state=state,

                    )



                    # Keep a skip-slot branch for partial plans.

                    next_beams.append(deepcopy(state))



                    for candidate in candidates:

                        trial = deepcopy(state)

                        trial.add_selected_meal(

                            slot=slot,

                            recipe_id=candidate["recipe_id"],

                            decision=candidate["decision"],

                            estimated_cost=candidate["incremental_cost"],

                        )

                        # The consolidated basket total is authoritative.

                        trial.estimated_spent = candidate["total_cost"]

                        next_beams.append(trial)



                next_beams.sort(key=ranking_key)

                beams = next_beams[:beam_width]



            return min(beams, key=ranking_key)



        strict_user_state = dict(user_state)

        strict_user_state["max_recipe_repetitions"] = strict_limit

        best_state = search(strict_user_state)



        # Relax only the default limit, and only when doing so fills

        # more meal slots. Never override an explicit user limit.

        if (

            configured_limit is None

            and len(best_state.selected_meals) < total_possible_meals

        ):

            relaxed_user_state = dict(user_state)

            relaxed_user_state["max_recipe_repetitions"] = max(

                strict_limit, total_possible_meals

            )

            relaxed_state = search(relaxed_user_state)



            if len(relaxed_state.selected_meals) > len(

                best_state.selected_meals

            ):

                best_state = relaxed_state



        return best_state



    # ============================================================

    # GET RECIPE CANDIDATES

    # ============================================================



    def _get_candidates(

        self,

        user_state: dict,

        slot: MealSlot,

        plan_state: PlanState,

    ) -> list[str]:

        """

        Retrieve new recipes and include previously selected

        recipes as potential reuse candidates.

        Recipe repetition is limited during candidate evaluation.

        """

        meal_slot = {

            "date": slot.date.isoformat(),

            "meal_type": slot.meal_type,

            "max_cooking_time": slot.max_cooking_time,

        }

        max_repeats = int(

            user_state.get(

                "max_recipe_repetitions",

                2,

            )

        )

        usage_counts = {}

        for meal in plan_state.selected_meals:

            recipe_id = meal["recipe_id"]

            usage_counts[recipe_id] = usage_counts.get(recipe_id, 0) + 1

        # Reuse candidates are already known to the planner.

        reuse_ids = [

            recipe_id

            for recipe_id in usage_counts

            if usage_counts[recipe_id] < max_repeats

        ]

        # Ask Recipe Agent for new recipes.

        # Existing recipe IDs remain excluded from retrieval,

        # but are reintroduced locally as reuse candidates.

        response = self.manager.recipe_agent.run(

            user_state=user_state,

            meal_slot=meal_slot,

            selected_recipe_ids=list(plan_state.used_recipe_ids),

            recent_cuisines=[],

            max_candidates=self.max_candidates_per_slot,

        )

        if isinstance(response, dict):

            candidates = response.get("candidate_recipe_ids")

            if candidates is None:

                data = response.get("data") or {}

                candidates = data.get("candidate_recipe_ids", [])

        elif isinstance(response, list):

            candidates = response

        else:

            candidates = []

        result = []

        # Prioritize reuse candidates to encourage

        # ingredient sharing and batch-friendly plans.

        for recipe_id in reuse_ids:

            if recipe_id not in result:

                result.append(recipe_id)

        for candidate in candidates or []:

            if isinstance(candidate, str):

                recipe_id = candidate.strip().upper()

            elif isinstance(candidate, dict):

                recipe_id = candidate.get("recipe_id") or candidate.get("id")

                if recipe_id:

                    recipe_id = str(recipe_id).strip().upper()

            else:

                continue

            if not recipe_id:

                continue

            if recipe_id not in result:

                result.append(recipe_id)

        return result

    # ============================================================

    # EVALUATE ONE CANDIDATE

    # ============================================================



    def _evaluate_candidate(

        self,

        user_state: dict,

        slot: MealSlot,

        recipe_id: str,

        plan_state: PlanState,

    ) -> dict:

        planning_user_state = dict(user_state)

        # Use CURRENT remaining budget.

        planning_user_state["remaining_budget"] = plan_state.remaining_budget

        # Use CURRENT inventory.

        planning_user_state["pantry"] = self._inventory_to_pantry(

            plan_state.current_inventory

        )

        meal_context = {

            "date": slot.date.isoformat(),

            "meal_type": slot.meal_type,

            "max_cooking_time": slot.max_cooking_time,

        }

        return self.manager.evaluate_candidate(

            recipe_id=recipe_id,

            user_state=planning_user_state,

            meal_context=meal_context,

            defer_budget_to_planner=True,

        )

    # ============================================================

    # BUDGET HELPER

    # ============================================================

    @staticmethod



    def _get_budget(

        user_state: dict,

    ) -> float:

        """

        Support either:

            budget_remaining: 50

        or:

            budget: {

                total: 50,

                remaining: 40

            }

        or:

            budget: 50

        """

        if "budget_remaining" in user_state:

            return float(user_state["budget_remaining"])

        budget = user_state.get(

            "budget",

            0.0,

        )

        if isinstance(budget, dict):

            return float(

                budget.get(

                    "remaining",

                    budget.get(

                        "total",

                        0.0,

                    ),

                )

            )

        return float(budget or 0.0)

    # ============================================================

    # REJECTION REASON HELPER

    # ============================================================

    @staticmethod



    def _extract_reason(

        decision: dict,

    ) -> Any:

        """

        Preserve useful explanation from

        the Reasoning Engine.

        """

        return (

            decision.get("reason")

            or decision.get("failed_constraints")

            or decision.get("unknown_constraints")

            or decision.get("errors")

            or "unspecified"

        )



    def _update_nutrition(

        self,

        plan_state: PlanState,

        slot: MealSlot,

        decision: dict,

    ) -> None:

        recipe = decision.get(

            "recipe",

            {},

        )

        if not recipe:

            return

        plan_state.nutrition_state = aggregate_nutrition(

            nutrition_state=plan_state.nutrition_state,

            date=slot.date.isoformat(),

            nutrition=recipe,

            servings=1.0,

        )

        plan_state.execution_trace.append(

            {

                "event": "nutrition_updated",

                "slot_id": slot.slot_id,

                "recipe_id": decision.get("recipe_id"),

            }

        )



    def _reconcile_final_inventory(

        self,

        plan_state: PlanState,

        final_grocery_basket: dict,

    ) -> bool:

        """

        Reconcile inventory once after plan optimization.

        Initial pantry

        + consolidated grocery purchases

        - all selected recipe requirements

        \= final inventory

        Never commit partial inventory updates.

        """

        from copy import deepcopy

        inventory = deepcopy(plan_state.initial_inventory)

        # 1. Add purchases from the final basket only.

        for item in final_grocery_basket.get("items", []):

            packages = item.get("packages")

            if packages is None:

                plan_state.execution_trace.append(

                    {

                        "event": "inventory_reconciliation_failed",

                        "reason": ("Unknown package count for " f"{item.get('name')}"),

                    }

                )

                return False

            if packages == 0:

                continue

            if item.get("package_quantity") is None or not item.get("package_unit"):

                plan_state.execution_trace.append(

                    {

                        "event": "inventory_reconciliation_failed",

                        "reason": (

                            "Missing package quantity or unit for "

                            f"{item.get('name')}"

                        ),

                    }

                )

                return False

            purchase = {

                "ingredient_name": item.get("name"),

                "package_quantity": item["package_quantity"],

                "package_unit": item["package_unit"],

                "packages_needed": packages,

            }

            try:

                inventory = add_purchase(

                    inventory,

                    purchase,

                )

            except ValueError as exc:

                plan_state.execution_trace.append(

                    {

                        "event": "inventory_reconciliation_failed",

                        "reason": str(exc),

                    }

                )

                return False

        # 2. Consume measurable requirements and record qualitative ones.

        qualitative_requirements = []

        qualitative_instructions = {

            "to taste",

            "as needed",

            "as required",

            "required",

        }



        reconciliation_errors = []

        for selected in plan_state.selected_meals:

            decision = selected.get("decision") or {}

            ingredient_data = decision.get("ingredient") or {}

            required = ingredient_data.get("required_ingredients", [])

            measurable = []



            for ingredient in required:

                if not isinstance(ingredient, dict):

                    measurable.append(ingredient)

                    continue



                quantity = ingredient.get(

                    "quantity",

                    ingredient.get("required_quantity"),

                )

                unit = str(

                    ingredient.get(

                        "unit",

                        ingredient.get("required_unit", ""),

                    )

                    or ""

                ).strip().lower()

                qualitative_quantity = (

                    isinstance(quantity, str)

                    and quantity.strip().lower() in qualitative_instructions

                )

                qualitative_unit = unit in qualitative_instructions



                if qualitative_quantity or qualitative_unit:

                    qualitative_requirements.append(

                        {

                            "event": "qualitative_requirement_unresolved",

                            "recipe_id": selected.get("recipe_id"),

                            "ingredient_name": (

                                ingredient.get("ingredient_name")

                                or ingredient.get("name")

                            ),

                            "quantity": quantity,

                            "unit": unit,

                        }

                    )

                else:

                    measurable.append(ingredient)



            # Check every measurable requirement instead of stopping at the

            # first incompatible unit. Only the local inventory copy changes.

            for ingredient in measurable:

                try:

                    inventory = consume_inventory(inventory, [ingredient])

                except ValueError as exc:

                    reason = str(exc)

                    ingredient_name = (

                        ingredient.get("ingredient_name") or ingredient.get("name")

                        if isinstance(ingredient, dict) else None

                    )

                    if reason.startswith("Package contents unknown"):

                        error_type = "package_contents_unknown"

                    elif reason.startswith("Incompatible inventory units:"):

                        error_type = "unresolved_conversion"

                    elif reason.startswith("Insufficient inventory"):

                        error_type = "insufficient_inventory"

                    else:

                        error_type = "inventory_error"

                    reconciliation_errors.append({

                        "recipe_id": selected.get("recipe_id"),

                        "ingredient_name": ingredient_name,

                        "error_type": error_type,

                        "reason": reason,

                    })



        if reconciliation_errors:

            # Preserve the original inventory and the failure semantics.

            # Report all issues in a single event for easier diagnosis.

            plan_state.execution_trace.append({

                "event": "inventory_reconciliation_failed",

                "reason": "One or more ingredient requirements could not be reconciled.",

                "unresolved_count": sum(

                    error["error_type"] in {"unresolved_conversion", "package_contents_unknown"}

                    for error in reconciliation_errors

                ),

                "error_count": len(reconciliation_errors),

                "details": reconciliation_errors,

            })

            return False



        plan_state.execution_trace.extend(qualitative_requirements)

        # Numeric requirements were reconciled, but qualitative quantities

        # cannot be subtracted precisely from inventory.

        plan_state.current_inventory = inventory

        if qualitative_requirements:

            plan_state.execution_trace.append(

                {

                    "event": "inventory_reconciliation_incomplete",

                    "reason": "Qualitative ingredient quantities remain unresolved.",

                    "unresolved_count": len(qualitative_requirements),

                }

            )

            return True



        # 3. Commit only when all requirements are measurable and succeed.

        plan_state.execution_trace.append(

            {

                "event": "inventory_reconciled",

                "selected_meals": len(plan_state.selected_meals),

            }

        )

        return True



    def _update_inventory(

        self,

        plan_state: PlanState,

        decision: dict,

    ) -> None:

        ingredient_data = decision.get(

            "ingredient",

            {},

        )

        grocery_data = decision.get(

            "grocery",

            {},

        )

        required_ingredients = ingredient_data.get(

            "required_ingredients",

            [],

        )

        grocery_items = grocery_data.get(

            "items",

            [],

        )

        inventory = plan_state.current_inventory

        # ========================================================

        # 1. ADD PURCHASED PACKAGES

        # ========================================================

        for item in grocery_items:

            package_quantity = item.get("package_quantity")

            package_unit = item.get("package_unit")

            packages_needed = item.get("packages_needed")

            # Some outputs may use "packages".

            if packages_needed is None:

                packages_needed = item.get("packages")

            if (

                package_quantity is None

                or package_unit is None

                or packages_needed is None

            ):

                continue

            purchase = {

                "ingredient_name": (

                    item.get("ingredient")

                    or item.get("ingredient_name")

                    or item.get("name")

                ),

                "package_quantity": package_quantity,

                "package_unit": package_unit,

                "packages_needed": packages_needed,

            }

            try:

                inventory = add_purchase(

                    inventory,

                    purchase,

                )

            except ValueError as exc:

                plan_state.execution_trace.append(

                    {

                        "event": "inventory_purchase_warning",

                        "reason": str(exc),

                    }

                )

        # ========================================================

        # 2. CONSUME RECIPE INGREDIENTS

        # ========================================================

        try:

            inventory = consume_inventory(

                inventory,

                required_ingredients,

            )

        except ValueError as exc:

            # Do NOT crash the whole planner.

            #

            # Keep trace so this can be investigated.

            plan_state.execution_trace.append(

                {

                    "event": "inventory_consumption_warning",

                    "recipe_id": decision.get("recipe_id"),

                    "reason": str(exc),

                }

            )

        plan_state.current_inventory = inventory

    @staticmethod



    def _inventory_to_pantry(

        inventory: dict,

    ) -> list[dict]:

        pantry = []

        for name, item in (inventory or {}).items():

            pantry.append(

                {

                    "ingredient_name": name,

                    "quantity": item.get("quantity"),

                    "unit": item.get("unit"),

                }

            )

        return pantry



    def _build_final_grocery_basket(

        self,

        plan_state: PlanState,

    ) -> dict:

        recipe_requirements = []

        product_catalog = []

        # ========================================================

        # COLLECT DATA FROM SELECTED MEALS

        # ========================================================

        for selected in plan_state.selected_meals:

            recipe_id = selected.get("recipe_id")

            decision = selected.get(

                "decision",

                {},

            )

            # ----------------------------------------------------

            # Required ingredients

            # ----------------------------------------------------

            ingredient_data = decision.get(

                "ingredient",

                {},

            )

            required = ingredient_data.get(

                "required_ingredients",

                [],

            )

            recipe_requirements.append(

                {

                    "recipe_id": recipe_id,

                    "ingredients": required,

                }

            )

            # ----------------------------------------------------

            # Reuse product information already obtained

            # during candidate evaluation.

            #

            # This avoids unnecessary extra web calls.

            # ----------------------------------------------------

            grocery_data = decision.get(

                "grocery",

                {},

            )

            for item in grocery_data.get(

                "items",

                [],

            ):

                ingredient_name = (

                    item.get("ingredient")

                    or item.get("ingredient_name")

                    or item.get("name")

                )

                if not ingredient_name:

                    continue

                # Preserve original Grocery Agent evidence.

                # Do not turn estimated prices into verified prices.

                price = item.get("price")

                if price is None:

                    price = item.get("price_per_package")

                product_catalog.append(

                    {

                        **item,

                        "ingredient_id": item.get("ingredient_id"),

                        "ingredient_name": ingredient_name,

                        "package_quantity": item.get("package_quantity"),

                        "package_unit": item.get("package_unit"),

                        "price": price,

                    }

                )

        # ========================================================

        # INITIAL PANTRY

        #

        # Important:

        # Member 4's final aggregation must subtract the

        # ORIGINAL pantry, not the already-consumed final inventory.

        # ========================================================

        initial_inventory_list = self._inventory_to_pantry(plan_state.initial_inventory)

        # ========================================================

        # BUILD FINAL PLAN BASKET

        # ========================================================

        # If fake/unit-test candidates do not contain real

        # ingredient data, preserve the old fallback behaviour.

        if not recipe_requirements or not any(

            item["ingredients"] for item in recipe_requirements

        ):

            has_selected_meals = len(plan_state.selected_meals) > 0

            return {

                "items": [],

                "known_cost": round(

                    plan_state.estimated_spent,

                    2,

                ),

                # An empty plan has nothing to price, so it must

                # not be reported as a successfully priced plan.

                "all_items_priced": has_selected_meals,

                "unpriced_items": [],

                "aggregated_requirements": [],

                "status": ("complete" if has_selected_meals else "empty_plan"),

            }

        return build_plan_grocery_basket(

            recipe_requirements=recipe_requirements,

            inventory=initial_inventory_list,

            product_catalog=product_catalog,

        )

    @staticmethod



    def _extract_cost(decision: dict) -> float:

        """

        Extract the total cost of ONE candidate recipe.

        Returns:

            Complete projected cost, or complete verified cost.

        Raises:

            ValueError when no complete cost is available.

        Important:

            This is a standalone candidate cost.

            It is NOT the incremental cost of adding a

            recipe to the combined meal-plan basket.

        """

        grocery = decision.get("grocery")

        if not isinstance(grocery, dict):

            raise ValueError("Candidate has no valid grocery result")

        # Prefer verified cost when every item is priced.

        if grocery.get("all_items_priced") is True:

            known = grocery.get("known_cost")

            if known is not None:

                cost = float(known)

                if cost >= 0:

                    return cost

        # Otherwise use a complete provisional projection.

        if grocery.get("projected_cost_complete") is True:

            projected = grocery.get("projected_cost")

            if projected is not None:

                cost = float(projected)

                if cost >= 0:

                    return cost

        # Never silently interpret missing prices as zero.

        raise ValueError("Candidate grocery cost is incomplete")

    @staticmethod



    def _extract_reason(

        decision: dict,

    ) -> Any:

        if decision.get("status") == "failed":

            return {

                "stage": decision.get("stage"),

                "reason": decision.get("reason"),

            }

        reasoning = decision.get(

            "reasoning",

            {},

        )

        status = reasoning.get("status")

        if status == "rejected":

            return reasoning.get(

                "failed_constraints",

                [],

            )

        if status == "uncertain":

            return reasoning.get(

                "unknown_constraints",

                [],

            )

        return "unspecified"


