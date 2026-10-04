"""tests/test_grocery_pipeline.py — offline tests for the grocery pipeline.

No real API calls: a FakeClient returns hand-written products, so these tests run
anywhere, any time, without an API key or search credits.

Run:
    python -m pytest tests/test_grocery_pipeline.py -v
"""

import pytest

from src.grocery.food_filter import check_match
from src.grocery.grocery_service import (
    GroceryService,
    basket_summary,
    grocery_summary,
)
from src.grocery.tavily_client import (
    SearchError,
    clean_title,
    extract_price,
    is_product_page,
    normalize,
    store_for,
)
from src.grocery.units import parse_package, to_base


# =====================================================================
# Test data
# =====================================================================

def product(pid, title, price, store="fairprice", **extra):
    """A product dict in the same shape TavilyGroceryClient.search() returns."""

    return {
        "product_id": pid,
        "title": title,
        "price": price,
        "currency": "SGD",
        "merchant_id": store,
        "store": store.replace("_", " ").title(),
        "url": f"https://www.{store}.com.sg/product/{pid}",
        "size_text": "",
        "availability": "local",
        "in_stock": None,
        "source_updated_at": None,
        "country_code": "SG",
        "region": "sg",
        **extra,
    }


FAKE_RESULTS = {
    "rice": [
        product(
            "r1",
            "Royal Umbrella Thai Hom Mali Rice 500g",
            2.00,
        ),
        product(
            "r2",
            "SongHe Jasmine Rice 1kg",
            3.50,
        ),
        product(
            "r3",
            "Tefal Rice Cooker 1.8L",
            89.00,
        ),
        product(
            "r4",
            "Rice Crackers Seaweed 100g",
            1.80,
        ),
    ],

    "chicken": [
        product(
            "c1",
            "Pedigree Adult Dry Dog Food Chicken 3kg",
            24.90,
        ),
        product(
            "c2",
            "Fresh Chicken Breast 500g",
            6.50,
        ),
        product(
            "c3",
            "Maggi Chicken Stock Cubes 60g",
            2.10,
        ),
    ],

    "tomato": [
        product(
            "t1",
            "Heinz Tomato Ketchup 500g",
            3.20,
        ),
        product(
            "t2",
            "Cherry Tomatoes 250g",
            2.95,
        ),
    ],

    "tomatoes": [
        product(
            "t3",
            "Tomatoes 1kg",
            3.80,
        ),
    ],

    "tofu": [
        product(
            "f1",
            "Tofu Press Stainless Steel",
            25.00,
        ),
        product(
            "f2",
            "Unicurd Firm Tofu 300g",
            1.20,
        ),

        # Deliberately invalid non-Singapore/non-FairPrice result.
        # This verifies that external results do not enter the basket.
        product(
            "f3",
            "Firm Tofu 300g",
            0.50,
            store="tofuworld",
            country_code="MY",
            region="my",
        ),
    ],

    "eggs": [
        product(
            "e1",
            "Pasar Fresh Eggs 10s",
            3.10,
        ),
    ],

    "brown rice": [
        product(
            "b1",
            "SongHe Brown Rice 500g",
            2.00,
        ),
    ],

    "milk": [
        product(
            "m1",
            "Meiji Fresh Milk 2L",
            6.20,
        ),
        product(
            "m2",
            "Farm Fresh Pure Fresh Milk 1L",
            3.45,
        ),
        product(
            "m3",
            "Fresh Milk 1L",
            3.30,
        ),
        product(
            "m4",
            "Fake Premium Milk 1L",
            3.40,
        ),
        product(
            "m5",
            "Dutch Lady Fresh Milk 1L",
            49.90,
        ),
    ],

    "garlic": [
        product(
            "g1",
            "China Garlic",
            1.50,
        ),
    ],

    "apple": [
        product(
            "a1",
            "Apple iPhone 16 128GB",
            99.00,
        ),
    ],
}


# =====================================================================
# Fake clients
# =====================================================================

