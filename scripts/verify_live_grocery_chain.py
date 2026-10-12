
from src.agents.ingredient_agent import IngredientAgent
from src.agents.grocery_agent import GroceryAgent
from src.agents.contracts import normalize_agent_result
from src.grocery.ollama_fallback_service import (
    OllamaFallbackGroceryService,
)


def main():
    recipe_id = "R14336"
    remaining_budget = 50.0

    pantry = [
        {
            "ingredient_id": "ING0614",
            "ingredient_name": "cauliflower",
            "quantity": 1,
            "unit": "head",
        },
        {
            "ingredient_id": "ING3248",
            "ingredient_name": "sour cream",
            "quantity": 2,
            "unit": "tablespoon",
        },
    ]

    print("=" * 60)
    print("LIVE INGREDIENT -> GROCERY -> BUDGET TEST")
    print("=" * 60)

    ingredient_agent = IngredientAgent()

    ingredient_result = normalize_agent_result(
        ingredient_agent.run(
            recipe_id=recipe_id,
            pantry=pantry,
        ),
        "ingredient",
    )

    print("\nIngredient Agent:", ingredient_result["status"])

    if ingredient_result["status"] == "failed":
        print("Errors:", ingredient_result["errors"])
        return

    missing = ingredient_result["data"].get(
        "missing_ingredients", []
    )

    print("Missing ingredients:", len(missing))

    for item in missing:
        print(
            "-",
            item.get("ingredient_name"),
            item.get("quantity"),
            item.get("unit"),
        )

    grocery_agent = GroceryAgent(
        grocery_service=OllamaFallbackGroceryService()
    )

    grocery_result = normalize_agent_result(
        grocery_agent.run(
            recipe_id=recipe_id,
            missing_ingredients=missing,
            remaining_budget=remaining_budget,
        ),
        "grocery",
    )

    data = grocery_result["data"]

    print("\n" + "=" * 60)
    print("LIVE GROCERY AGENT RESULT")
    print("=" * 60)

    print("Status:", grocery_result["status"])
    print("Known cost:", data.get("known_cost"))
    
    print("Projected cost:", data.get("projected_cost"))
    print(
        "Projection complete:",
        data.get("projected_cost_complete"),
    )
    print(
        "Projected items:",
        data.get("projected_items"),
    )
    print(
        "Projection missing:",
        data.get("projection_missing"),
    )

    print("All items priced:", data.get("all_items_priced"))
    print("Unpriced items:", data.get("unpriced_items"))
    print("Budget status:", data.get("budget_status"))
    
    print(
        "Estimated budget status:",
        data.get("estimated_budget_status"),
    )
    print(
        "Estimated budget remaining:",
        data.get("estimated_budget_after_purchase"),
    )
    print(
        "Estimated budget reason:",
        data.get("estimated_budget_reason"),
    )

    print(
        "Budget after purchase:",
        data.get("budget_after_purchase"),
    )

    print("\nGrocery items:")

    for item in data.get("items", []):
        print("\nIngredient:", item.get("ingredient"))
        print("Product:", item.get("product_name"))
        print("Match:", item.get("match_quality"))
        print("Package:", item.get("package_quantity"), item.get("package_unit"))
        print("Purchase basis:", item.get("purchase_basis"))
        print("Minimum package cost:", item.get("minimum_package_cost"))
        print("Estimated cost:", item.get("estimated_total_cost"))
        print("Verified/assumed total:", item.get("total_cost"))
        print("Purchase channel:", item.get("purchase_channel"))
        print("URL:", item.get("source_url"))

    print("\nWarnings:", grocery_result["warnings"])
    print("Errors:", grocery_result["errors"])


if __name__ == "__main__":
    main()
