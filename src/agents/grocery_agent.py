"""src/agents/grocery_agent.py
Grocery Agent.
The Grocery Agent receives missing ingredients from the
Ingredient Agent / Manager and uses GroceryService to obtain
purchasable FairPrice grocery options.
BudgetService checks whether the combined grocery purchase
cost fits the remaining budget.
The final recipe decision remains with the Reasoning Engine.
"""
import math
from src.agents.contracts import (
    AgentResult,
    AgentStatus,
)
from src.grocery.grocery_service import (
    GroceryService,
    grocery_summary,
)
from src.reasoning.budget_service import (
    check_grocery_budget,
    check_provisional_grocery_budget,
)
from src.grocery.units import to_base
from src.grocery.ingredient_conversions import (
    estimate_ingredient_mass,
)
class GroceryAgent:
    """
    Agent responsible for grocery purchasing facts.
    Input:
        recipe_id:
            Candidate recipe being evaluated.
        missing_ingredients:
            Ingredients that need to be purchased.
        remaining_budget:
            Available grocery budget. Optional.
    Output:
        Shared AgentResult containing grocery information,
        combined purchase cost, and budget feasibility.
    """
    def __init__(
        self,
        grocery_service: GroceryService | None = None,
    ):
        self.grocery_service = (
            grocery_service
            if grocery_service is not None
            else GroceryService()
        )
    def run(
        self,
        recipe_id: str,
        missing_ingredients: list[dict] | dict,
        remaining_budget: float | None = None,
    ) -> dict:
        """
        Find purchasable grocery options for missing ingredients.
        GroceryService performs:
        - FairPrice search
        - product filtering
        - price extraction
        - package parsing
        - package calculation
        - minimum-package fallback
        - caching
        BudgetService performs:
        - total known purchase cost checking
        - budget feasibility
        - remaining budget calculation
        - unknown-cost handling
        """
        # ---------------------------------------------------------
        # Validate recipe ID
        # ---------------------------------------------------------
        if not recipe_id:
            return AgentResult(
                agent="grocery",
                status=AgentStatus.FAILED,
                data={},
                warnings=[],
                errors=["recipe_id is required"],
            ).to_dict()
        # ---------------------------------------------------------
        # Validate missing ingredients
        # ---------------------------------------------------------
        if not isinstance(
            missing_ingredients,
            (list, dict),
        ):
            return AgentResult(
                agent="grocery",
                status=AgentStatus.FAILED,
                data={
                    "recipe_id": recipe_id,
                },
                warnings=[],
                errors=[
                    "missing_ingredients must be a list or dictionary"
                ],
            ).to_dict()
        # ---------------------------------------------------------
        # Nothing needs purchasing
        # ---------------------------------------------------------
        if not missing_ingredients:
            budget_result = None
            budget_status = "not_checked"
            if remaining_budget is not None:
                try:
                    budget_result = check_grocery_budget(
                        grocery_results={
                            "priced_products": [],
                            "incomplete_products": [],
                            "missing_products": [],
                        },
                        remaining_budget=remaining_budget,
                    )
                    budget_status = budget_result["budget_status"]
                except (TypeError, ValueError) as exc:
                    return AgentResult(
                        agent="grocery",
                        status=AgentStatus.FAILED,
                        data={
                            "recipe_id": recipe_id,
                        },
                        warnings=[],
                        errors=[
                            f"Budget validation failed: {exc}"
                        ],
                    ).to_dict()
            return AgentResult(
                agent="grocery",
                status=AgentStatus.SUCCESS,
                data={
                    "recipe_id": recipe_id,
                    "items": [],
                    "known_cost": 0.0,
                    "all_items_priced": True,
                    "unpriced_items": [],
                    "projected_cost": 0.0,
                    "projected_cost_complete": True,
                    "projected_items": 0,
                    "projection_missing": [],
                    "budget": budget_result,
                    "budget_status": budget_status,
                    "remaining_budget": remaining_budget,
                    "budget_after_purchase": (
                        budget_result.get("budget_after_purchase")
                        if budget_result is not None
                        else None
                    ),
                },
                warnings=[],
                errors=[],
            ).to_dict()
        # ---------------------------------------------------------
        # Call existing GroceryService
        # ---------------------------------------------------------
        try:
            options = (
                self.grocery_service
                .get_grocery_list(
                    missing_ingredients,
                    recipe_id=recipe_id,
                )
            )
            # ---------------------------------------------------------
            # Prevent empty grocery results from being treated
            # as successfully priced purchases.
            # ---------------------------------------------------------
            if not options:
                return AgentResult(
                    agent="grocery",
                    status=AgentStatus.PARTIAL,
                    data={
                        "recipe_id": recipe_id,
                        "items": [],
                        "known_cost": 0.0,
                        "all_items_priced": False,
                        "unpriced_items": [
                            (
                                item.get("ingredient_name")
                                or item.get("ingredient")
                            )
                            for item in (
                                missing_ingredients.values()
                                if isinstance(missing_ingredients, dict)
                                else missing_ingredients
                            )
                            if isinstance(item, dict)
                        ] if isinstance(missing_ingredients, list) else list(missing_ingredients.keys()),
                        "budget": None,
                        "budget_status": "uncertain"
                            if remaining_budget is not None
                            else "not_checked",
                        "remaining_budget": remaining_budget,
                        "budget_after_purchase": None,
                    },
                    warnings=[
                        "Grocery lookup returned no products for "
                        "the requested missing ingredients."
                    ],
                    errors=[],
                ).to_dict()
            grocery_results = grocery_summary(options)
        except Exception as exc:
            return AgentResult(
                agent="grocery",
                status=AgentStatus.FAILED,
                data={
                    "recipe_id": recipe_id,
                },
                warnings=[],
                errors=[
                    f"Grocery lookup failed: {exc}"
                ],
            ).to_dict()
        # ---------------------------------------------------------
        # Known purchase cost
        #
        # Only products with a usable total_cost contribute.
        # Missing/incomplete products are NOT treated as free.
        # ---------------------------------------------------------
        known_cost = round(
            sum(
                float(item["total_cost"])
                for item in grocery_results["priced_products"]
                if item.get("total_cost") is not None
            ),
            2,
        )
        # ---------------------------------------------------------
        # Find items whose purchase cost is unknown
        # ---------------------------------------------------------
        unpriced_items = []
        for item in grocery_results["incomplete_products"]:
            ingredient = item.get("ingredient")
            if ingredient:
                unpriced_items.append(ingredient)
        for item in grocery_results["missing_products"]:
            ingredient = item.get("ingredient")
            if ingredient:
                unpriced_items.append(ingredient)
        # Remove duplicates while preserving order.
        unpriced_items = list(
            dict.fromkeys(unpriced_items)
        )
        # ---------------------------------------------------------
        # all_items_priced
        # ---------------------------------------------------------
        all_items_priced = (
            len(unpriced_items) == 0
        )
        # ---------------------------------------------------------
        # Warnings
        # ---------------------------------------------------------
        warnings = [
            f"No complete purchase price found for {ingredient}"
            for ingredient in unpriced_items
        ]
        # ---------------------------------------------------------
        # Warn when one retail package is assumed sufficient.
        #
        # The purchase price is known, but exact quantity
        # coverage has not been verified.
        # ---------------------------------------------------------
        for item in grocery_results["priced_products"]:
            if (
                item.get("purchase_basis") == "minimum_retail_package"
                or item.get("match_status") == "matched_minimum_package"
            ):
                ingredient = item.get(
                    "ingredient",
                    "unknown ingredient",
                )
                warnings.append(
                    f"{ingredient}: one retail package is "
                    "assumed sufficient; exact quantity "
                    "coverage is not verified."
                )
        # ---------------------------------------------------------
        # Agent status
        #
        # success:
        #   Every grocery item has a usable purchase cost.
        #
        # partial:
        #   Some costs remain unknown.
        #
        # failed:
        #   Invalid input or service failure.
        # ---------------------------------------------------------
        if all_items_priced:
            status = AgentStatus.SUCCESS
        else:
            status = AgentStatus.PARTIAL
        # ---------------------------------------------------------
        # Combine grocery items
        # ---------------------------------------------------------
        items = (
            grocery_results["priced_products"]
            + grocery_results["incomplete_products"]
            + grocery_results["missing_products"]
        )
        # ---------------------------------------------------------
        # BUDGET SERVICE INTEGRATION
        #
        # Pass actual GroceryService results.
        #
        # BudgetService returns:
        #   pass
        #   hard_fail
        #   uncertain
        #
        # If no budget was provided:
        #   not_checked
        # ---------------------------------------------------------
        budget_result = None
        budget_status = "not_checked"
        if remaining_budget is not None:
            try:
                budget_result = check_grocery_budget(
                    grocery_results=grocery_results,
                    remaining_budget=remaining_budget,
                )
                budget_status = budget_result["budget_status"]
            except (TypeError, ValueError) as exc:
                return AgentResult(
                    agent="grocery",
                    status=AgentStatus.FAILED,
                    data={
                        "recipe_id": recipe_id,
                        "items": items,
                        "known_cost": known_cost,
                        "all_items_priced": all_items_priced,
                        "unpriced_items": unpriced_items,
                    },
                    warnings=warnings,
                    errors=[
                        f"Budget validation failed: {exc}"
                    ],
                ).to_dict()
        # ---------------------------------------------------------
        # PROVISIONAL BUDGET EVALUATION
        #
        # Separate from the existing BudgetService decision.
        # Never overwrite budget_status or known_cost.
        # ---------------------------------------------------------
        estimated_budget_status = "not_checked"
        estimated_budget_after_purchase = None
        estimated_budget_reason = (
            "No remaining budget was provided."
        )
        projected_cost = grocery_results.get("projected_cost")
        projection_complete = grocery_results.get(
            "projected_cost_complete",
            False,
        )
        if remaining_budget is not None:
            if (
                not projection_complete
                or projected_cost is None
            ):
                estimated_budget_status = "uncertain"
                estimated_budget_reason = (
                    "One or more grocery items have no "
                    "reliable projected purchase cost."
                )
            else:
                projected_remaining = round(
                    float(remaining_budget)
                    - float(projected_cost),
                    2,
                )
                estimated_budget_after_purchase = (
                    projected_remaining
                )
                if projected_remaining >= 0:
                    estimated_budget_status = "pass"
                    estimated_budget_reason = (
                        "Projected grocery purchases fit "
                        "within the available budget. "
                        "This is a provisional estimate, "
                        "not a verified purchase total."
                    )
                else:
                    estimated_budget_status = "hard_fail"
                    estimated_budget_reason = (
                        "Projected grocery purchases exceed "
                        "the available budget. "
                        "This is a provisional estimate."
                    )
        # ---------------------------------------------------------
        # PROVISIONAL BUDGET SERVICE RESULT
        #
        # Separate from the strict BudgetService result.
        # Does not overwrite known_cost or budget_status.
        # ---------------------------------------------------------
        try:
            provisional_budget_result = (
                check_provisional_grocery_budget(
                    projected_cost=projected_cost,
                    projected_cost_complete=projection_complete,
                    remaining_budget=remaining_budget,
                    safety_margin=0.20,
                )
            )
        except (TypeError, ValueError) as exc:
            return AgentResult(
                agent="grocery",
                status=AgentStatus.FAILED,
                data={
                    "recipe_id": recipe_id,
                    "items": items,
                    "known_cost": known_cost,
                    "all_items_priced": all_items_priced,
                    "unpriced_items": unpriced_items,
                },
                warnings=warnings,
                errors=[
                    f"Provisional budget validation failed: {exc}"
                ],
            ).to_dict()
        # ---------------------------------------------------------
        # OPTIONAL PLANNING BUDGET INFORMATION
        #
        # This does not modify BudgetService results.
        # It does not turn LLM estimates into verified costs.
        # ---------------------------------------------------------
        planning_budget_status = budget_status
        planning_budget_source = "verified"
        if budget_status == "not_checked":
            planning_budget_source = "not_checked"
        elif (
            budget_status == "uncertain"
            and projection_complete
            and projected_cost is not None
        ):
            if estimated_budget_status == "pass":
                planning_budget_status = "provisional_pass"
                planning_budget_source = "estimated"
            elif estimated_budget_status == "hard_fail":
                planning_budget_status = "provisional_hard_fail"
                planning_budget_source = "estimated"
            else:
                planning_budget_status = "uncertain"
                planning_budget_source = "incomplete"
        elif budget_status == "uncertain":
            planning_budget_source = "incomplete"
        # ---------------------------------------------------------
        # Shared AgentResult
        # ---------------------------------------------------------
        return AgentResult(
            agent="grocery",
            status=status,
            data={
                "recipe_id": recipe_id,
                "items": items,
                "known_cost": known_cost,
                # Provisional shopping estimate.
                # Does not affect the verified budget decision.
                "projected_cost": grocery_results.get(
                    "projected_cost"
                ),
                "projected_cost_complete": grocery_results.get(
                    "projected_cost_complete",
                    False,
                ),
                "projected_items": grocery_results.get(
                    "projected_items",
                    0,
                ),
                "projection_missing": grocery_results.get(
                    "projection_missing",
                    [],
                ),
                "all_items_priced": all_items_priced,
                "unpriced_items": unpriced_items,
                # BudgetService results
                "budget": budget_result,
                "budget_status": budget_status,
                "estimated_budget_status": (
                    estimated_budget_status
                ),
                "estimated_budget_after_purchase": (
                    estimated_budget_after_purchase
                ),
                "estimated_budget_reason": (
                    estimated_budget_reason
                ),
                 "planning_budget_status": (
                    planning_budget_status
                ),
                "planning_budget_source": (
                    planning_budget_source
                ),
                "provisional_budget": (
                    provisional_budget_result
                ),
                "remaining_budget": remaining_budget,
                "budget_after_purchase": (
                    budget_result.get("budget_after_purchase")
                    if budget_result is not None
                    else None
                ),
            },
            warnings=warnings,
            errors=[],
        ).to_dict()