class FakeClient:
    def __init__(self, fail=False):
        self.calls = 0
        self.fail = fail

    def search(self, query, limit=None):
        self.calls += 1

        if self.fail:
            raise SearchError(
                "Tavily search failed: timeout"
            )

        return FAKE_RESULTS.get(
            query.lower().strip(),
            [],
        )


class OneShot:
    """Client that returns the same fixed products for any query."""

    def __init__(self, products):
        self.products = products

    def search(self, query, limit=None):
        return self.products


@pytest.fixture
def service():
    return GroceryService(
        client=FakeClient(),
        verify_links=False,
    )


# =====================================================================
# Units
# =====================================================================

@pytest.mark.parametrize(
    "title,expected",
    [
        (
            "Farm Fresh Pure Fresh Milk 1L",
            (1000.0, "ml"),
        ),
        (
            "Royal Umbrella Rice 5kg",
            (5000.0, "g"),
        ),
        (
            "Coca-Cola 12 x 330ml",
            (3960.0, "ml"),
        ),
        (
            "Pasar Fresh Eggs 10s",
            (10.0, "pcs"),
        ),
        (
            "Nestle Noodles 5's",
            (5.0, "pcs"),
        ),
        (
            "China Garlic",
            None,
        ),
    ],
)
def test_parse_package(title, expected):
    assert parse_package(title) == expected


def test_to_base():
    assert to_base(
        1.5,
        "kg",
    ) == (1500.0, "g")

    assert to_base(
        2,
        "cups",
    ) == (480.0, "ml")

    assert to_base(
        3,
        "whatever",
    ) is None


# =====================================================================
# Food filter
# =====================================================================

@pytest.mark.parametrize(
    "ingredient,title",
    [
        (
            "chicken",
            "Pedigree Adult Dry Dog Food Chicken 3kg",
        ),
        (
            "chicken",
            "Pedigree Chicken & Vegetables 1.5kg",
        ),
        (
            "chicken",
            "Whiskas Chicken Pouch 85g",
        ),
        (
            "chicken",
            "Maggi Chicken Stock Cubes 60g",
        ),
        (
            "rice",
            "Tefal Rice Cooker 1.8L",
        ),
        (
            "rice",
            "Rice Crackers Seaweed 100g",
        ),
        (
            "tomato",
            "Heinz Tomato Ketchup 500g",
        ),
        (
            "tofu",
            "Tofu Press Stainless Steel",
        ),
        (
            "apple",
            "Apple iPhone 16 128GB",
        ),
        (
            "eggs",
            "Kinder Surprise Eggs 3s",
        ),
        (
            "milk",
            "Nestle Milk Chocolate 100g",
        ),
        (
            "milk",
            "Similac Infant Formula Milk 900g",
        ),
        (
            "milk",
            "Milk Hugs Oatmeal Bath Soak in Milk Scent",
        ),
    ],
)
def test_rejects_non_food_and_processed(
    ingredient,
    title,
):
    assert check_match(
        ingredient,
        title,
    )[0] is False


@pytest.mark.parametrize(
    "ingredient,title",
    [
        (
            "chicken",
            "Fresh Chicken Breast 500g",
        ),
        (
            "tomato",
            "Cherry Tomatoes 250g",
        ),
        (
            "eggs",
            "Pasar Fresh Eggs 10s",
        ),
        (
            "tomato sauce",
            "Heinz Tomato Sauce 300g",
        ),
    ],
)
def test_accepts_real_ingredient(
    ingredient,
    title,
):
    assert check_match(
        ingredient,
        title,
    )[0] is True


def test_generic_word_alone_is_not_enough():
    assert check_match(
        "duck breast",
        "Fresh Chicken Breast 500g",
    )[0] is False

    assert check_match(
        "coconut milk",
        "Fresh Milk 1L",
    )[0] is False


def test_prep_words_ignored():
    assert check_match(
        "3 garlic cloves, minced",
        "China Garlic",
    ) == (
        True,
        "exact",
    )

    assert check_match(
        "2 tbsp extra virgin olive oil",
        "Bertolli Extra Virgin Olive Oil 500ml",
    ) == (
        True,
        "exact",
    )


