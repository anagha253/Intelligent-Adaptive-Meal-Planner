
from src.agents.grocery_agent import build_plan_grocery_basket


def test_unresolved_package_coverage_is_provisional():
    recipes = [
        {
            "recipe_id": "TEST001",
            "ingredients": [
                {
                    "ingredient_id": "ING_TEST",
                    "ingredient_name": "test herb",
                    "quantity": 30,
                    "unit": "g",
                }
            ],
        }
    ]

    catalog = [
        {
            "ingredient_id": "ING_TEST",
            "ingredient_name": "test herb",
            "package_quantity": 1,
            "package_unit": "bunch",
            "price": 2.50,
        }
    ]

    basket = build_plan_grocery_basket(
        recipe_requirements=recipes,
        inventory=[],
        product_catalog=catalog,
    )

    item = basket["items"][0]

    assert item["packages"] == 1

    assert item["package_conversion_status"] == "unresolved"

    assert item["quantity_coverage_verified"] is False

    assert item["leftover_quantity"] is None

    assert item["pricing_status"] == "estimated"

    assert item["purchase_cost"] is None

    assert item["estimated_purchase_cost"] == 2.50

    assert basket["projected_cost"] == 2.50

    assert basket["known_cost"] == 0
