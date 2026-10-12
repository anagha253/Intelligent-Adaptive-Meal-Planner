# src/planning/plan_state.py

from dataclasses import dataclass, field
from typing import Any

from src.planning.meal_slot import MealSlot


@dataclass
class PlanState:

    slots: list[MealSlot]

    initial_budget: float

    # -----------------------------------------
    # Meal-planning state
    # -----------------------------------------

    selected_meals: list[dict] = field(
        default_factory=list
    )

    used_recipe_ids: set[str] = field(
        default_factory=set
    )

    rejected_candidates: list[dict] = field(
        default_factory=list
    )

    uncertain_candidates: list[dict] = field(
        default_factory=list
    )

    # -----------------------------------------
    # Budget state
    # -----------------------------------------

    estimated_spent: float = 0.0

    # -----------------------------------------
    # Member-3 state
    # -----------------------------------------

    initial_inventory: dict = field(
        default_factory=dict
    )

    current_inventory: dict = field(
        default_factory=dict
    )

    nutrition_state: dict = field(
        default_factory=dict
    )

    # -----------------------------------------
    # Member-4 final grocery state
    # -----------------------------------------

    final_grocery_basket: dict = field(
        default_factory=dict
    )

    # -----------------------------------------
    # Planner state
    # -----------------------------------------

    status: str = "building"

    execution_trace: list[dict] = field(
        default_factory=list
    )
    skipped_slots: list[dict] = field(default_factory=list)

    # ============================================================
    # BUDGET
    # ============================================================

    @property
    def remaining_budget(self) -> float:

        return max(
            self.initial_budget
            - self.estimated_spent,
            0.0,
        )

    # ============================================================
    # SELECTED MEAL
    # ============================================================

    def add_selected_meal(
        self,
        slot: MealSlot,
        recipe_id: str,
        decision: dict,
        estimated_cost: float = 0.0,
    ) -> None:

        self.selected_meals.append(
            {
                "slot": slot.to_dict(),
                "recipe_id": recipe_id,
                "decision": decision,
                "estimated_cost":
                    estimated_cost,
            }
        )

        self.used_recipe_ids.add(
            recipe_id
        )

        self.estimated_spent += max(
            float(
                estimated_cost or 0.0
            ),
            0.0,
        )

        self.execution_trace.append(
            {
                "event":
                    "meal_selected",

                "slot_id":
                    slot.slot_id,

                "recipe_id":
                    recipe_id,
            }
        )

    # ============================================================
    # REJECTED
    # ============================================================

    def add_rejection(
        self,
        slot: MealSlot,
        recipe_id: str,
        reason: Any,
    ) -> None:

        self.rejected_candidates.append(
            {
                "slot_id":
                    slot.slot_id,

                "recipe_id":
                    recipe_id,

                "reason":
                    reason,
            }
        )

        self.execution_trace.append(
            {
                "event":
                    "candidate_rejected",

                "slot_id":
                    slot.slot_id,

                "recipe_id":
                    recipe_id,

                "reason":
                    reason,
            }
        )

    # ============================================================
    # UNCERTAIN
    # ============================================================

    def add_uncertain(
        self,
        slot: MealSlot,
        recipe_id: str,
        reason: Any,
    ) -> None:

        self.uncertain_candidates.append(
            {
                "slot_id":
                    slot.slot_id,

                "recipe_id":
                    recipe_id,

                "reason":
                    reason,
            }
        )

        self.execution_trace.append(
            {
                "event":
                    "candidate_uncertain",

                "slot_id":
                    slot.slot_id,

                "recipe_id":
                    recipe_id,

                "reason":
                    reason,
            }
        )

    # ============================================================
    # SLOT INFEASIBLE
    # ============================================================

    def mark_slot_infeasible(
        self,
        slot: MealSlot,
    ) -> None:

        self.execution_trace.append(
            {
                "event":
                    "slot_infeasible",

                "slot_id":
                    slot.slot_id,
            }
        )

    # ============================================================
    # SERIALIZATION
    # ============================================================

    def mark_slot_skipped(
        self,
        slot: MealSlot,
        reason: str = "user_skipped",
    ) -> None:
        """Record a meal slot intentionally skipped by the user."""
        if any(item.get("slot_id") == slot.slot_id for item in self.skipped_slots):
            return

        self.skipped_slots.append(
            {"slot_id": slot.slot_id, "reason": reason}
        )
        self.execution_trace.append({
            "event": "slot_skipped",
            "slot_id": slot.slot_id,
            "reason": reason,
        })

    def to_dict(self) -> dict:

        return {

            "status":
                self.status,

            "slots": [
                slot.to_dict()
                for slot in self.slots
            ],

            "selected_meals":
                self.selected_meals,

            "used_recipe_ids":
                sorted(
                    self.used_recipe_ids
                ),

            "budget": {

                "initial":
                    self.initial_budget,

                "estimated_spent":
                    self.estimated_spent,

                "remaining":
                    self.remaining_budget,
            },

            "inventory": {
                "initial":
                    self.initial_inventory,

                "current":
                    self.current_inventory,
            },

            "nutrition":
                self.nutrition_state,

            "final_grocery_basket":
                self.final_grocery_basket,

            "rejected_candidates":
                self.rejected_candidates,

            "uncertain_candidates":
                self.uncertain_candidates,

            "skipped_slots":
                self.skipped_slots,

            "execution_trace":
                self.execution_trace,
        }