# ============================================================
# DAY 5 - PLAN-LEVEL GROCERY AGGREGATION
# Member 4
# ============================================================
def _ingredient_key(item):
    """
    Return a stable key for matching an ingredient.
    ingredient_id is preferred because names may have
    capitalization/spacing differences.
    """
    ingredient_id = item.get("ingredient_id")
    if ingredient_id:
        return str(ingredient_id).strip()
    name = (
        item.get("ingredient_name")
        or item.get("name")
        or ""
    )
    return name.strip().lower()
def _ingredient_name(item):
    """
    Get ingredient name regardless of whether the source uses
    'ingredient_name' or 'name'.
    """
    return (
        item.get("ingredient_name")
        or item.get("name")
        or ""
    ).strip()

def normalize_requirement_quantity(name, quantity, unit):
    original_quantity = quantity
    original_unit = str(unit or "").strip().lower()
    ingredient_name = " ".join(str(name or "").lower().split())

    try:
        quantity = float(quantity)
    except (TypeError, ValueError, OverflowError):
        return None

    if not math.isfinite(quantity) or quantity <= 0:
        return None

    unit = original_unit

    # Preserve existing sesame oil special case.
    if ingredient_name == "sesame oil" and unit in {
        "pinch",
        "pinches",
    }:
        return {
            "quantity": round(quantity * 0.25, 4),
            "unit": "ml",
            "conversion_status": "estimated",
            "original_quantity": original_quantity,
            "original_unit": original_unit,
        }

    # Preserve exact physical volume and mass conversions.
    # These do not require ingredient-specific estimates.
    exact = to_base(quantity, unit)

    # if exact is not None and exact[1] in {"g", "ml"}:
    if (
    exact is not None
    and exact[1] in {"g", "ml"}
    and not (
        exact[1] == "ml"
        and ingredient_name not in {
            "oil",
            "vegetable oil",
            "cooking oil",
        }
        and estimate_ingredient_mass(name, quantity, unit) is not None
    )
):
        return {
            "quantity": exact[0],
            "unit": exact[1],
            "conversion_status": "exact",
            "original_quantity": original_quantity,
            "original_unit": original_unit,
        }

    # Prefer ingredient-specific estimates for count, bunch,
    # clove, and other non-standard recipe units.
    estimated = estimate_ingredient_mass(
        name,
        quantity,
        unit,
    )

    if estimated is not None:
        return {
            "quantity": estimated[0],
            "unit": estimated[1],
            "conversion_status": "estimated",
            "original_quantity": original_quantity,
            "original_unit": original_unit,
        }

    # Generic count conversions remain exact when no
    # ingredient-specific mass estimate is available.
    if exact is not None:
        return {
            "quantity": exact[0],
            "unit": exact[1],
            "conversion_status": "exact",
            "original_quantity": original_quantity,
            "original_unit": original_unit,
        }

    return {
        "quantity": quantity,
        "unit": unit,
        "conversion_status": "unresolved",
        "original_quantity": original_quantity,
        "original_unit": original_unit,
    }