# =====================================================================
# Package maths
# =====================================================================

def test_task_example_700g_from_500g_packs(
    service,
):
    # Need 700g.
    # 500g @ $2.00 requires 2 packages = $4.00.

    opt = service.get_grocery_option(
        "brown rice",
        700,
        "g",
    )

    assert opt.packages_needed == 2
    assert opt.total_cost == 4.00

    # Do not prorate the retail package.
    assert opt.total_cost != 2.80


def test_picks_cheapest_total_purchase(
    service,
):
    # Need 700g:
    # 1kg @ $3.50 beats
    # 500g @ $2.00 x 2 = $4.00.

    opt = service.get_grocery_option(
        "rice",
        700,
        "g",
    )

    assert (
        opt.product_name
        == "SongHe Jasmine Rice 1kg"
    )

    assert opt.packages_needed == 1
    assert opt.total_cost == 3.50

    # Need 1100g:
    # 500g x3 = $6.00
    # 1kg x2 = $7.00.

    opt = service.get_grocery_option(
        "rice",
        1100,
        "g",
    )

    assert opt.packages_needed == 3
    assert opt.total_cost == 6.00


def test_count_units(service):
    opt = service.get_grocery_option(
        "eggs",
        12,
        "pcs",
    )

    assert opt.packages_needed == 2
    assert opt.total_cost == 6.20


def test_volume_units_and_price_outlier(
    service,
):
    # Need 1.5L.
    # 2L @ $6.20 x1 beats
    # 1L @ $3.30 x2.
    #
    # $49.90 milk should be dropped as an outlier.

    opt = service.get_grocery_option(
        "milk",
        1.5,
        "l",
    )

    assert (
        opt.product_name
        == "Meiji Fresh Milk 2L"
    )

    assert opt.packages_needed == 1
    assert opt.total_cost == 6.20


def test_package_size_from_page_text_when_title_has_none():
    item = product(
        "z1",
        "Unicurd Firm Tofu",
        1.20,
        size_text=(
            "Unicurd Firm Tofu "
            "300g $1.20"
        ),
    )

    opt = GroceryService(
        client=OneShot([item]),
        verify_links=False,
    ).get_grocery_option(
        "tofu",
        600,
        "g",
    )

    assert opt.package_quantity == 300
    assert opt.packages_needed == 2
    assert opt.total_cost == 2.40


# =====================================================================
# Products that must never reach the basket
# =====================================================================

def test_non_food_never_returned(service):
    chicken = service.get_grocery_option(
        "chicken",
        500,
        "g",
    )

    assert chicken.product_name is not None
    assert "Dog" not in chicken.product_name

    tofu = service.get_grocery_option(
        "tofu",
        300,
        "g",
    )

    assert (
        tofu.product_name
        == "Unicurd Firm Tofu 300g"
    )


def test_non_singapore_products_rejected(
    service,
):
    opt = service.get_grocery_option(
        "tofu",
        300,
        "g",
    )

    # The cheaper Malaysian listing must be excluded.
    assert opt.price_per_package == 1.20


def test_non_fairprice_store_rejected():
    # Deliberately inject a non-FairPrice product.
    # The FairPrice-only grocery service must reject it.

    item = product(
        "x9",
        "Milk Hugs Oatmeal Milk",
        24.0,
        store="babyluxe",
    )

    opt = GroceryService(
        client=OneShot([item]),
        verify_links=False,
    ).get_grocery_option(
        "milk",
        1,
        "l",
    )

    assert opt.product_name is None
    assert opt.match_status == "no_match"


def test_out_of_stock_rejected():
    item = product(
        "o1",
        "Meiji Fresh Milk 2L",
        6.20,
        in_stock=False,
    )

    opt = GroceryService(
        client=OneShot([item]),
        verify_links=False,
    ).get_grocery_option(
        "milk",
        1,
        "l",
    )

    assert opt.product_name is None


# =====================================================================
# Missing/no-match handling
# =====================================================================

