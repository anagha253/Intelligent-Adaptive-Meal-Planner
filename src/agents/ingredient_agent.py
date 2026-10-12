from __future__ import annotations

import re
from typing import Any, Dict, List

from src.pantry.pantry_service import (
    fetch_recipe_ingredients,
    filter_ingredient_list,
)


# ============================================================
# HELPERS
# ============================================================

def normalize_name(name: Any) -> str:
    """Normalize ingredient names for matching."""
    if name is None:
        return ""

    return " ".join(
        str(name).strip().lower().split()
    )


def parse_quantity_unit(value: Any) -> tuple[Any, str]:
    """
    Parse pantry availability values such as:

        "200 grams"
        "5 counts"
        "2 tablespoon"

    Returns:
        (quantity, unit)
    """
    if isinstance(value, dict):
        return (
            value.get("quantity"),
            str(value.get("unit", "")).strip().lower(),
        )

    if value is None:
        return None, ""

    text = str(value).strip()

    match = re.match(
        r"^\s*([0-9]+(?:\.[0-9]+)?)\s*(.*)\s*$",
        text,
    )

    if not match:
        return None, ""

    quantity_text = match.group(1)
    unit = match.group(2).strip().lower()

    try:
        quantity = float(quantity_text)

        # Keep integers as integers where possible.
        if quantity.is_integer():
            quantity = int(quantity)
    except ValueError:
        quantity = None

    return quantity, unit


def normalize_unit(unit: Any) -> str:
    """Normalize common unit spellings without doing quantity conversion."""
    unit = str(unit or "").strip().lower()

    aliases = {
        "grams": "g",
        "gram": "g",
        "kgs": "kg",
        "kilograms": "kg",
        "kilogram": "kg",
        "milliliters": "ml",
        "milliliter": "ml",
        "liters": "l",
        "liter": "l",
        "counts": "count",
        "pieces": "piece",
        "piece": "piece",
        "tablespoons": "tablespoon",
        "tbsp": "tablespoon",
        "tablespoon": "tablespoon",
        "teaspoons": "teaspoon",
        "tsp": "teaspoon",
        "teaspoon": "teaspoon",
    }

    return aliases.get(unit, unit)


def pantry_to_dict(
    pantry_input: Any,
) -> Dict[str, Dict[str, Any]]:
    """
    Convert Manager/User-State pantry data into the dictionary
    format expected by the existing pantry_service.

    Supported input formats:

    1. User State / Manager dictionary:
       {
           "Tomatoes": "5 counts",
           "Cheese": "200 grams"
       }

    2. Structured dictionary:
       {
           "tomatoes": {
               "quantity": 5,
               "unit": "count"
           }
       }

    3. Structured list:
       [
           {
               "ingredient_id": "ING001",
               "ingredient_name": "rice",
               "quantity": 500,
               "unit": "g"
           }
       ]
    """

    pantry_dict: Dict[str, Dict[str, Any]] = {}

    if pantry_input is None:
        return pantry_dict

    # --------------------------------------------------------
    # Case 1 / 2: dictionary input
    # --------------------------------------------------------
    if isinstance(pantry_input, dict):

        for ingredient_name, value in pantry_input.items():

            name = normalize_name(ingredient_name)

            if not name:
                continue

            quantity, unit = parse_quantity_unit(value)

            pantry_dict[name] = {
                "quantity": quantity,
                "unit": normalize_unit(unit),
            }

        return pantry_dict

    # --------------------------------------------------------
    # Case 3: list input
    # --------------------------------------------------------
    if isinstance(pantry_input, list):

        for item in pantry_input:

            if not isinstance(item, dict):
                continue

            name = normalize_name(
                item.get("ingredient_name")
            )

            if not name:
                continue

            pantry_dict[name] = {
                "quantity": item.get("quantity"),
                "unit": normalize_unit(
                    item.get("unit", "")
                ),
            }

        return pantry_dict

    return pantry_dict


# ============================================================
# REQUIRED INGREDIENTS
# ============================================================

def get_required_ingredients(
    recipe_id: str,
) -> List[Dict[str, Any]]:
    """
    Retrieve recipe ingredients using the existing
    recipe-ingredient mapping service.
    """

    ingredients = fetch_recipe_ingredients(recipe_id)

    required: List[Dict[str, Any]] = []

    for ingredient_name, data in ingredients.items():

        required.append(
            {
                "ingredient_id": data.get("ingredient_id"),
                "ingredient_name": ingredient_name,
                "alias_name": data.get("alias_name"),
                "quantity": data.get("quantity"),
                "unit": normalize_unit(data.get("unit")),
            }
        )

    return required


# ============================================================
# PANTRY USED
# ============================================================