# def normalize_requirement_quantity(name, quantity, unit):
#     original_quantity = quantity
#     original_unit = str(unit or "").strip().lower()
#     ingredient_name = " ".join(str(name or "").lower().split())
#     try:
#         quantity = float(quantity)
#     except (TypeError, ValueError, OverflowError):
#         return None
#     if not math.isfinite(quantity) or quantity <= 0:
#         return None
#     unit = original_unit
#     # A pinch is not a standard liquid measurement.
#     # This is an explicitly provisional MVP assumption.
#     if ingredient_name == "sesame oil" and unit in {
#         "pinch",
#         "pinches",
#     }:
#         return {
#             "quantity": round(quantity * 0.25, 4),
#             "unit": "ml",
#             "conversion_status": "estimated",
#             "original_quantity": original_quantity,
#             "original_unit": original_unit,
#         }
#     # Ingredient-specific mass conversions first.
#     estimated = estimate_ingredient_mass(
#         name,
#         quantity,
#         unit,
#     )
#     if estimated is not None:
#         return {
#             "quantity": estimated[0],
#             "unit": estimated[1],
#             "conversion_status": "estimated",
#             "original_quantity": original_quantity,
#             "original_unit": original_unit,
#         }
#     # General physical-unit conversion.
#     exact = to_base(quantity, unit)
#     if exact is not None:
#         return {
#             "quantity": exact[0],
#             "unit": exact[1],
#             "conversion_status": "exact",
#             "original_quantity": original_quantity,
#             "original_unit": original_unit,
#         }
#     return {
#         "quantity": quantity,
#         "unit": unit,
#         "conversion_status": "unresolved",
#         "original_quantity": original_quantity,
#         "original_unit": original_unit,
#     }
def aggregate_requirements(recipe_requirements):
    """
    Aggregate ingredient requirements across selected recipes.
    - Uses existing unit normalization.
    - Combines compatible normalized quantities.
    - Preserves estimated conversion status.
    - Keeps incompatible units separate.
    - Never silently adds incompatible quantities.
    """
    aggregated = {}
    status_priority = {
        "exact": 0,
        "estimated": 1,
        "unresolved": 2,
    }
    for recipe in recipe_requirements or []:
        recipe_id = recipe.get("recipe_id")
        for ingredient in recipe.get("ingredients", []):
            key = _ingredient_key(ingredient)
            if not key:
                continue
            name = _ingredient_name(ingredient)
            normalized = normalize_requirement_quantity(
                name=name,
                quantity=ingredient.get("quantity"),
                unit=ingredient.get("unit"),
            )
            if normalized is None:
                continue
            quantity = normalized["quantity"]
            unit = normalized["unit"]
            conversion_status = normalized["conversion_status"]
            # Different incompatible units must remain separate.
            group_key = (key, unit)
            if group_key not in aggregated:
                aggregated[group_key] = {
                    "ingredient_id": ingredient.get("ingredient_id"),
                    "ingredient_name": name,
                    "quantity": 0.0,
                    "unit": unit,
                    "recipe_ids": [],
                    "conversion_status": conversion_status,
                    "normalization_status": "resolved",
                    "source_requirements": [],
                }
            record = aggregated[group_key]
            record["quantity"] += quantity
            # Preserve the least certain conversion status.
            current_status = record["conversion_status"]
            if (
                status_priority[conversion_status]
                > status_priority[current_status]
            ):
                record["conversion_status"] = conversion_status
            record["source_requirements"].append({
                "recipe_id": recipe_id,
                "quantity": normalized["original_quantity"],
                "unit": normalized["original_unit"],
                "conversion_status": conversion_status,
            })
            if (
                recipe_id is not None
                and recipe_id not in record["recipe_ids"]
            ):
                record["recipe_ids"].append(recipe_id)
    # Identify ingredients with incompatible unit groups.
    ingredient_groups = {}
    for (ingredient_key, unit), record in aggregated.items():
        ingredient_groups.setdefault(
            ingredient_key, []
        ).append(record)
    for records in ingredient_groups.values():
        if len(records) > 1:
            units = [record["unit"] for record in records]
            for record in records:
                record["normalization_status"] = "unresolved"
                record["unresolved_units"] = units
    return list(aggregated.values())
