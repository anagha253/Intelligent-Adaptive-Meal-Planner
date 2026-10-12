
from src.agents.grocery_agent import GroceryAgent
from src.grocery.grocery_service import GroceryOption
from src.agents.contracts import normalize_agent_result


# ============================================================
# Fake Grocery Service
# ============================================================

class FakeGroceryService:
    """
    Test double for GroceryService.

    Matches the real get_grocery_list interface:
        get_grocery_list(items, recipe_id=None)
    """

    def __init__(self, options):
        self.options = options
        self.calls = 0
        self.last_recipe_id = None

    def get_grocery_list(self, items, recipe_id=None):
        self.calls += 1
        self.last_recipe_id = recipe_id
        return self.options


class FailingGroceryService:
    """
    Simulates an unexpected Grocery Service failure.
    """

    def get_grocery_list(self, items, recipe_id=None):
        raise RuntimeError("test grocery failure")


# ============================================================
# Test 1: All items priced
# ============================================================

def test_grocery_agent_all_items_priced():

    options = [
        GroceryOption(
            ingredient_id="ING01",
            ingredient_name="rice",
            required_quantity=300,
            required_unit="g",
            product_name="FairPrice Jasmine Rice",
            package_quantity=1,
            package_unit="kg",
            packages_needed=1,
            price_per_package=3.80,
            total_cost=3.80,
            currency="SGD",
            store="FairPrice",
            match_status="matched",
        ),
        GroceryOption(
            ingredient_id="ING02",
            ingredient_name="tofu",
            required_quantity=300,
            required_unit="g",
            product_name="Fortune Tofu",
            package_quantity=300,
            package_unit="g",
            packages_needed=1,
            price_per_package=2.50,
            total_cost=2.50,
            currency="SGD",
            store="FairPrice",
            match_status="matched",
        ),
    ]

    service = FakeGroceryService(options)
    agent = GroceryAgent(grocery_service=service)

    result = agent.run(
        recipe_id="R001",
        missing_ingredients=[
            {
                "ingredient_id": "ING01",
                "ingredient_name": "rice",
                "quantity": 300,
                "unit": "g",
            },
            {
                "ingredient_id": "ING02",
                "ingredient_name": "tofu",
                "quantity": 300,
                "unit": "g",
            },
        ],
    )

    assert result["agent"] == "grocery"
    assert result["status"] == "success"

    data = result["data"]

    assert data["known_cost"] == 6.30
    assert data["all_items_priced"] is True
    assert data["unpriced_items"] == []

    assert service.calls == 1
    assert service.last_recipe_id == "R001"


# ============================================================
# Test 2: Missing product price
# ============================================================

def test_grocery_agent_missing_price():

    options = [
        GroceryOption(
            ingredient_id="ING01",
            ingredient_name="rice",
            product_name="FairPrice Jasmine Rice",
            price_per_package=3.80,
            total_cost=3.80,
            currency="SGD",
            store="FairPrice",
            match_status="matched",
        ),
        GroceryOption(
            ingredient_id="ING02",
            ingredient_name="tofu",
            product_name=None,
            price_per_package=None,
            total_cost=None,
            match_status="no_match",
        ),
    ]

    agent = GroceryAgent(
        grocery_service=FakeGroceryService(options)
    )

    result = agent.run(
        recipe_id="R001",
        missing_ingredients=[
            {
                "ingredient_id": "ING01",
                "ingredient_name": "rice",
                "quantity": 300,
                "unit": "g",
            },
            {
                "ingredient_id": "ING02",
                "ingredient_name": "tofu",
                "quantity": 300,
                "unit": "g",
            },
        ],
    )

    assert result["status"] == "partial"

    data = result["data"]

    assert data["known_cost"] == 3.80
    assert data["all_items_priced"] is False
    assert "tofu" in data["unpriced_items"]

    assert data["projected_cost"] is None
    assert data["projected_cost_complete"] is False
    assert "tofu" in data["projection_missing"]


# ============================================================
# Test 3: No missing ingredients
# ============================================================

def test_grocery_agent_no_missing_ingredients():

    service = FakeGroceryService([])

    agent = GroceryAgent(grocery_service=service)

    result = agent.run(
        recipe_id="R001",
        missing_ingredients=[],
    )

    assert result["status"] == "success"

    data = result["data"]

    assert data["known_cost"] == 0.0
    assert data["all_items_priced"] is True
    assert data["unpriced_items"] == []

    assert data["projected_cost"] == 0.0
    assert data["projected_cost_complete"] is True