def test_no_match_gives_na(service):
    opt = service.get_grocery_option(
        "apple",
        2,
        "pcs",
    )

    assert opt.match_status == "no_match"

    assert opt.product_name is None
    assert opt.price_per_package is None
    assert opt.total_cost is None


def test_unknown_ingredient_gives_na(
    service,
):
    opt = service.get_grocery_option(
        "dragonfruit",
        1,
        "pcs",
    )

    assert opt.product_name is None
    assert opt.price_per_package is None


def test_no_package_size_keeps_price_but_no_packages(
    service,
):
    opt = service.get_grocery_option(
        "garlic",
        50,
        "g",
    )

    assert (
        opt.match_status
        == "matched_no_quantity"
    )

    assert opt.price_per_package == 1.50
    assert opt.packages_needed is None
    assert opt.total_cost is None


def test_unit_mismatch(service):
    opt = service.get_grocery_option(
        "tofu",
        2,
        "pcs",
    )

    assert (
        opt.match_status
        == "matched_no_quantity"
    )

    assert opt.total_cost is None
    assert "unit mismatch" in opt.note


def test_search_error_gives_error_status():
    svc = GroceryService(
        client=FakeClient(fail=True),
        verify_links=False,
    )

    opt = svc.get_grocery_option(
        "rice",
        500,
        "g",
    )

    assert opt.match_status == "error"
    assert opt.price_per_package is None
    assert "search failed" in opt.note


# =====================================================================
# Recipe-style ingredient text
# =====================================================================

def test_recipe_text_with_amounts_and_prep_words(
    service,
):
    opt = service.get_grocery_option(
        "2 boneless skinless chicken breasts, diced",
        500,
        "g",
    )

    assert (
        opt.product_name
        == "Fresh Chicken Breast 500g"
    )

    assert opt.match_quality == "exact"
    assert opt.search_query == "chicken"


def test_partial_name_gives_approximate_match(
    service,
):
    opt = service.get_grocery_option(
        "1 cup fresh cherry tomatoes",
        500,
        "g",
    )

    assert (
        opt.product_name
        == "Tomatoes 1kg"
    )

    assert (
        opt.match_quality
        == "approximate"
    )

    assert "approximate" in opt.note


# =====================================================================
# Tavily page parsing — FairPrice only
# =====================================================================

def test_extract_price_skips_banners_and_unit_prices():
    assert extract_price(
        "Free delivery above $79. "
        "Meiji Fresh Milk 2L $6.20"
    ) == 6.20

    assert extract_price(
        "$0.35/100g Price $3.45"
    ) == 3.45

    assert extract_price(
        "S$ 12.90 each"
    ) == 12.90

    assert extract_price(
        "No price here"
    ) is None


def test_store_and_product_page_detection():
    url = (
        "https://www.fairprice.com.sg/"
        "product/meiji-fresh-milk-2l-13036390"
    )

    assert store_for(url) == (
        "fairprice.com.sg",
        "FairPrice",
    )

    # Any non-FairPrice source must be rejected.
    assert store_for(
        "https://www.amazon.com/dp/123"
    ) == (
        None,
        None,
    )

    assert is_product_page(url)

    assert not is_product_page(
        "https://www.fairprice.com.sg/"
        "search?query=milk"
    )

    assert not is_product_page(
        "https://www.fairprice.com.sg/"
        "category/milk"
    )


def test_clean_title():
    assert clean_title(
        "Buy Meiji Fresh Milk 2L "
        "| FairPrice Singapore"
    ) == "Meiji Fresh Milk 2L"

    assert clean_title(
        "FairPrice Basmati Rice "
        "| NTUC FairPrice"
    ) == "FairPrice Basmati Rice"


def test_normalize_tavily_result():
    r = {
        "title": (
            "Meiji Fresh Milk 2L "
            "| FairPrice Singapore"
        ),
        "url": (
            "https://www.fairprice.com.sg/"
            "product/meiji-fresh-milk-2l-13036390"
        ),
        "content": (
            "Meiji Fresh Milk 2L. "
            "$6.20. "
            "Product of Thailand."
        ),
        "raw_content": "",
    }

    p = normalize(r)

    assert (
        p["title"]
        == "Meiji Fresh Milk 2L"
    )

    assert p["price"] == 6.20
    assert p["store"] == "FairPrice"
    assert p["currency"] == "SGD"