# def subtract_inventory(requirements, inventory):
#     """
#     Deduct pantry stock from aggregated requirements.
#     Does not mutate the original inventory.
#     Does not consume the same pantry stock twice.
#     """
#     stock_map = {}
#     for item in inventory or []:
        
#         key = _ingredient_key(item)
#         if not key:
#             continue
#         name = _ingredient_name(item)
#         normalized = normalize_requirement_quantity(
#             name,
#             item.get("quantity"),
#             item.get("unit"),
#         )
#         if normalized is None:
#             continue
#         stock_map.setdefault(key, []).append({
#             "quantity": normalized["quantity"],
#             "unit": normalized["unit"],
#             "conversion_status": normalized["conversion_status"],
#         })
#     results = []
#     for requirement in requirements or []:
#         key = _ingredient_key(requirement)
#         required = float(requirement.get("quantity", 0))
#         required_unit = requirement.get("unit")
#         remaining = required
#         inventory_used = 0.0
#         inventory_unresolved = False
#         for stock in stock_map.get(key, []):
#             if remaining <= 0:
#                 break
#             # Requirements and inventory must share a
#             # comparable normalized unit.
#             if stock["unit"] != required_unit:
#                 inventory_unresolved = True
#                 continue
#             available = max(0.0, stock["quantity"])
#             consumed = min(remaining, available)
#             remaining -= consumed
#             inventory_used += consumed
#             stock["quantity"] -= consumed
#         result = dict(requirement)
#         result.update({
#             "required_quantity": required,
#             "inventory_available": inventory_used,
#             "inventory_used": inventory_used,
#             "purchase_required": max(0.0, remaining),
#             "inventory_conversion_unresolved": inventory_unresolved,
#         })
#         results.append(result)
#     return results
def subtract_inventory(requirements, inventory):
    """
    Deduct pantry stock from aggregated requirements.
    Does not mutate the original inventory.
    Does not consume the same pantry stock twice.
    """

    # NEW: Match ingredients by normalized name.
    # This handles recipe IDs such as ING2337 when
    # pantry records contain only ingredient names.
    def pantry_match_key(item):
        name = _ingredient_name(item)
        return " ".join(name.lower().split())

    stock_map = {}

    for item in inventory or []:

        # CHANGED: Use normalized ingredient name.
        key = pantry_match_key(item)

        if not key:
            continue

        name = _ingredient_name(item)

        normalized = normalize_requirement_quantity(
            name,
            item.get("quantity"),
            item.get("unit"),
        )

        if normalized is None:
            continue

        stock_map.setdefault(key, []).append({
            "quantity": normalized["quantity"],
            "unit": normalized["unit"],
            "conversion_status": normalized["conversion_status"],
        })

    results = []

    for requirement in requirements or []:

        # CHANGED: Use the same key as pantry inventory.
        key = pantry_match_key(requirement)

        required = float(requirement.get("quantity", 0))
        required_unit = requirement.get("unit")

        remaining = required
        inventory_used = 0.0
        inventory_unresolved = False

        for stock in stock_map.get(key, []):

            if remaining <= 0:
                break

            # Requirements and inventory must share
            # a comparable normalized unit.
            if stock["unit"] != required_unit:
                inventory_unresolved = True
                continue

            available = max(0.0, stock["quantity"])
            consumed = min(remaining, available)

            remaining -= consumed
            inventory_used += consumed

            # Prevent the same pantry stock being used twice.
            stock["quantity"] -= consumed

        result = dict(requirement)

        result.update({
            "required_quantity": required,
            "inventory_available": inventory_used,
            "inventory_used": inventory_used,
            "purchase_required": max(0.0, remaining),
            "inventory_conversion_unresolved": inventory_unresolved,
        })

        results.append(result)

    return results
def calculate_packages(
    required_quantity,
    package_quantity,
):
    """
    Calculate the number of whole packages that must be bought.
    Examples:
        need 200g, package 1000g -> 1
        need 1000g, package 1000g -> 1
        need 1001g, package 1000g -> 2
    """
    try:
        required_quantity = float(required_quantity)
        package_quantity = float(package_quantity)
    except (TypeError, ValueError):
        return None
    if required_quantity <= 0:
        return 0
    if package_quantity <= 0:
        return None
    return math.ceil(
        required_quantity / package_quantity
    )
def calculate_package_leftover(
    required_quantity,
    package_quantity,
    packages,
):
    """
    Calculate how much purchased product remains after
    satisfying the current requirement.
    """
    if packages is None:
        return None
    try:
        required_quantity = float(required_quantity)
        package_quantity = float(package_quantity)
        packages = int(packages)
    except (TypeError, ValueError):
        return None
    purchased_quantity = (
        package_quantity * packages
    )
    return max(
        0.0,
        purchased_quantity - required_quantity,
    )
