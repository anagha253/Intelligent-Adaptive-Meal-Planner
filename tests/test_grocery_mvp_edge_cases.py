
import pytest

from src.agents.grocery_agent import (
    aggregate_requirements,
    build_plan_grocery_basket,
)


def test_unresolved_units_do_not_crash():
    recipes = [
        {
            "recipe_id": "R1",
            "ingredients": [
                {
                    "ingredient_name": "mystery vegetable",
                    "quantity": 2,
                    "unit": "tablespoon",
                }
            ],
        },
        {
            "recipe_id": "R2",
            "ingredients": [
                {
                    "ingredient_name": "mystery vegetable",
                    "quantity": 1,
                    "unit": "count",
                }
            ],
        },
    ]

    aggregated = aggregate_requirements(recipes)

    assert len(aggregated) == 2
    assert all(
        item["normalization_status"] == "unresolved"
        for item in aggregated
    )


def test_missing_product_price_is_not_free():
    recipes = [
        {
            "recipe_id": "R1",
            "ingredients": [
                {
                    "ingredient_name": "rice",
                    "quantity": 500,
                    "unit": "g",
                }
            ],
        }
    ]

    catalog = [
        {
            "ingredient_name": "rice",
            "package_quantity": 1000,
            "package_unit": "g",
            "price": None,
        }
    ]

    basket = build_plan_grocery_basket(
        recipe_requirements=recipes,
        inventory=[],
        product_catalog=catalog,
    )

    assert basket["known_cost"] == 0
    assert basket["all_items_priced"] is False
    assert basket["projected_cost_complete"] is False
    assert "rice" in basket["unpriced_items"]


def test_estimated_carrot_not_verified():
    recipes = [
        {
            "recipe_id": "R1",
            "ingredients": [
                {
                    "ingredient_name": "carrot",
                    "quantity": 1,
                    "unit": "count",
                }
            ],
        }
    ]

    catalog = [
        {
            "ingredient_name": "carrot",
            "package_quantity": 500,
            "package_unit": "g",
            "price": 1.50,
        }
    ]

    basket = build_plan_grocery_basket(
        recipe_requirements=recipes,
        inventory=[],
        product_catalog=catalog,
    )

    assert basket["known_cost"] == 0
    assert basket["projected_cost"] == 1.50
    assert basket["all_items_priced"] is False
    assert basket["projected_cost_complete"] is True
    assert basket["items"][0]["conversion_status"] == "estimated"

def test_unresolved_units_not_counted_as_verified():
    recipes = [
        {
            "recipe_id": "R1",
            "ingredients": [
                {
                    "ingredient_name": "mystery vegetable",
                    "quantity": 2,
                    "unit": "tablespoon",
                }
            ],
        },
        {
            "recipe_id": "R2",
            "ingredients": [
                {
                    "ingredient_name": "mystery vegetable",
                    "quantity": 1,
                    "unit": "count",
                }
            ],
        },
    ]

    catalog = [
        {
            "ingredient_name": "mystery vegetable",
            "package_quantity": 500,
            "package_unit": "g",
            "price": 2.00,
        }
    ]

    basket = build_plan_grocery_basket(
        recipe_requirements=recipes,
        inventory=[],
        product_catalog=catalog,
    )

    assert basket["known_cost"] == 0
    assert basket["all_items_priced"] is False
    assert basket["projected_cost_complete"] is False
    assert basket["projected_cost"] is None

    assert len(basket["unresolved_requirements"]) == 2

    assert all(
        item["pricing_status"] == "unresolved_conversion"
        for item in basket["items"]
    )


def test_to_taste_requirement_is_preserved_separately():
    recipes = [
        {
            "recipe_id": "R1",
            "ingredients": [
                {
                    "ingredient_id": "ING3046",
                    "ingredient_name": "table salt",
                    "quantity": "required",
                    "unit": "to taste",
                }
            ],
        }
    ]

    basket = build_plan_grocery_basket(
        recipe_requirements=recipes,
        inventory=[],
        product_catalog=[],
    )

    assert len(basket["qualitative_requirements"]) == 1

    instruction = basket["qualitative_requirements"][0]
    assert instruction["ingredient_name"] == "table salt"
    assert instruction["quantity"] == "required"
    assert instruction["unit"] == "to taste"
    assert instruction["recipe_ids"] == ["R1"]

    # Qualitative instructions must not become numeric purchases.
    assert len(basket["items"]) == 1

    item = basket["items"][0]

    assert item["ingredient_id"] == "ING3046"
    assert item["name"] == "table salt"
    assert item["required_quantity"] is None
    assert item["required_unit"] == "to taste"
    assert item["purchase_basis"] == "qualitative_requirement"
    assert item["status"] == "quantity_unknown"
    assert item["packages"] is None
    assert item["purchase_cost"] is None
    assert item["estimated_purchase_cost"] is None
    assert item["quantity_coverage_verified"] is False

    # Grocery cost remains incomplete.
    assert basket["projected_cost_complete"] is False
    assert "table salt" in basket["unpriced_items"]