def test_normalize_drops_pages_without_price_or_not_products():
    no_price = {
        "title": "Milk | FairPrice",
        "url": (
            "https://www.fairprice.com.sg/"
            "product/milk-1"
        ),
        "content": "Out of stock",
        "raw_content": "",
    }

    category = {
        "title": "Milk | FairPrice",
        "url": (
            "https://www.fairprice.com.sg/"
            "category/milk"
        ),
        "content": "$3.45 $4.10 $5.20",
        "raw_content": "",
    }

    foreign = {
        "title": "Milk",
        "url": (
            "https://www.walmart.com/"
            "ip/milk/123"
        ),
        "content": "$3.45",
    }

    assert normalize(no_price) is None
    assert normalize(category) is None
    assert normalize(foreign) is None


def test_out_of_stock_page_marked():
    r = {
        "title": (
            "Farm Fresh Milk 1L "
            "| FairPrice Singapore"
        ),
        "url": (
            "https://www.fairprice.com.sg/"
            "product/farm-fresh-milk-1l-12345678"
        ),
        "content": "Out of stock",
        "raw_content": (
            "Farm Fresh Milk 1L\n"
            "Price $3.45"
        ),
    }

    p = normalize(r)

    assert p is not None
    assert p["price"] == 3.45
    assert p["in_stock"] is False


# =====================================================================
# Contract, cache and basket
# =====================================================================

def test_output_contract_fields(service):
    d = service.search_grocery_product(
        "tofu"
    ).to_dict()

    for key in [
        "ingredient_id",
        "ingredient_name",
        "product_name",
        "package_quantity",
        "package_unit",
        "packages_needed",
        "price_per_package",
        "total_cost",
        "store",
        "source_url",
        "date_collected",
    ]:
        assert key in d


def test_cache_avoids_second_search():
    client = FakeClient()

    svc = GroceryService(
        client=client,
        verify_links=False,
    )

    svc.get_grocery_option(
        "rice",
        500,
        "g",
    )

    svc.get_grocery_option(
        "Rice",
        900,
        "g",
    )

    assert client.calls == 1


def test_grocery_list_and_basket(service):
    items = [
        {
            "ingredient_id": "I1",
            "ingredient_name": "rice",
            "quantity": 700,
            "unit": "g",
        },
        {
            "ingredient_id": "I2",
            "ingredient_name": "tofu",
            "quantity": 300,
            "unit": "g",
        },
        {
            "ingredient_id": "I3",
            "ingredient_name": "apple",
            "quantity": 2,
            "unit": "pcs",
        },
    ]

    summary = basket_summary(
        service.get_grocery_list(items)
    )

    assert summary["priced_items"] == 2

    assert (
        summary["estimated_total"]
        == 3.50 + 1.20
    )

    assert summary["missing_price"] == [
        "apple"
    ]


# =====================================================================
# Real Tavily result samples — FairPrice
# =====================================================================

REAL_BASMATI = {
    "url": (
        "https://www.fairprice.com.sg/"
        "product/fairprice-basmati-rice-5kg-13214051"
    ),
    "title": (
        "FairPrice Basmati Rice "
        "| NTUC FairPrice"
    ),
    "content": (
        "Help Centre\n\n"
        "Cart\n\n"
        "HomeRice, Noodles & Cooking Ingredients"
        "RiceWhite Rice\n\n"
        "campaign labelOffer\n\n"
        "$16.50\n\n"
        "$18.20\n\n"
        "Save $1.70Ends in 12h\n\n"
        "FairPrice Basmati Rice\n\n"
        "5kg|Brand:Fairprice\n\n"
        "## COUNTRY/PLACE OF ORIGIN\n\n"
        "India"
    ),
    "raw_content": None,
}