def find_plan_product(
    requirement,
    product_catalog,
):
    """
    Find a grocery product for an ingredient.
    Matching order:
    1. ingredient_id
    2. normalized ingredient name
    """
    requirement_id = requirement.get("ingredient_id")
    # --------------------------------------------------------
    # 1. ID matching
    # --------------------------------------------------------
    if requirement_id:
        for product in product_catalog or []:
            if (
                str(
                    product.get("ingredient_id", "")
                ).strip()
                == str(requirement_id).strip()
            ):
                return product
    # --------------------------------------------------------
    # 2. Name matching
    # --------------------------------------------------------
    requirement_name = _ingredient_name(
        requirement
    ).lower()
    if requirement_name:
        for product in product_catalog or []:
            product_name = (
                product.get("ingredient_name")
                or product.get("name")
                or ""
            ).strip().lower()
            if product_name == requirement_name:
                return product
    return None
def collect_qualitative_requirements(recipe_requirements):
    """Preserve non-numeric ingredient instructions separately."""
    qualitative = []
    seen = set()
    qualitative_units = {
        "to taste",
        "as needed",
        "as required",
    }
    for recipe in recipe_requirements or []:
        recipe_id = recipe.get("recipe_id")
        for ingredient in recipe.get("ingredients", []):
            raw_quantity = ingredient.get("quantity")
            raw_unit = str(ingredient.get("unit") or "").strip().lower()
            instruction = None
            if isinstance(raw_quantity, str):
                candidate = raw_quantity.strip().lower()
                if candidate in qualitative_units:
                    instruction = candidate
            if raw_unit in qualitative_units:
                instruction = raw_unit
            if instruction is None:
                continue
            name = _ingredient_name(ingredient)
            key = (
                ingredient.get("ingredient_id"),
                name.lower(),
                instruction,
                recipe_id,
            )
            if key in seen:
                continue
            seen.add(key)
            qualitative.append({
                "ingredient_id": ingredient.get("ingredient_id"),
                "ingredient_name": name,
                "instruction": instruction,
                "quantity": raw_quantity,
                "unit": instruction,
                "recipe_id": recipe_id,
                "recipe_ids": [recipe_id] if recipe_id is not None else [],
            })
    return qualitative