def get_pantry_used(
    required_ingredients: List[Dict[str, Any]],
    pantry: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Return recipe ingredients that are present
    in the user's pantry.

    This is presence-based for the MVP.
    """

    pantry_used: List[Dict[str, Any]] = []

    for ingredient in required_ingredients:

        name = normalize_name(
            ingredient.get("ingredient_name")
        )

        if name not in pantry:
            continue

        pantry_item = pantry[name]

        pantry_used.append(
            {
                "ingredient_id": ingredient.get(
                    "ingredient_id"
                ),
                "ingredient_name": ingredient.get(
                    "ingredient_name"
                ),
                "required_quantity": ingredient.get(
                    "quantity"
                ),
                "available_quantity": pantry_item.get(
                    "quantity"
                ),
                "unit": ingredient.get("unit"),
            }
        )

    return pantry_used


# ============================================================
# MISSING INGREDIENTS
# ============================================================

def get_missing_ingredients(
    required_ingredients_dict: Dict[str, Dict[str, Any]],
    pantry: Dict[str, Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """
    Reuse the existing pantry service to calculate
    ingredients that need to be purchased.
    """

    return filter_ingredient_list(
        pantry,
        required_ingredients_dict,
    )


def format_missing_ingredients(
    missing: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Convert existing pantry-service output
    into Ingredient Agent output format.
    """

    result: List[Dict[str, Any]] = []

    for ingredient_name, data in missing.items():

        result.append(
            {
                "ingredient_id": data.get(
                    "ingredient_id"
                ),
                "ingredient_name": ingredient_name,
                "quantity": data.get(
                    "quantity"
                ),
                "unit": data.get(
                    "unit"
                ),
                "status": data.get(
                    "status",
                    "missing",
                ),
            }
        )

    return result


# ============================================================
# INGREDIENT AGENT
# ============================================================

class IngredientAgent:
    """
    Day 4 Member 3 Ingredient Agent.

    Responsibilities:

        Recipe ID
            ↓
        Required ingredients
            ↓
        Pantry comparison
            ↓
        Missing ingredients
            ↓
        Structured output

    The Manager passes:
        recipe_id
        pantry
    """

    name = "ingredient"

    def run(
        self,
        *,
        recipe_id: str,
        pantry: Any,
    ) -> Dict[str, Any]:
        """
        Main Ingredient Agent interface.

        Called by Manager as:

            agent.run(
                recipe_id=recipe_id,
                pantry=pantry
            )
        """

        # ----------------------------------------------------
        # Validate recipe_id
        # ----------------------------------------------------

        if not recipe_id:
            return {
                "agent": self.name,
                "status": "failed",
                "data": {},
                "warnings": [],
                "errors": [
                    "recipe_id is required"
                ],
            }

        recipe_id = str(
            recipe_id
        ).strip().upper()

        # ----------------------------------------------------
        # Normalize pantry input
        # ----------------------------------------------------

        pantry_data = pantry_to_dict(
            pantry
        )

        # ----------------------------------------------------
        # Retrieve recipe ingredients
        # ----------------------------------------------------

        try:

            recipe_ingredients = fetch_recipe_ingredients(
                recipe_id
            )

        except (
            ValueError,
            FileNotFoundError,
        ) as error:

            return {
                "agent": self.name,
                "status": "failed",
                "data": {
                    "recipe_id": recipe_id
                },
                "warnings": [],
                "errors": [
                    str(error)
                ],
            }

        # ----------------------------------------------------
        # No recipe found
        # ----------------------------------------------------

        if not recipe_ingredients:

            return {
                "agent": self.name,
                "status": "failed",
                "data": {
                    "recipe_id": recipe_id
                },
                "warnings": [],
                "errors": [
                    f"No ingredients found for {recipe_id}"
                ],
            }

        # ----------------------------------------------------
        # Required ingredient list
        # ----------------------------------------------------

        required_ingredients = (
            get_required_ingredients(
                recipe_id
            )
        )

        # ----------------------------------------------------
        # Pantry used
        # ----------------------------------------------------

        pantry_used = get_pantry_used(
            required_ingredients,
            pantry_data,
        )

        # ----------------------------------------------------
        # Missing ingredients
        # ----------------------------------------------------

        missing_raw = get_missing_ingredients(
            recipe_ingredients,
            pantry_data,
        )

        missing_ingredients = (
            format_missing_ingredients(
                missing_raw
            )
        )

        # ----------------------------------------------------
        # Unsupported / uncertain items
        # ----------------------------------------------------

        unsupported_items: List[Dict[str, Any]] = []

        for item in missing_ingredients:

            status = item.get("status")

            if status == "unit_mismatch":
               unsupported_items.append(item)

        # ----------------------------------------------------
        # Status
        # ----------------------------------------------------

        if unsupported_items:
            status = "partial"
        else:
            status = "success"

        # ----------------------------------------------------
        # Final AgentResult
        # ----------------------------------------------------

        return {
            "agent": self.name,
            "status": status,
            "data": {
                "recipe_id": recipe_id,
                "required_ingredients": required_ingredients,
                "pantry_used": pantry_used,
                "missing_ingredients": missing_ingredients,
                "unsupported_items": unsupported_items,
            },
            "warnings": [],
            "errors": [],
        }