REAL_JASMINE = {
    "url": (
        "https://www.fairprice.com.sg/"
        "product/fairprice-jasmine-fragrant-rice-5kg-13086205"
    ),
    "title": (
        "FairPrice Jasmine Fragrant Rice "
        "| NTUC FairPrice"
    ),
    "content": (
        "Help Centre\n\n"
        "Cart\n\n"
        "HomeRice, Noodles & Cooking Ingredients"
        "RiceWhite Rice\n\n"
        "$9.20\n\n"
        "FairPrice Jasmine Fragrant Rice\n\n"
        "5kg|Brand:Fairprice\n\n"
        "## KEY INFORMATION"
    ),
    "raw_content": None,
}


REAL_CATEGORY = {
    "url": (
        "https://www.fairprice.com.sg/"
        "category/rice"
    ),
    "title": (
        "Shop Rice For Everyday Great Value "
        "| NTUC FairPrice"
    ),
    "content": (
        "$16.95$18.60\n\n"
        "SongHe AAA Thai Hom Mali Rice\n\n"
        "5kg"
    ),
    "raw_content": None,
}


def test_real_fairprice_offer_price_is_current_not_old_price():
    p = normalize(
        REAL_BASMATI
    )

    assert (
        p["title"]
        == "FairPrice Basmati Rice"
    )

    # Current offer price, not old crossed-out price.
    assert p["price"] == 16.50


def test_real_fairprice_regular_price():
    p = normalize(
        REAL_JASMINE
    )

    assert (
        p["title"]
        == "FairPrice Jasmine Fragrant Rice"
    )

    assert p["price"] == 9.20


def test_real_category_page_is_skipped():
    assert normalize(
        REAL_CATEGORY
    ) is None


def test_real_results_end_to_end():
    products = [
        p
        for p in (
            normalize(r)
            for r in (
                REAL_BASMATI,
                REAL_JASMINE,
                REAL_CATEGORY,
            )
        )
        if p
    ]

    opt = GroceryService(
        client=OneShot(products),
        verify_links=False,
    ).get_grocery_option(
        "rice",
        5,
        "kg",
    )

    assert (
        opt.product_name
        == "FairPrice Jasmine Fragrant Rice"
    )

    assert opt.package_quantity == 5
    assert opt.package_unit == "kg"

    assert opt.packages_needed == 1
    assert opt.total_cost == 9.20
    assert opt.store == "FairPrice"


# =====================================================================
# PantryService -> GroceryService integration
# =====================================================================

def test_grocery_service_accepts_pantry_grocery_list(
    service,
):
    grocery_list = {
        "rice": {
            "ingredient_id": "I1",
            "alias_name": "rice",
            "quantity": 700,
            "unit": "g",
        },

        "tofu": {
            "ingredient_id": "I2",
            "alias_name": "tofu",
            "quantity": 300,
            "unit": "g",
        },
    }

    options = service.get_grocery_list(
        grocery_list
    )

    assert len(options) == 2

    assert (
        options[0].ingredient_name
        == "rice"
    )

    assert (
        options[0].ingredient_id
        == "I1"
    )

    assert (
        options[1].ingredient_name
        == "tofu"
    )

    assert (
        options[1].ingredient_id
        == "I2"
    )


def test_grocery_summary_separates_results(
    service,
):
    grocery_list = {
        "rice": {
            "ingredient_id": "I1",
            "quantity": 700,
            "unit": "g",
        },

        "apple": {
            "ingredient_id": "I2",
            "quantity": 2,
            "unit": "pcs",
        },
    }

    options = service.get_grocery_list(
        grocery_list
    )

    summary = grocery_summary(
        options
    )

    assert (
        summary["items_requested"]
        == 2
    )

    assert (
        summary["products_priced"]
        == 1
    )

    assert (
        summary["products_missing"]
        == 1
    )

    assert (
        summary[
            "priced_products"
        ][0]["ingredient"]
        == "rice"
    )

    assert (
        summary[
            "missing_products"
        ][0]["ingredient"]
        == "apple"
    )