def build_plan_grocery_basket(
    recipe_requirements,
    inventory=None,
    product_catalog=None,
):
    """
    Build one grocery basket for the full meal plan.
    Backward-compatible input/output structure.
    Important:
    The current MultiMealPlanner passes a reduced
    product catalog without reliable price-source
    metadata. Such prices are treated as projections,
    not automatically verified retail costs.
    """
    import math
    inventory = inventory or []
    product_catalog = product_catalog or []
    qualitative_requirements = collect_qualitative_requirements(
        recipe_requirements
    )
    aggregated = aggregate_requirements(
        recipe_requirements
    )
    purchase_requirements = subtract_inventory(
        aggregated,
        inventory,
    )
    unresolved_requirements = [
        requirement
        for requirement in purchase_requirements
        if (
            requirement.get("normalization_status")
            == "unresolved"
            or requirement.get(
                "conversion_status"
            ) == "unresolved"
        )
    ]
    basket_items = []
    known_cost = 0.0
    projected_cost = 0.0
    unpriced_items = []
    projection_missing = []
    warnings = []
    unit_aliases = {
        "tbsp": "tablespoon",
        "tbs": "tablespoon",
        "tablespoons": "tablespoon",
        "tsp": "teaspoon",
        "teaspoons": "teaspoon",
        "gram": "g",
        "grams": "g",
        "kilogram": "kg",
        "kilograms": "kg",
        "milliliter": "ml",
        "milliliters": "ml",
        "millilitre": "ml",
        "millilitres": "ml",
        "liter": "l",
        "liters": "l",
        "litre": "l",
        "litres": "l",
        "piece": "pcs",
        "pieces": "pcs",
        "count": "pcs",
        "heads": "head",
    }
    unit_info = {
        "tablespoon": ("volume", 15.0),
        "teaspoon": ("volume", 5.0),
        "g": ("mass", 1.0),
        "kg": ("mass", 1000.0),
        "ml": ("volume", 1.0),
        "l": ("volume", 1000.0),
        "pcs": ("count", 1.0),
        "head": ("head", 1.0),
        "clove": ("clove", 1.0),
        "stalk": ("stalk", 1.0),
        "sprig": ("sprig", 1.0),
    }
    def normalize_unit(value):
        text = str(value or "").strip().lower()
        if text in {"nan", "none", "null"}:
            return ""
        return unit_aliases.get(text, text)
    def positive_number(value):
        if isinstance(value, bool):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(number) or number <= 0:
            return None
        return number
    def convert_requirement(
        quantity,
        from_unit,
        to_unit,
    ):
        """
        Convert required quantity into package units.
        Returns None if no safe conversion exists.
        """
        from_unit = normalize_unit(from_unit)
        to_unit = normalize_unit(to_unit)
        if from_unit == to_unit and from_unit:
            return quantity
        source = unit_info.get(from_unit)
        target = unit_info.get(to_unit)
        if (
            source is None
            or target is None
            or source[0] != target[0]
        ):
            return None
        return (
            quantity * source[1] / target[1]
        )
    def estimate_package_conversion(
        quantity,
        from_unit,
        to_unit,
        ingredient_name,
    ):
        """Estimate package units through ingredient-specific mass data.
        This is a provisional fallback only. It must not be treated
        as exact retail quantity coverage.
        """
        from_unit = normalize_unit(from_unit)
        to_unit = normalize_unit(to_unit)
        # Convert an ingredient-specific recipe measure to mass.
        required_mass = estimate_ingredient_mass(
            ingredient_name,
            quantity,
            from_unit,
        )
        if required_mass is not None:
            grams, _ = required_mass
            if to_unit == "g":
                return grams
            if to_unit == "kg":
                return grams / 1000.0
        # Convert mass requirements to an estimated count-like unit
        # such as head, bunch, piece, clove, sprig, or wedge.
        if from_unit in {"g", "kg"}:
            required_grams = (
                quantity * 1000.0 if from_unit == "kg" else quantity
            )
            grams_per_package_unit = estimate_ingredient_mass(
                ingredient_name,
                1.0,
                to_unit,
            )
            if grams_per_package_unit is not None:
                grams, _ = grams_per_package_unit
                if grams > 0:
                    return required_grams / grams
        return None
    def implausible_package(quantity, unit, ingredient):
        """
        Conservative sanity checks for ordinary
        household grocery packages.
        These are heuristic checks, not product
        verification.
        """
        unit = normalize_unit(unit)
        if unit == "kg" and quantity > 25:
            return True
        if unit == "g" and quantity > 25000:
            return True
        if unit == "l" and quantity > 25:
            return True
        if unit == "ml" and quantity > 25000:
            return True
        return False
    for requirement in purchase_requirements:
        required = positive_number(
            requirement.get("purchase_required")
        )
        if required is None:
            continue
        ingredient_id = requirement.get(
            "ingredient_id"
        )
        ingredient_name = _ingredient_name(
            requirement
        )
        required_unit = normalize_unit(
            requirement.get("unit")
        )
        product = find_plan_product(
            requirement,
            product_catalog,
        )
        base_item = {
            "ingredient_id": ingredient_id,
            "name": ingredient_name,
            "required_quantity": required,
            "required_unit": required_unit,
            "package_quantity": None,
            "package_unit": None,
            "packages": None,
            "purchased_quantity": None,
            "price_per_package": None,
            "purchase_cost": None,
            "estimated_purchase_cost": None,
            "leftover_quantity": None,
            "inventory_used": requirement.get(
                "inventory_used", 0
            ),
            "recipe_ids": requirement.get(
                "recipe_ids", []
            ),
            "pricing_status": "unpriced",
            "purchase_basis": None,
            "quantity_coverage_verified": False,
            "price_source": "unknown",
            "conversion_status": requirement.get(
                "conversion_status", "exact"
            ),
            "normalization_status": requirement.get(
                "normalization_status", "resolved"
            ),
            "inventory_conversion_unresolved": requirement.get(
                "inventory_conversion_unresolved", False
            ),
        }
        if (
            requirement.get("normalization_status")
            == "unresolved"
            or requirement.get("conversion_status")
            == "unresolved"
        ):
            base_item["pricing_status"] = "unresolved_conversion"
            base_item["price_source"] = "unknown"
            unpriced_items.append(ingredient_name)
            projection_missing.append(ingredient_name)
            warnings.append(
                f"{ingredient_name}: unresolved quantity conversion. "
                "Purchase quantity cannot be verified."
            )
            basket_items.append(base_item)
            continue
        if product is None:
            unpriced_items.append(ingredient_name)
            projection_missing.append(ingredient_name)
            basket_items.append(base_item)
            continue
        package_quantity = positive_number(
            product.get("package_quantity")
        )
        package_unit = normalize_unit(
            product.get("package_unit")
        )
        price = positive_number(
            product.get("price")
            if product.get("price") is not None
            else product.get("price_per_package")
        )
        base_item["package_quantity"] = (
            package_quantity
        )
        base_item["package_unit"] = package_unit
        base_item["price_per_package"] = (
            round(price, 2)
            if price is not None
            else None
        )
        if price is None:
            unpriced_items.append(ingredient_name)
            projection_missing.append(ingredient_name)
            basket_items.append(base_item)
            continue
        if package_quantity is None:
            unpriced_items.append(ingredient_name)
            projection_missing.append(ingredient_name)
            base_item["pricing_status"] = "invalid_package"
            basket_items.append(base_item)
            continue
        if implausible_package(
            package_quantity,
            package_unit,
            ingredient_name,
        ):
            warnings.append(
                f"{ingredient_name}: implausible package "
                f"size {package_quantity} {package_unit}"
            )
            unpriced_items.append(ingredient_name)
            projection_missing.append(ingredient_name)
            base_item["pricing_status"] = (
                "implausible_package"
            )
            basket_items.append(base_item)
            continue
        # Preserve the existing strict plan-basket
        # contract for different unit strings.
        #
        # A separate provisional calculation can
        # still be added later without changing
        # pricing_status.
        converted_required = convert_requirement(
            required,
            required_unit,
            package_unit,
        )
        estimated_package_conversion = False
        if converted_required is None:
            converted_required = estimate_package_conversion(
                required,
                required_unit,
                package_unit,
                ingredient_name,
            )
            estimated_package_conversion = (
                converted_required is not None
            )
        if converted_required is not None:
            packages = math.ceil(
                converted_required / package_quantity
            )
            packages = max(1, packages)
            purchased_quantity = (
                packages * package_quantity
            )
            leftover_quantity = max(
                0.0,
                purchased_quantity - converted_required,
            )
            conversion_is_exact = (
                requirement.get("conversion_status", "exact") == "exact"
            )
            normalization_resolved = (
                requirement.get("normalization_status", "resolved")
                == "resolved"
            )
            inventory_resolved = not requirement.get(
                "inventory_conversion_unresolved", False
            )
            quantity_supported = (
                conversion_is_exact
                and not estimated_package_conversion
                and normalization_resolved
                and inventory_resolved
            )
            if estimated_package_conversion:
                warnings.append(
                    f"{ingredient_name}: estimated ingredient-specific "
                    "conversion used for package sizing; quantity "
                    "coverage is provisional."
                )
            is_llm_product = (
                product.get("purchase_basis") == "llm_estimated_package"
                or product.get("match_status") == "estimated_no_retail_match"
            )
            if quantity_supported:
                purchase_basis = "calculated_quantity"
            elif is_llm_product:
                purchase_basis = "minimum_retail_package"
            else:
                purchase_basis = "estimated_quantity"
        else:
            # No reliable conversion exists between the
            # required ingredient unit and retail package unit.
            #
            # One package is only a provisional shopping
            # suggestion, NOT proof of sufficient inventory.

            packages = 1

            # Quantity remains expressed in the package unit.
            # Inventory must not interpret this as recipe units.
            purchased_quantity = package_quantity

            # Leftover cannot be calculated without a
            # compatible unit conversion.
            leftover_quantity = None

            purchase_basis = "minimum_retail_package"

            # Explicitly mark coverage as unverified.
            quantity_supported = False
            warnings.append(
                f"{ingredient_name}: package coverage unresolved "
                f"(required {required} {required_unit}, "
                f"package {package_quantity} {package_unit}). "
                "One package is a provisional minimum purchase; "
                "inventory sufficiency is not verified."
            )
        estimated_purchase_cost = round(
            packages * price,
            2,
        )
        projected_cost += estimated_purchase_cost
        # Only count as known when explicit source
        # evidence is available in the catalog.
        #
        # The current planner strips that metadata,
        # so its reduced catalog normally remains
        # provisional.
        retail_total = positive_number(
            product.get("total_cost")
        )
        estimated_total = positive_number(
            product.get("estimated_total_cost")
        )
        source_basis = product.get("purchase_basis")
        source_status = product.get("match_status")
        is_llm = (
            source_basis == "llm_estimated_package"
            or source_status == "estimated_no_retail_match"
        )
        has_estimated_quantity = (
            product.get("quantity_estimated") is True
            or source_basis == "estimated_quantity"
            or source_status == "matched_estimated_quantity"
        )
        has_estimated_source = (
            estimated_total is not None
            and retail_total is None
        )
        has_retail_evidence = (
            price is not None
            and not is_llm
            and not has_estimated_quantity
            and not has_estimated_source
        )
        conversion_is_exact = (
            requirement.get("conversion_status", "exact") == "exact"
        )
        normalization_resolved = (
            requirement.get("normalization_status", "resolved")
            == "resolved"
        )
        inventory_resolved = not requirement.get(
            "inventory_conversion_unresolved", False
        )
        if (
            has_retail_evidence
            and quantity_supported
            and conversion_is_exact
            and normalization_resolved
            and inventory_resolved
        ):
            known_cost += estimated_purchase_cost
            base_item["purchase_cost"] = (
                estimated_purchase_cost
            )
            base_item["pricing_status"] = "priced"
            base_item["price_source"] = "retail"
        else:
            base_item["estimated_purchase_cost"] = (
                estimated_purchase_cost
            )
            base_item["pricing_status"] = "estimated"
            base_item["price_source"] = (
                "ollama_estimate"
                if is_llm
                else (
                    "retail_estimated_quantity"
                    if (
                        has_estimated_quantity
                        or not conversion_is_exact
                    )
                    else "unverified"
                )
            )

        # Accepted cost for meal planning and budgeting.
        # Includes both Tavily and Ollama prices.
        base_item["planning_purchase_cost"] = (
            estimated_purchase_cost

        )
        base_item.update({
            "packages": packages,
            "purchased_quantity": purchased_quantity,
            "leftover_quantity": leftover_quantity,
            "purchase_basis": purchase_basis,
            "package_conversion_status": (
                "estimated"
                if estimated_package_conversion
                else (
                    "exact"
                    if converted_required is not None
                    else "unresolved"
                )
            ),
            "quantity_coverage_verified": (
                quantity_supported
            ),
        })
        # Usable purchase cost for shopping and planning.
        # This includes verified retailer costs and
        # provisional Tavily/Ollama estimates.
        #
        # Keep purchase_cost as verified-only.
        effective_cost = (
            base_item.get("purchase_cost")
        )
        if effective_cost is None:
            effective_cost = base_item.get(
                "estimated_purchase_cost"
            )
        base_item["effective_purchase_cost"] = (
            round(float(effective_cost), 2)
            if effective_cost is not None
            else None
        )
        base_item["display_cost"] = base_item.get(
        "effective_purchase_cost"
        )
        base_item["has_usable_price"] = (
            base_item["display_cost"] is not None
        )
        base_item["cost_is_estimated"] = (
            base_item.get("pricing_status") != "priced"
        )
        basket_items.append(base_item)
    unpriced_items = list(
        dict.fromkeys(
            item.get("name")
            for item in basket_items
            if item.get("effective_purchase_cost") is None
        )
    )
    projection_missing = list(
        dict.fromkeys(projection_missing)
    )
    projection_complete = (
        len(projection_missing) == 0
    )
    all_items_have_usable_cost = (
        len(projection_missing) == 0
        and all(
            item.get("effective_purchase_cost") is not None
            for item in basket_items
        )
    )
    return {
        "items": basket_items,
        "known_cost": round(known_cost, 2),
        "unresolved_requirements": unresolved_requirements,
        "all_items_priced": all(
            item.get("pricing_status") == "priced"
            for item in basket_items
        ),
        "all_items_have_usable_cost": all(
            item.get("effective_purchase_cost") is not None
            for item in basket_items
        ),
        "qualitative_requirements": qualitative_requirements,
        "unpriced_items": unpriced_items,
        "aggregated_requirements": aggregated,
        "purchase_requirements": purchase_requirements,
        "projected_cost": (
            round(projected_cost, 2)
            if projection_complete
            else None
        ),
        "projected_cost_complete": (
            projection_complete
        ),
        "projection_missing": projection_missing,
        "warnings": warnings,
                "all_items_have_usable_cost": (
            all_items_have_usable_cost
        ),
          "planning_cost": (
            round(projected_cost, 2)
            if projection_complete
            else None
        ),
        "planning_cost_complete": projection_complete,
    }
