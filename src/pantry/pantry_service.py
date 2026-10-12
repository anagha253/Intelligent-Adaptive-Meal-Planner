import sys
import os
import json
import math
from pathlib import Path

sys.path.append(
    os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..")
    )
)

import scripts.mapping_retrieval_query


BASE_DIR = Path(__file__).resolve().parent.parent.parent
PANTRY_FILE = BASE_DIR / "data" / "sample" / "pantry.json"


def normalize_name(name):
    """Normalize ingredient names for comparison."""
    return str(name).strip().lower()


def normalize_unit(unit):
    """Normalize unit formatting only."""
    return str(unit).strip().lower()


# def is_unknown_quantity(quantity):
#     """Check whether quantity is missing/NaN."""
#     if quantity is None:
#         return True

#     try:
#         return math.isnan(float(quantity))
#     except (TypeError, ValueError):
#         return False
def is_unknown_quantity(quantity):
    """Check whether quantity is unknown or nonnumeric."""

    if quantity is None:
        return True

    if isinstance(quantity, str):
        if quantity.strip().lower() in {
            "",
            "unknown",
            "required",
            "to taste",
            "as needed",
            "none",
            "nan",
        }:
            return True

    try:
        return math.isnan(float(quantity))
    except (TypeError, ValueError):
        return True

def load_pantry():
    """Load pantry data from JSON."""

    if not PANTRY_FILE.exists():
        raise FileNotFoundError(
            f"Pantry file not found: {PANTRY_FILE}"
        )

    with open(PANTRY_FILE, "r") as file:
        return json.load(file)


def examine_pantry(pantry_data):
    """
    Convert pantry JSON into a dictionary indexed
    by normalized ingredient name.
    """

    if not isinstance(pantry_data, dict):
        raise ValueError("Pantry data should be a dictionary.")

    if "items" not in pantry_data:
        raise ValueError("Pantry data must contain an 'items' list.")

    return {
        normalize_name(item["name"]): {
            "quantity": item["quantity"],
            "unit": normalize_unit(item["unit"])
        }
        for item in pantry_data["items"]
    }


def fetch_recipe_ingredients(recipe_id):
    """
    Retrieve recipe ingredients from the mapping KB.

    Keeps ingredient ID and aliases so they can later
    be used by the grocery/product search layer.
    """

    df = scripts.mapping_retrieval_query.get_recipe_ingredients(
        recipe_id
    )

    if df.empty:
        return {}

    return {
        normalize_name(row["ingredient_name"]): {
            "ingredient_id": row["ingredient_id"],
            "alias_name": row["alias_name"],
            "quantity": row["quantity_per_serving"],
            "unit": normalize_unit(row["unit"])
        }
        for _, row in df.iterrows()
    }


def filter_ingredient_list(pantry_data, ingredient_names):
    """
    Compare recipe requirements with pantry contents.

    Returns only ingredients that still need
    to be purchased.
    """

    if not isinstance(pantry_data, dict):
        raise ValueError(
            "Pantry data should be a dictionary."
        )

    if not isinstance(ingredient_names, dict):
        raise ValueError(
            "Ingredient names should be a dictionary."
        )

    grocery_list = {}

    ingredients_not_in_pantry = (
        ingredient_names.keys() - pantry_data.keys()
    )

    ingredients_in_pantry = (
        ingredient_names.keys() & pantry_data.keys()
    )

    # -----------------------------------------
    # Ingredients completely missing
    # -----------------------------------------

    for ingredient in ingredients_not_in_pantry:

        ingredient_data = ingredient_names[ingredient]

        required = ingredient_data["quantity"]
        required_unit = ingredient_data["unit"]

        grocery_item = {
            "ingredient_id": ingredient_data["ingredient_id"],
            "alias_name": ingredient_data["alias_name"],
            "quantity": required,
            "unit": required_unit
        }

        if is_unknown_quantity(required):
            grocery_item["quantity"] = None
            grocery_item["status"] = "quantity_unknown"

        grocery_list[ingredient] = grocery_item

    # -----------------------------------------
    # Ingredients already present in pantry
    # -----------------------------------------

    for ingredient in ingredients_in_pantry:

        ingredient_data = ingredient_names[ingredient]

        required = ingredient_data["quantity"]
        required_unit = ingredient_data["unit"]

        available = pantry_data[ingredient]["quantity"]
        pantry_unit = pantry_data[ingredient]["unit"]

        grocery_item = {
            "ingredient_id": ingredient_data["ingredient_id"],
            "alias_name": ingredient_data["alias_name"],
            "quantity": required,
            "unit": required_unit
        }

        # Unknown recipe quantity
        if is_unknown_quantity(required):
            grocery_item["quantity"] = None
            grocery_item["status"] = "quantity_unknown"

            grocery_list[ingredient] = grocery_item
            continue
        if is_unknown_quantity(available):
            grocery_item["status"] = "quantity_unknown"
            grocery_list[ingredient] = grocery_item
            continue
        # Unit mismatch
        # Member 3's normalization should eventually
        # resolve compatible unit conversions.
        if required_unit != pantry_unit:
            grocery_item["status"] = "unit_mismatch"

            grocery_list[ingredient] = grocery_item
            continue

        # Calculate how much is still required
        missing_quantity = max(
            float(required) - float(available),
            0
        )

        # Only add ingredients that need purchasing
        if missing_quantity > 0:
            grocery_item["quantity"] = missing_quantity
            grocery_list[ingredient] = grocery_item

    return grocery_list


if __name__ == "__main__":

    recipe_id = "R03943"

    ingredients = fetch_recipe_ingredients(recipe_id)
    pantry = examine_pantry(load_pantry())

    grocery_list = filter_ingredient_list(
        pantry,
        ingredients
    )

    print(f"\nRecipe: {recipe_id}")

    print("\nRequired Ingredients:")
    print(ingredients)

    print("\nPantry:")
    print(pantry)

    print("\nFinal Grocery List:")
    print(grocery_list)