# ============================================================
# Test 4: Recipe ID required
# ============================================================

# ============================================================
# Test 4: Recipe ID required
# ============================================================

def test_grocery_agent_requires_recipe_id():

    agent = GroceryAgent(
        grocery_service=FakeGroceryService([])
    )

    result = agent.run(
        recipe_id="",
        missing_ingredients=[],
    )

    assert result["status"] == "failed"
    assert result["errors"]


# ============================================================
# Test 5: Multiple packages
# ============================================================

def test_grocery_agent_preserves_multiple_package_calculation():

    options = [
        GroceryOption(
            ingredient_id="ING01",
            ingredient_name="rice",
            required_quantity=1300,
            required_unit="g",
            product_name="FairPrice Jasmine Rice",
            package_quantity=1,
            package_unit="kg",
            packages_needed=2,
            price_per_package=3.80,
            total_cost=7.60,
            currency="SGD",
            store="FairPrice",
            match_status="matched",
        )
    ]

    service = FakeGroceryService(options)

    agent = GroceryAgent(grocery_service=service)

    result = agent.run(
        recipe_id="R001",
        missing_ingredients=[
            {
                "ingredient_id": "ING01",
                "ingredient_name": "rice",
                "quantity": 1300,
                "unit": "g",
            }
        ],
    )

    assert result["status"] == "success"

    data = result["data"]

    assert data["known_cost"] == 7.60

    item = data["items"][0]

    assert item["packages_needed"] == 2
    assert item["total_cost"] == 7.60
    assert item["match_status"] == "matched"

    assert service.last_recipe_id == "R001"


# ============================================================
# Test 6: Minimum retail package
# ============================================================

def test_grocery_agent_preserves_minimum_package_result():

    options = [
        GroceryOption(
            ingredient_id="ING02",
            ingredient_name="cheddar cheese",
            required_quantity=1.5,
            required_unit="tablespoon",
            product_name="Cheddar Cheese",
            package_quantity=500,
            package_unit="g",
            packages_needed=1,
            price_per_package=10.04,
            total_cost=10.04,
            currency="SGD",
            store="FairPrice",
            purchase_basis="minimum_retail_package",
            match_status="matched_minimum_package",
            note=(
                "Unit mismatch; using one retail "
                "package as the minimum purchase."
            ),
        )
    ]

    agent = GroceryAgent(
        grocery_service=FakeGroceryService(options)
    )

    result = agent.run(
        recipe_id="R001",
        missing_ingredients=[
            {
                "ingredient_id": "ING02",
                "ingredient_name": "cheddar cheese",
                "quantity": 1.5,
                "unit": "tablespoon",
            }
        ],
    )

    assert result["status"] == "success"

    data = result["data"]

    assert data["known_cost"] == 10.04

    item = data["items"][0]

    assert item["packages_needed"] == 1
    assert item["total_cost"] == 10.04
    assert item["match_status"] == "matched_minimum_package"
    assert item["purchase_basis"] == "minimum_retail_package"


# ============================================================
# Test 7: Missing product
# ============================================================

def test_grocery_agent_partial_when_product_missing():

    options = [
        GroceryOption(
            ingredient_id="ING01",
            ingredient_name="rice",
            required_quantity=300,
            required_unit="g",
            product_name="FairPrice Jasmine Rice",
            package_quantity=1,
            package_unit="kg",
            packages_needed=1,
            price_per_package=3.80,
            total_cost=3.80,
            currency="SGD",
            store="FairPrice",
            match_status="matched",
        ),
        GroceryOption(
            ingredient_id="ING02",
            ingredient_name="tofu",
            required_quantity=300,
            required_unit="g",
            product_name=None,
            price_per_package=None,
            total_cost=None,
            match_status="no_match",
        ),
    ]

    agent = GroceryAgent(
        grocery_service=FakeGroceryService(options)
    )

    result = agent.run(
        recipe_id="R001",
        missing_ingredients=[
            {
                "ingredient_id": "ING01",
                "ingredient_name": "rice",
                "quantity": 300,
                "unit": "g",
            },
            {
                "ingredient_id": "ING02",
                "ingredient_name": "tofu",
                "quantity": 300,
                "unit": "g",
            },
        ],
    )

    assert result["status"] == "partial"

    data = result["data"]

    assert data["known_cost"] == 3.80
    assert data["all_items_priced"] is False
    assert "tofu" in data["unpriced_items"]
    assert result["warnings"]