def calculate_incremental_basket_cost(
    selected_recipe_requirements,
    candidate_recipe_requirement,
    inventory=None,
    product_catalog=None,
):
    """
    Calculate the additional grocery purchase cost
    caused by adding one candidate recipe.
    Both baskets use the SAME original inventory
    and product catalog.
    Verified and estimated costs remain separate.
    """
    import math
    selected = list(selected_recipe_requirements or [])
    if not isinstance(candidate_recipe_requirement, dict):
        raise TypeError(
            "candidate_recipe_requirement must be a dictionary"
        )
    if not isinstance(
        candidate_recipe_requirement.get("ingredients", []),
        list,
    ):
        raise ValueError(
            "Candidate ingredients must be a list"
        )
    # Use the same initial inventory for both calculations.
    inventory = inventory if inventory is not None else []
    product_catalog = (
        product_catalog if product_catalog is not None else []
    )
    # Basket before adding the candidate.
    before = build_plan_grocery_basket(
        recipe_requirements=selected,
        inventory=inventory,
        product_catalog=product_catalog,
    )
    # Basket after adding the candidate.
    after = build_plan_grocery_basket(
        recipe_requirements=(
            selected + [candidate_recipe_requirement]
        ),
        inventory=inventory,
        product_catalog=product_catalog,
    )
    def valid_cost(value):
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if not math.isfinite(number) or number < 0:
            return None
        return number
    before_known = valid_cost(before.get("known_cost"))
    after_known = valid_cost(after.get("known_cost"))
    if before_known is None or after_known is None:
        raise ValueError("Invalid known basket cost")
    # Known retail cost difference.
    known_increment = round(
        after_known - before_known, 2
    )
    # Negative increments indicate inconsistent pricing,
    # product selection, or source classification.
    if known_increment < -0.01:
        raise ValueError(
            "Known basket cost decreased after adding "
            "a recipe. Check product catalog consistency."
        )
    known_increment = max(0.0, known_increment)
    before_complete = (
        before.get("projected_cost_complete") is True
    )
    after_complete = (
        after.get("projected_cost_complete") is True
    )
    projection_complete = (
        before_complete and after_complete
    )
    projected_increment = None
    if projection_complete:
        before_projected = valid_cost(
            before.get("projected_cost")
        )
        after_projected = valid_cost(
            after.get("projected_cost")
        )
        if (
            before_projected is None
            or after_projected is None
        ):
            projection_complete = False
        else:
            difference = round(
                after_projected - before_projected, 2
            )
            if difference < -0.01:
                raise ValueError(
                    "Projected basket cost decreased after "
                    "adding a recipe. Check pricing consistency."
                )
            projected_increment = max(
                0.0, difference
            )
    # Identify products that require additional packages.
    before_items = {
        (
            item.get("ingredient_id")
            or item.get("name", "").strip().lower()
        ): item
        for item in before.get("items", [])
    }
    additional_items = []
    for item in after.get("items", []):
        key = (
            item.get("ingredient_id")
            or item.get("name", "").strip().lower()
        )
        previous = before_items.get(key, {})
        old_packages = previous.get("packages")
        new_packages = item.get("packages")
        additional_packages = None
        if (
            isinstance(old_packages, int)
            and isinstance(new_packages, int)
        ):
            additional_packages = (
                new_packages - old_packages
            )
        elif (
            not previous
            and isinstance(new_packages, int)
        ):
            additional_packages = new_packages
        additional_items.append({
            "ingredient_id": item.get("ingredient_id"),
            "name": item.get("name"),
            "previous_packages": old_packages,
            "new_packages": new_packages,
            "additional_packages": additional_packages,
            "price_per_package": item.get(
                "price_per_package"
            ),
            "pricing_status": item.get(
                "pricing_status"
            ),
        })
    return {
        "known_incremental_cost": known_increment,
        "projected_incremental_cost": projected_increment,
        "projected_cost_complete": projection_complete,
        "before_known_cost": round(before_known, 2),
        "after_known_cost": round(after_known, 2),
        "before_projected_cost": (
            before.get("projected_cost")
        ),
        "after_projected_cost": (
            after.get("projected_cost")
        ),
        "before_basket": before,
        "after_basket": after,
        "additional_items": additional_items,
        "projection_missing": list(
            after.get("projection_missing", [])
        ),
    }
