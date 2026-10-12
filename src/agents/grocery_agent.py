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



from src.grocery.ollama_fallback_service import (

    OllamaFallbackGroceryService,

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

            else OllamaFallbackGroceryService()

        )

    def run(

        self,

        recipe_id: str,

        missing_ingredients: list[dict] | dict,

        remaining_budget: float | None = None,

    ) -> dict:

        """Return one unified shopping cost for Tavily and Ollama products.



        A price is usable when the product has a positive package price and

        a defensible package count. Source identity does not affect budget

        classification. Unknown costs are never silently treated as zero.

        """

        if not recipe_id:

            return AgentResult(

                agent="grocery", status=AgentStatus.FAILED, data={},

                warnings=[], errors=["recipe_id is required"],

            ).to_dict()

        if not isinstance(missing_ingredients, (list, dict)):

            return AgentResult(

                agent="grocery", status=AgentStatus.FAILED,

                data={"recipe_id": recipe_id}, warnings=[],

                errors=["missing_ingredients must be a list or dictionary"],

            ).to_dict()



        def money(value):

            if isinstance(value, bool):

                return None

            try:

                value = float(value)

            except (TypeError, ValueError, OverflowError):

                return None

            return value if math.isfinite(value) and value >= 0 else None



        if isinstance(missing_ingredients, dict):

            requested = list(missing_ingredients.keys())

        else:

            requested = [

                str(x.get("ingredient_name") or x.get("ingredient") or "").strip()

                for x in missing_ingredients if isinstance(x, dict)

            ]

        requested = [x for x in requested if x]



        try:

            options = (

                self.grocery_service.get_grocery_list(

                    missing_ingredients, recipe_id=recipe_id

                ) if missing_ingredients else []

            )

            summary = grocery_summary(options) if options else {

                "priced_products": [], "incomplete_products": [],

                "missing_products": [],

            }

        except Exception as exc:

            return AgentResult(

                agent="grocery", status=AgentStatus.FAILED,

                data={"recipe_id": recipe_id}, warnings=[],

                errors=[f"Grocery lookup failed: {exc}"],

            ).to_dict()



        items = (

            list(summary.get("priced_products") or [])

            + list(summary.get("incomplete_products") or [])

            + list(summary.get("missing_products") or [])

        )

        priced = []

        missing = []

        warnings = []

        total = 0.0



        for item in items:

            name = str(item.get("ingredient") or item.get("ingredient_name") or "").strip()

            package_price = money(item.get("price_per_package"))

            if package_price is None:

                package_price = money(item.get("price"))

            package_count = money(item.get("packages_needed"))

            explicit_total = money(item.get("total_cost"))

            if explicit_total is None:

                explicit_total = money(item.get("estimated_total_cost"))



            # A provided total is usable. Otherwise compute a package cost.

            cost = explicit_total

            if cost is None and package_price is not None and package_count is not None:

                if package_count >= 1 and float(package_count).is_integer():

                    cost = package_price * package_count

            if cost is None and package_price is not None:

                # One package is a shopping assumption, not quantity proof.

                package_size = money(item.get("package_quantity"))

                if package_size is not None and package_size > 0:

                    cost = package_price

                    warnings.append(

                        f"{name}: one package assumed; quantity coverage not confirmed."

                    )



            if cost is None:

                if name:

                    missing.append(name)

                    warnings.append(f"No usable grocery price found for {name}.")

                item["pricing_status"] = "unpriced"

                item["purchase_cost"] = None

                continue

            cost = round(cost, 2)

            total += cost

            item["purchase_cost"] = cost

            item["effective_purchase_cost"] = cost

            item["planning_purchase_cost"] = cost

            item["pricing_status"] = "priced"

            item["price_source"] = (

                "ollama" if (

                    item.get("purchase_basis") == "llm_estimated_package"

                    or item.get("match_status") == "estimated_no_retail_match"

                ) else "tavily"

            )

            priced.append(item)



        if not items and requested:

            missing.extend(requested)

        missing = list(dict.fromkeys(missing))

        complete = not missing

        total_cost = round(total, 2) if complete else None

        budget_status = "not_checked"

        budget_after_purchase = None

        budget = None

        if remaining_budget is not None:

            available = money(remaining_budget)

            if available is None:

                return AgentResult(

                    agent="grocery", status=AgentStatus.FAILED,

                    data={"recipe_id": recipe_id}, warnings=warnings,

                    errors=["remaining_budget must be nonnegative and finite"],

                ).to_dict()

            if total_cost is None:

                budget_status = "uncertain"

            else:

                budget_after_purchase = round(available - total_cost, 2)

                budget_status = "pass" if budget_after_purchase >= 0 else "hard_fail"

            budget = {

                "budget_status": budget_status,

                "budget_after_purchase": budget_after_purchase,

                "known_cost": round(total, 2),

            }



        data = {

            "recipe_id": recipe_id,

            "items": items,

            "known_cost": round(total, 2),

            "projected_cost": total_cost,  # Compatibility with planner.

            "projected_cost_complete": complete,

            "projected_items": len(priced),

            "projection_missing": missing,

            "all_items_priced": complete,

            "unpriced_items": missing,

            "budget": budget,

            "budget_status": budget_status,

            "planning_budget_status": budget_status,

            "planning_budget_source": "unified",

            "remaining_budget": remaining_budget,

            "budget_after_purchase": budget_after_purchase,

        }

        return AgentResult(

            agent="grocery",

            status=AgentStatus.SUCCESS if complete else AgentStatus.PARTIAL,

            data=data, warnings=warnings, errors=[],

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

    def convert_using_original_requirements(

        requirement,

        package_unit,

    ):

        """

        Use original recipe units when normalized conversion

        is unresolved or less useful than the original units.



        Returns:

            (quantity, conversion_status)



        The result is exact only when every source requirement

        can be converted directly into package units.

        """



        sources = requirement.get(

            "source_requirements"

        ) or []



        if not sources:

            return None, "unresolved"



        total = 0.0



        for source in sources:

            quantity = positive_number(

                source.get("quantity")

            )



            if quantity is None:

                return None, "unresolved"



            source_unit = normalize_unit(

                source.get("unit")

            )



            converted = convert_requirement(

                quantity,

                source_unit,

                package_unit,

            )



            if converted is None:

                return None, "unresolved"



            total += converted



        return total, "exact"

    def estimate_package_conversion(

        quantity,

        from_unit,

        to_unit,

        ingredient_name,

    ):

        """Estimate package units through ingredient-specific mass data.

        This is an estimated conversion, not exact quantity coverage.

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

        conversion_unresolved = (

            requirement.get("normalization_status")

            == "unresolved"

            or requirement.get("conversion_status")

            == "unresolved"

        )



        if conversion_unresolved:

            warnings.append(

                f"{ingredient_name}: normalized quantity conversion "

                "is unresolved. Original recipe units will be "

                "checked against the retail package."

            )



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

        converted_required = convert_requirement(

            required,

            required_unit,

            package_unit,

        )



        estimated_package_conversion = (

            requirement.get("conversion_status") == "estimated"

        )



        original_converted, original_status = (

            convert_using_original_requirements(

                requirement,

                package_unit,

            )

        )

        original_conversion_exact = (

            original_converted is not None

            and original_status == "exact"

        )



        # Prefer original units when they provide an exact,

        # directly comparable retail package quantity.

        if (

            original_conversion_exact

            and (

                converted_required is None

                or conversion_unresolved

                or estimated_package_conversion

            )

        ):



            converted_required = original_converted

            estimated_package_conversion = False

            conversion_unresolved = False

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

                inventory_resolved

                and (

                    (

                        conversion_is_exact

                        and not estimated_package_conversion

                        and normalization_resolved

                    )

                    or (

                        original_conversion_exact

                        and not estimated_package_conversion

                    )

                )

            )

            if estimated_package_conversion:

                warnings.append(

                    f"{ingredient_name}: estimated ingredient-specific "

                    "conversion used for package sizing; quantity "

                    "coverage is not confirmed."

                )

            is_llm_product = (

                product.get("purchase_basis") == "llm_estimated_package"

                or product.get("match_status") == "estimated_no_retail_match"

            )

            if quantity_supported:

                purchase_basis = "calculated_quantity"



            elif (

                converted_required is not None

                and original_conversion_exact

                and not estimated_package_conversion

            ):

                purchase_basis = "calculated_quantity"



            elif converted_required is not None:

                purchase_basis = "estimated_quantity"



            else:

                purchase_basis = "minimum_retail_package"

        else:

            # No reliable conversion exists between the

            # required ingredient unit and retail package unit.

            #

            # One package is a shopping assumption, NOT proof of sufficient inventory.



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

                "One package is assumed for shopping; "

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



        # UNIFIED PRICE CALCULATION

        # Both Tavily and Ollama package prices count equally.



        known_cost += estimated_purchase_cost



        base_item["purchase_cost"] = estimated_purchase_cost

        base_item["estimated_purchase_cost"] = None

        base_item["pricing_status"] = "priced"



        # Retain provenance for diagnostics only.

        is_ollama = (

            product.get("purchase_basis") == "llm_estimated_package"

            or product.get("match_status") == "estimated_no_retail_match"

        )



        base_item["price_source"] = (

            "ollama" if is_ollama else "tavily"

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

        # prices from either source.

        #

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




    # Add qualitative requirements without inventing recipe quantities.

    existing_ids = {

        str(item["ingredient_id"]).strip()

        for item in basket_items

        if item.get("ingredient_id")

    }




    existing_names = {

        str(item.get("name") or "").strip().lower()

        for item in basket_items

    }



    for requirement in qualitative_requirements:

        ingredient_id = requirement.get("ingredient_id")


        ingredient_name = str(

            requirement.get("ingredient_name") or ""

        ).strip()



        if not ingredient_name:

            continue



        if (

            (ingredient_id and str(ingredient_id).strip() in existing_ids)

            or ingredient_name.lower() in existing_names

        ):

            continue



        product = find_plan_product(

            requirement,

            product_catalog,

        )



        package_quantity = (

            positive_number(product.get("package_quantity"))

            if product else None

        )



        package_unit = (

            normalize_unit(product.get("package_unit"))

            if product else None

        )



        price = None

        if product:

            price = positive_number(

                product.get("price")

                if product.get("price") is not None

                else product.get("price_per_package")

            )



        usable_package = (

            price is not None

            and package_quantity is not None

            and bool(package_unit)

            and not implausible_package(

                package_quantity,

                package_unit,

                ingredient_name,

            )

        )



        item = {


            "ingredient_id": ingredient_id,

            "name": ingredient_name,

            "required_quantity": None,

            "required_unit": requirement.get("unit") or "unknown",

            "instruction": requirement.get("instruction"),


            "package_quantity": package_quantity,

            "package_unit": package_unit,

            "packages": None,

            "purchased_quantity": None,

            "price_per_package": price,


            "purchase_cost": None,

            "estimated_purchase_cost": None,

            "effective_purchase_cost": None,

            "display_cost": None,

            "has_usable_price": False,

            "cost_is_estimated": False,

            "leftover_quantity": None,

            "inventory_used": 0.0,

            "recipe_ids": requirement.get("recipe_ids", []),

            "pricing_status": "unpriced",

            "price_source": "unknown",

            "purchase_basis": "qualitative_requirement",

            "quantity_coverage_verified": False,

            "status": "quantity_unknown",


        }





        if usable_package:

            package_cost = round(price, 2)



            known_cost += package_cost

            projected_cost += package_cost



            is_ollama = (

                product.get("purchase_basis")

                == "llm_estimated_package"

                or product.get("match_status")

                == "estimated_no_retail_match"

            )



            item.update({

                "packages": 1,

                "purchased_quantity": package_quantity,

                "purchase_cost": package_cost,

                "estimated_purchase_cost": None,

                "effective_purchase_cost": package_cost,

                "display_cost": package_cost,

                "planning_purchase_cost": package_cost,

                "has_usable_price": True,

                "cost_is_estimated": False,

                "pricing_status": "priced",

                "price_source": (

                    "ollama" if is_ollama else "tavily"

                ),

                "package_conversion_status": "unresolved",

                "quantity_coverage_verified": False,

            })



            warnings.append(

                f"{ingredient_name}: recipe quantity is unspecified; "

                "one package was assumed for shopping."

            )

        else:

            projection_missing.append(ingredient_name)

            warnings.append(

                f"{ingredient_name}: no usable package price available."

            )





        basket_items.append(item)



        if ingredient_id:

            existing_ids.add(str(ingredient_id).strip())



        existing_names.add(ingredient_name.lower())




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

        "all_items_have_usable_cost": all_items_have_usable_cost,

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

    Both price sources contribute to the same shopping total.

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

def build_cost_summary(grocery_basket, initial_budget):

    """Summarize one shopping total regardless of Tavily/Ollama source.



    Legacy projected_* keys are retained solely for planner compatibility.

    """

    def valid_money(value, field):

        if isinstance(value, bool):

            raise ValueError(f"{field} must be numeric")

        try:

            value = float(value)

        except (TypeError, ValueError, OverflowError):

            raise ValueError(f"{field} must be numeric") from None

        if not math.isfinite(value) or value < 0:

            raise ValueError(f"{field} must be finite and nonnegative")

        return round(value, 2)



    if not isinstance(grocery_basket, dict):

        raise TypeError("grocery_basket must be a dictionary")

    budget = valid_money(initial_budget, "initial_budget")

    known = valid_money(grocery_basket.get("known_cost", 0), "known_cost")

    complete = grocery_basket.get("projected_cost_complete") is True

    raw_total = grocery_basket.get("projected_cost")

    total = valid_money(raw_total, "projected_cost") if complete and raw_total is not None else None

    if total is None:

        complete = False

    if total is not None and total + 0.01 < known:

        raise ValueError("Projected cost cannot be below known cost")

    missing = list(grocery_basket.get("projection_missing") or [])

    unpriced = list(grocery_basket.get("unpriced_items") or [])

    # The legacy unpriced_items field can describe items with no verified

    # retailer price even when the combined shopping cost is available.

    # Only genuinely missing purchase costs invalidate the total.

    if missing:

        complete = False

        total = None

    remaining = round(budget - known, 2)

    total_remaining = round(budget - total, 2) if total is not None else None

    return {

        "initial_budget": budget,

        "known_grocery_cost": known,

        "remaining": remaining,

        "all_items_priced": grocery_basket.get("all_items_priced") is True,

        "all_items_have_usable_cost": complete,

        "unpriced_items": unpriced,

        "projected_grocery_cost": total,

        "projected_cost_complete": complete,

        "estimated_cost_component": None,

        "known_remaining_budget": remaining,

        "projected_remaining_budget": total_remaining,

        "projection_missing": missing,

        "known_cost_within_budget": known <= budget,

        "projected_cost_within_budget": (

            total <= budget if total is not None else None

        ),

        "budget_verification": (

            "verified" if complete and grocery_basket.get("all_items_priced") is True

            else "complete" if complete else "incomplete"

        ),

    }