# ============================================================
# Test 8: Service failure
# ============================================================

def test_grocery_agent_handles_service_failure():

    agent = GroceryAgent(
        grocery_service=FailingGroceryService()
    )

    result = agent.run(
        recipe_id="R001",
        missing_ingredients=[
            {
                "ingredient_id": "ING01",
                "ingredient_name": "rice",
                "quantity": 300,
                "unit": "g",
            }
        ],
    )

    assert result["status"] == "failed"
    assert result["data"]["recipe_id"] == "R001"
    assert result["warnings"] == []
    assert result["errors"]

    assert (
        "Grocery lookup failed"
        in result["errors"][0]
    )


# ============================================================
# Test 9: Invalid input
# ============================================================

def test_grocery_agent_rejects_invalid_missing_ingredients():

    agent = GroceryAgent(
        grocery_service=FakeGroceryService([])
    )

    result = agent.run(
        recipe_id="R001",
        missing_ingredients="rice",
    )

    assert result["status"] == "failed"
    assert result["errors"]

    assert (
        "missing_ingredients"
        in result["errors"][0]
    )


# ============================================================
# Test 10: Manager-facing shared contract
# ============================================================

def test_grocery_agent_matches_shared_contract():

    options = [
        GroceryOption(
            ingredient_id="ING01",
            ingredient_name="rice",
            required_quantity=300,
            required_unit="g",
            product_name="FairPrice Jasmine Rice",
            package_quantity=500,
            package_unit="g",
            packages_needed=1,
            price_per_package=2.00,
            total_cost=2.00,
            currency="SGD",
            store="FairPrice",
            match_status="matched",
        )
    ]

    service = FakeGroceryService(options)

    agent = GroceryAgent(grocery_service=service)

    result = agent.run(
        recipe_id="R001",
        missing_ingredients=[
            {
                "ingredient_id": "ING01",
                "ingredient_name": "rice",
                "quantity": 300,
                "unit": "g",
            }
        ],
    )

    # This is how Manager normalizes agent results.
    normalized = normalize_agent_result(
        result,
        "grocery",
    )

    assert normalized["agent"] == "grocery"
    assert normalized["status"] == "success"

    assert isinstance(normalized["data"], dict)

    assert normalized["data"]["recipe_id"] == "R001"
    assert normalized["data"]["known_cost"] == 2.00
    assert normalized["data"]["all_items_priced"] is True
    assert normalized["data"]["unpriced_items"] == []

    assert normalized["warnings"] == []
    assert normalized["errors"] == []

    assert service.last_recipe_id == "R001"



def test_ollama_price_counts_as_regular_grocery_cost():
    from unittest.mock import Mock

    from src.agents.grocery_agent import GroceryAgent
    from src.grocery.grocery_service import GroceryOption

    service = Mock()

    service.get_grocery_list.return_value = [
        GroceryOption(
            ingredient_id="ING001",
            ingredient_name="butter lettuce",
            required_quantity=0.5,
            required_unit="head",
            product_name="Fresh Butterhead Lettuce",
            package_quantity=1,
            package_unit="head",
            packages_needed=1,
            price_per_package=1.5,
            estimated_total_cost=1.5,
            total_cost=None,
            purchase_basis="llm_estimated_package",
            match_status="estimated_no_retail_match",
        )
    ]

    agent = GroceryAgent(
        grocery_service=service
    )

    result = agent.run(
        recipe_id="R001",
        missing_ingredients=[
            {
                "ingredient_id": "ING001",
                "ingredient_name": "butter lettuce",
                "missing_quantity": 0.5,
                "unit": "head",
            }
        ],
        remaining_budget=50,
    )

    data = result["data"]

    assert result["status"] == "success"

    # Ollama and Tavily prices are treated equally.
    assert data["known_cost"] == 1.50
    assert data["projected_cost"] == 1.50

    assert data["all_items_priced"] is True
    assert data["unpriced_items"] == []

    assert data["budget_status"] == "pass"
    assert data["planning_budget_status"] == "pass"

    assert data["budget_after_purchase"] == 48.50

    assert data["items"][0]["price_source"] == "ollama"