def build_cost_summary(
    grocery_basket,
    initial_budget,
):
    """
    Summarize verified and projected grocery spending.
    Known cost:
        Cost supported by verified retail pricing rules.
    Projected cost:
        Complete grocery estimate, including Tavily
        and Ollama prices and provisional quantities.
    Both Tavily and Ollama prices count equally toward
    projected grocery spending.
    A complete projection is not necessarily verified.
    """
    import math
    def valid_money(value, field_name):
        if isinstance(value, bool):
            raise ValueError(
                f"{field_name} must be numeric"
            )
        try:
            number = float(value)
        except (
            TypeError,
            ValueError,
            OverflowError,
        ):
            raise ValueError(
                f"{field_name} must be numeric"
            ) from None
        if not math.isfinite(number) or number < 0:
            raise ValueError(
                f"{field_name} must be finite and nonnegative"
            )
        return round(number, 2)
    if not isinstance(grocery_basket, dict):
        raise TypeError(
            "grocery_basket must be a dictionary"
        )
    initial_budget = valid_money(
        initial_budget,
        "initial_budget",
    )
    known_cost = valid_money(
        grocery_basket.get("known_cost", 0),
        "known_cost",
    )
    projection_complete = (
        grocery_basket.get(
            "projected_cost_complete"
        ) is True
    )
    raw_projected = grocery_basket.get(
        "projected_cost"
    )
    projected_cost = None
    if (
        projection_complete
        and raw_projected is not None
    ):
        projected_cost = valid_money(
            raw_projected,
            "projected_cost",
        )
        if projected_cost + 0.01 < known_cost:
            raise ValueError(
                "Projected cost cannot be below known cost"
            )
    else:
        projection_complete = False
    known_remaining = round(
        initial_budget - known_cost,
        2,
    )
    projected_remaining = (
        round(
            initial_budget - projected_cost,
            2,
        )
        if projected_cost is not None
        else None
    )
    unpriced_items = list(
        grocery_basket.get(
            "unpriced_items", []
        ) or []
    )
    projection_missing = list(
        grocery_basket.get(
            "projection_missing", []
        ) or []
    )
    estimated_component = (
        round(
            projected_cost - known_cost,
            2,
        )
        if projected_cost is not None
        else None
    )
    # Preserve the existing verified-price contract.
    # Do not infer verification merely because every
    # ingredient has a usable projected price.
    all_items_priced = (
        grocery_basket.get(
            "all_items_priced"
        ) is True
    )
    # Tavily and Ollama estimates are both accepted
    # as usable planning costs when the complete
    # projected grocery basket is available.
    all_items_have_usable_cost = (
        grocery_basket.get(
            "all_items_have_usable_cost"
        ) is True
        or projection_complete
    )
    # Verified means all items have verified pricing.
    # Provisional means a complete projected cost exists,
    # but one or more prices or quantities are estimated.
    # Incomplete means no complete cost is available.
    if (
        all_items_priced
        and projection_complete
        and projected_cost is not None
    ):
        budget_verification = "verified"
    elif (
        projection_complete
        and projected_cost is not None
    ):
        budget_verification = "provisional"
    else:
        budget_verification = "incomplete"
    return {
        "initial_budget": initial_budget,
        "known_grocery_cost": known_cost,
        "remaining": known_remaining,
        "all_items_priced": all_items_priced,
        "all_items_have_usable_cost": (
            all_items_have_usable_cost
        ),
        "unpriced_items": unpriced_items,
        "projected_grocery_cost": projected_cost,
        "projected_cost_complete": (
            projection_complete
        ),
        "estimated_cost_component": (
            estimated_component
        ),
        "known_remaining_budget": (
            known_remaining
        ),
        "projected_remaining_budget": (
            projected_remaining
        ),
        "projection_missing": (
            projection_missing
        ),
        "known_cost_within_budget": (
            known_cost <= initial_budget
        ),
        "projected_cost_within_budget": (
            projected_cost <= initial_budget
            if projected_cost is not None
            else None
        ),
        "budget_verification": (
            budget_verification
        ),
    }
