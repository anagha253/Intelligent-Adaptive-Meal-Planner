"""src/grocery/grocery_service.py

Turn grocery ingredients into buyable FairPrice grocery options.

The service:
- accepts individual ingredients or a grocery list
- accepts the grocery-list dictionary produced by PantryService
- searches FairPrice through Tavily
- filters unsafe/unrelated products
- calculates package quantities and purchase costs where possible
- keeps missing products/prices as None (NA)
- provides a user-facing grocery summary

Run dynamically with:

    python -m src.grocery.grocery_service

The development runner obtains the grocery list from PantryService,
then sends it directly into GroceryService.
"""

import json
import math
import re
import statistics
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

import requests

from src.grocery.food_filter import (
    check_match,
    search_queries,
    words,
)
from src.grocery.tavily_client import (
    SearchError,
    TavilyGroceryClient,
)
from src.grocery.units import (
    parse_package,
    pretty,
    to_base,
)


# ---------------------------------------------------------------------
# Grocery source
# ---------------------------------------------------------------------

GROCERY_STORE = "fairprice"

MAX_ITEM_PRICE = 100.0

PRICE_OUTLIER_FACTOR = 3.0


# ---------------------------------------------------------------------
# Known invalid FairPrice URL patterns
# ---------------------------------------------------------------------

BAD_URL_PATTERNS = [
    (
        re.compile(
            r"fairprice\.com\.sg/product/.*-ifp-[a-z]+-\d+$",
            re.IGNORECASE,
        ),
        "known fake FairPrice listing pattern (pages return 404)",
    ),
]


_SOFT_404 = re.compile(
    r"<title>[^<]*(404|not found|can.t (be )?found)[^<]*</title>",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

def _now() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat(
        timespec="seconds"
    )


# ---------------------------------------------------------------------
# Grocery output contract
# ---------------------------------------------------------------------

@dataclass
class GroceryOption:
    ingredient_id: str | None
    ingredient_name: str

    required_quantity: float | None = None
    required_unit: str | None = None

    product_name: str | None = None

    package_quantity: float | None = None
    package_unit: str | None = None
    packages_needed: int | None = None

    price_per_package: float | None = None
    total_cost: float | None = None

    currency: str | None = None
    store: str | None = None

    source_url: str | None = None
    source_updated_at: str | None = None

    date_collected: str = field(
        default_factory=_now
    )

    # matched | matched_no_quantity | no_match | error
    match_status: str = "no_match"

    # exact | approximate
    match_quality: str | None = None

    # Query that produced the selected result
    search_query: str | None = None

    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------
# Grocery service
# ---------------------------------------------------------------------

class GroceryService:

    def __init__(
        self,
        client: TavilyGroceryClient | None = None,
        verify_links: bool = False,
        cache_ttl_hours: float = 6.0,
    ):
        self.client = (
            client
            or TavilyGroceryClient()
        )

        self.verify_links = verify_links

        self.cache_ttl = (
            cache_ttl_hours * 3600
        )

        self._search_cache: dict[
            str,
            tuple[float, list[dict]],
        ] = {}

        self._link_cache: dict[
            str,
            bool,
        ] = {}

        self._http = requests.Session()

        self._http.headers[
            "User-Agent"
        ] = (
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36"
        )

    # -----------------------------------------------------------------
    # Search with cache
    # -----------------------------------------------------------------

    def _search(
        self,
        ingredient: str,
    ) -> list[dict]:

        key = " ".join(
            words(ingredient)
        )

        hit = self._search_cache.get(
            key
        )

        if (
            hit
            and
            time.time() - hit[0]
            < self.cache_ttl
        ):
            return hit[1]

        products = self.client.search(
            ingredient
        )

        self._search_cache[key] = (
            time.time(),
            products,
        )

        return products

    # -----------------------------------------------------------------
    # FairPrice validation
    # -----------------------------------------------------------------

    @staticmethod
    def _is_fairprice_product(
        product: dict,
    ) -> bool:
        """
        Confirm that a result belongs to FairPrice.

        Tavily is already restricted to FairPrice, but this check
        prevents unexpected or manually supplied results from another
        retailer from entering the grocery results.
        """

        text = (
            f"{product.get('store', '')} "
            f"{product.get('merchant_id', '')} "
            f"{product.get('url', '')}"
        ).lower()

        return (
            GROCERY_STORE in text
        )

    # -----------------------------------------------------------------
    # Filter search results
    # -----------------------------------------------------------------

    def _filter(
        self,
        ingredient: str,
        products: list[dict],
    ) -> tuple[list[dict], Counter]:

        valid = []
        rejected = Counter()

        for product in products:

            # ---------------------------------------------------------
            # Singapore only
            # ---------------------------------------------------------

            if product.get(
                "country_code"
            ) not in (
                None,
                "SG",
            ):
                rejected[
                    "not sold in Singapore"
                ] += 1
                continue

            if product.get(
                "region"
            ) not in (
                None,
                "sg",
            ):
                rejected[
                    "not sold in Singapore"
                ] += 1
                continue

            # ---------------------------------------------------------
            # SGD only
            # ---------------------------------------------------------

            if product.get(
                "currency"
            ) != "SGD":
                rejected[
                    "not SGD"
                ] += 1
                continue

            # ---------------------------------------------------------
            # Out-of-stock products are not usable
            # ---------------------------------------------------------

            if product.get(
                "in_stock"
            ) is False:
                rejected[
                    "out of stock"
                ] += 1
                continue

            # ---------------------------------------------------------
            # Local availability only
            # ---------------------------------------------------------

            if product.get(
                "availability"
            ) not in (
                None,
                "local",
            ):
                rejected[
                    f"availability="
                    f"{product.get('availability')}"
                ] += 1
                continue

            # ---------------------------------------------------------
            # Valid numeric price
            # ---------------------------------------------------------

            price = product.get(
                "price"
            )

            if price is None:
                rejected[
                    "missing price"
                ] += 1
                continue

            if not isinstance(
                price,
                (int, float),
            ):
                rejected[
                    "invalid price"
                ] += 1
                continue

            if price <= 0:
                rejected[
                    "invalid price"
                ] += 1
                continue

            if price > MAX_ITEM_PRICE:
                rejected[
                    "price too high for groceries"
                ] += 1
                continue

            # ---------------------------------------------------------
            # FairPrice only
            # ---------------------------------------------------------

            if not self._is_fairprice_product(
                product
            ):
                rejected[
                    "not FairPrice"
                ] += 1
                continue

            # ---------------------------------------------------------
            # Known invalid URLs
            # ---------------------------------------------------------

            bad_reason = None

            for regex, reason in (
                BAD_URL_PATTERNS
            ):
                if regex.search(
                    product.get(
                        "url"
                    ) or ""
                ):
                    bad_reason = reason
                    break

            if bad_reason:
                rejected[
                    bad_reason
                ] += 1
                continue

            # ---------------------------------------------------------
            # Ingredient/product relevance
            # ---------------------------------------------------------

            ok, quality = check_match(
                ingredient,
                product.get(
                    "title"
                ) or "",
            )

            if not ok:
                rejected[
                    quality
                ] += 1
                continue

            # ---------------------------------------------------------
            # Package size
            # ---------------------------------------------------------

            package = (
                parse_package(
                    product.get(
                        "title"
                    ) or ""
                )
                or
                parse_package(
                    product.get(
                        "size_text"
                    ) or ""
                )
            )

            valid.append(
                {
                    **product,
                    "match": quality,
                    "package": package,
                }
            )

        return (
            self._drop_price_outliers(
                valid,
                rejected,
            ),
            rejected,
        )

    # -----------------------------------------------------------------
    # Remove suspicious price outliers
    # -----------------------------------------------------------------

    @staticmethod
    def _drop_price_outliers(
        valid: list[dict],
        rejected: Counter,
    ) -> list[dict]:

        unit_prices = {
            id(product):
                product["price"]
                / product["package"][0]

            for product in valid

            if (
                product.get(
                    "package"
                )
                and
                product["package"][0] > 0
            )
        }

        # Need at least three comparable products
        # before applying median-based outlier removal.
        if len(
            unit_prices
        ) < 3:
            return valid

        median = statistics.median(
            unit_prices.values()
        )

        kept = []

        for product in valid:

            product_id = id(
                product
            )

            if (
                product_id
                in unit_prices
                and
                unit_prices[
                    product_id
                ]
                >
                PRICE_OUTLIER_FACTOR
                * median
            ):
                rejected[
                    "price outlier"
                ] += 1

            else:
                kept.append(
                    product
                )

        return kept

    # -----------------------------------------------------------------
    # Candidate quality
    # -----------------------------------------------------------------

    @staticmethod
    def _quality(
        product: dict,
    ) -> int:

        score = 0

        if (
            GroceryService
            ._is_fairprice_product(
                product
            )
        ):
            score += 2

        if product.get(
            "source_updated_at"
        ):
            score += 1

        if product.get(
            "package"
        ):
            score += 1

        return score

    # -----------------------------------------------------------------
    # Rank candidate products
    # -----------------------------------------------------------------

    def _rank(
        self,
        valid: list[dict],
        need: tuple[
            float,
            str,
        ] | None,
    ) -> list[dict]:

        for product in valid:

            product[
                "packages"
            ] = None

            product[
                "total"
            ] = None

            package = product.get(
                "package"
            )

            # ---------------------------------------------------------
            # Package calculation only when units are compatible
            # ---------------------------------------------------------

            if (
                need
                and
                package
                and
                package[1]
                == need[1]
            ):

                product[
                    "packages"
                ] = max(
                    1,
                    math.ceil(
                        need[0]
                        / package[0]
                        - 1e-9
                    ),
                )

                product[
                    "total"
                ] = round(
                    product[
                        "packages"
                    ]
                    * product[
                        "price"
                    ],
                    2,
                )

        def exact_first(
            product: dict,
        ) -> int:

            return (
                0
                if product[
                    "match"
                ] == "exact"
                else 1
            )

        # -------------------------------------------------------------
        # Products where purchase cost can be calculated
        # -------------------------------------------------------------

        priced = sorted(
            (
                product
                for product
                in valid
                if product[
                    "total"
                ] is not None
            ),
            key=lambda product: (
                exact_first(
                    product
                ),
                product[
                    "total"
                ],
                -self._quality(
                    product
                ),
            ),
        )

        # -------------------------------------------------------------
        # Products where package math is incomplete
        # -------------------------------------------------------------

        others = sorted(
            (
                product
                for product
                in valid
                if product[
                    "total"
                ] is None
            ),
            key=lambda product: (
                exact_first(
                    product
                ),
                -self._quality(
                    product
                ),
                product[
                    "price"
                ],
            ),
        )

        # Exact matches stay ahead of approximate matches.
        return sorted(
            priced + others,
            key=exact_first,
        )

    # -----------------------------------------------------------------
    # Optional product-link verification
    # -----------------------------------------------------------------

    def _link_ok(
        self,
        url: str | None,
    ) -> bool:

        if not url:
            return False

        if (
            url
            not in self._link_cache
        ):

            try:
                response = (
                    self._http.get(
                        url,
                        timeout=10,
                        allow_redirects=True,
                    )
                )

                gone = (
                    response.status_code
                    in (
                        404,
                        410,
                    )
                    or (
                        response.status_code
                        < 400
                        and
                        _SOFT_404.search(
                            response.text[
                                :50_000
                            ]
                        )
                    )
                )

                self._link_cache[
                    url
                ] = not gone

            except (
                requests
                .RequestException
            ):
                # A failed automated request does not prove
                # that the FairPrice page is invalid.
                self._link_cache[
                    url
                ] = True

        return self._link_cache[
            url
        ]

    # -----------------------------------------------------------------
    # Search ingredient fallbacks
    # -----------------------------------------------------------------

    def _find_candidates(
        self,
        ingredient: str,
        need: tuple[
            float,
            str,
        ] | None = None,
    ) -> tuple[
        list[dict],
        Counter,
        int,
        str | None,
    ]:

        all_valid = {}
        rejected = Counter()

        n_results = 0
        used_query = None

        for query in search_queries(
            ingredient
        ):

            products = self._search(
                query
            )

            n_results += len(
                products
            )

            (
                valid,
                rejected_here,
            ) = self._filter(
                ingredient,
                products,
            )

            rejected.update(
                rejected_here
            )

            for product in valid:

                all_valid.setdefault(
                    product[
                        "product_id"
                    ],
                    product,
                )

            if (
                valid
                and
                used_query is None
            ):
                used_query = query

            # ---------------------------------------------------------
            # Stop only when an exact useful result has been found.
            # ---------------------------------------------------------

            if need is None:

                if any(
                    product[
                        "match"
                    ] == "exact"
                    for product
                    in valid
                ):
                    break

            else:

                compatible_exact = any(
                    product[
                        "match"
                    ] == "exact"
                    and
                    product.get(
                        "package"
                    ) is not None
                    and
                    product[
                        "package"
                    ][1]
                    == need[1]

                    for product
                    in valid
                )

                if compatible_exact:
                    break

        return (
            list(
                all_valid.values()
            ),
            rejected,
            n_results,
            used_query,
        )

    # -----------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------

    def get_grocery_option(
        self,
        ingredient_name: str,
        required_quantity: float | None = None,
        unit: str | None = None,
        ingredient_id: str | None = None,
    ) -> GroceryOption:

        option = GroceryOption(
            ingredient_id=ingredient_id,
            ingredient_name=ingredient_name,
            required_quantity=required_quantity,
            required_unit=unit,
        )

        # -------------------------------------------------------------
        # Convert required quantity to base unit
        # -------------------------------------------------------------

        need = None

        if (
            required_quantity
            is not None
            and
            unit
        ):

            need = to_base(
                required_quantity,
                unit,
            )

            if need is None:
                option.note = (
                    f"unknown unit "
                    f"'{unit}'. "
                )

        # -------------------------------------------------------------
        # Search/filter products
        # -------------------------------------------------------------

        try:

            (
                valid,
                rejected,
                n_results,
                used_query,
            ) = self._find_candidates(
                ingredient_name,
                need,
            )

        except SearchError as exc:

            option.match_status = (
                "error"
            )

            option.note += (
                f"search failed: "
                f"{exc}"
            )

            return option

        # -------------------------------------------------------------
        # No reliable product
        # -------------------------------------------------------------

        if not valid:

            reasons = ", ".join(
                f"{reason} ({count})"
                for reason, count
                in rejected.most_common(
                    3
                )
            )

            if not reasons:
                reasons = (
                    "no search results"
                )

            option.note += (
                f"no reliable match "
                f"among {n_results} "
                f"results: {reasons}"
            )

            # Product and price remain None.
            return option

        option.search_query = (
            used_query
        )

        # -------------------------------------------------------------
        # Select best product
        # -------------------------------------------------------------

        broken = 0

        for product in self._rank(
            valid,
            need,
        )[:5]:

            if (
                self.verify_links
                and
                not self._link_ok(
                    product.get(
                        "url"
                    )
                )
            ):
                broken += 1
                continue

            option.product_name = (
                product[
                    "title"
                ]
            )

            option.price_per_package = (
                product[
                    "price"
                ]
            )

            option.currency = (
                product[
                    "currency"
                ]
            )

            option.store = (
                product[
                    "store"
                ]
            )

            option.source_url = (
                product[
                    "url"
                ]
            )

            option.source_updated_at = (
                product.get(
                    "source_updated_at"
                )
            )

            option.match_quality = (
                product[
                    "match"
                ]
            )

            if (
                product[
                    "match"
                ]
                == "approximate"
            ):
                option.note += (
                    "approximate match - "
                    "check the product suits "
                    "the recipe. "
                )

            package = product.get(
                "package"
            )

            if package:

                (
                    option.package_quantity,
                    option.package_unit,
                ) = pretty(
                    *package
                )

            # ---------------------------------------------------------
            # Complete purchase calculation
            # ---------------------------------------------------------

            if (
                product[
                    "total"
                ]
                is not None
            ):

                option.packages_needed = (
                    product[
                        "packages"
                    ]
                )

                option.total_cost = (
                    product[
                        "total"
                    ]
                )

                option.match_status = (
                    "matched"
                )

            # ---------------------------------------------------------
            # Product/price found but purchase calculation incomplete
            # ---------------------------------------------------------

            else:

                option.match_status = (
                    "matched_no_quantity"
                )

                if need is None:

                    if (
                        required_quantity
                        is None
                        or
                        not unit
                    ):

                        option.note += (
                            "no required quantity "
                            "given; packages not "
                            "calculated."
                        )

                    else:

                        option.note += (
                            "required quantity "
                            "could not be converted; "
                            "packages not calculated."
                        )

                elif not package:

                    option.note += (
                        "package size not found "
                        "on the product page; "
                        "packages not calculated."
                    )

                else:

                    option.note += (
                        f"unit mismatch "
                        f"(need {need[1]}, "
                        f"package in "
                        f"{package[1]}); "
                        f"packages not "
                        f"calculated."
                    )

            if broken:

                option.note += (
                    f" skipped {broken} "
                    f"product(s) with "
                    f"broken links."
                )

            option.note = (
                option.note.strip()
            )

            return option

        option.note += (
            f"all top matches had "
            f"broken product links "
            f"({broken})."
        )

        return option

    # -----------------------------------------------------------------
    # Single ingredient convenience method
    # -----------------------------------------------------------------

    def search_grocery_product(
        self,
        ingredient_name: str,
    ) -> GroceryOption:

        return self.get_grocery_option(
            ingredient_name
        )

    # -----------------------------------------------------------------
    # Grocery list
    # -----------------------------------------------------------------

    def get_grocery_list(
        self,
        items: list[dict] | dict,
    ) -> list[GroceryOption]:
        """
        Price all ingredients that need to be purchased.

        This directly accepts the dictionary produced by:

            pantry_service.filter_ingredient_list()

        Example:

            {
                "sour cream": {
                    "ingredient_id": "ING3248",
                    "alias_name": "...",
                    "quantity": "1.5",
                    "unit": "tablespoon"
                },

                "cilantro": {
                    "ingredient_id": "ING0870",
                    "alias_name": "...",
                    "quantity": "1.0",
                    "unit": "sprig"
                }
            }

        The original list format remains supported for compatibility
        with existing callers and tests.
        """

        options = []

        # -------------------------------------------------------------
        # PantryService dictionary format
        # -------------------------------------------------------------

        if isinstance(
            items,
            dict,
        ):

            for (
                ingredient_name,
                item,
            ) in items.items():

                option = (
                    self
                    .get_grocery_option(
                        ingredient_name=(
                            ingredient_name
                        ),
                        required_quantity=(
                            item.get(
                                "quantity"
                            )
                        ),
                        unit=(
                            item.get(
                                "unit"
                            )
                        ),
                        ingredient_id=(
                            item.get(
                                "ingredient_id"
                            )
                        ),
                    )
                )

                options.append(
                    option
                )

            return options

        # -------------------------------------------------------------
        # Existing list format
        # -------------------------------------------------------------

        if isinstance(
            items,
            list,
        ):

            for item in items:

                option = (
                    self
                    .get_grocery_option(
                        ingredient_name=(
                            item[
                                "ingredient_name"
                            ]
                        ),
                        required_quantity=(
                            item.get(
                                "quantity"
                            )
                        ),
                        unit=(
                            item.get(
                                "unit"
                            )
                        ),
                        ingredient_id=(
                            item.get(
                                "ingredient_id"
                            )
                        ),
                    )
                )

                options.append(
                    option
                )

            return options

        raise TypeError(
            "items must be either "
            "a pantry grocery-list "
            "dictionary or a list "
            "of grocery item "
            "dictionaries"
        )


# ---------------------------------------------------------------------
# Existing basket summary
# ---------------------------------------------------------------------

def basket_summary(
    options: list[
        GroceryOption
    ],
) -> dict:
    """
    Summarise grocery purchase costs.

    This function is retained for compatibility with existing
    project code/tests.
    """

    priced = [
        option
        for option
        in options
        if option.total_cost
        is not None
    ]

    missing_price = [
        option.ingredient_name
        for option
        in options
        if option.price_per_package
        is None
    ]

    missing_package_calc = [
        option.ingredient_name
        for option
        in options
        if (
            option.price_per_package
            is not None
            and
            option.total_cost
            is None
        )
    ]

    unknown_cost_items = [
        option.ingredient_name
        for option
        in options
        if option.total_cost
        is None
    ]

    known_subtotal = round(
        sum(
            option.total_cost
            for option
            in priced
        ),
        2,
    )

    return {
        "items":
            len(options),

        "priced_items":
            len(priced),

        "estimated_total":
            known_subtotal,

        "missing_price":
            missing_price,

        "missing_package_calc":
            missing_package_calc,

        "known_subtotal":
            known_subtotal,

        "unknown_cost_items":
            unknown_cost_items,

        "cost_complete":
            len(
                unknown_cost_items
            ) == 0,
    }


# ---------------------------------------------------------------------
# User-facing grocery summary
# ---------------------------------------------------------------------

def grocery_summary(
    options: list[
        GroceryOption
    ],
) -> dict:
    """
    Build a user-facing grocery result.

    Results are separated into:

    1. priced_products
       Product, package price and final purchase cost are known.

    2. incomplete_products
       A FairPrice product and package price were found, but package
       quantity/final purchase cost could not be calculated.

    3. missing_products
       No reliable available FairPrice product/price was found.
    """

    priced_products = []
    incomplete_products = []
    missing_products = []

    for option in options:

        item = {
            "ingredient_id":
                option.ingredient_id,

            "ingredient":
                option.ingredient_name,

            "required_quantity":
                option.required_quantity,

            "required_unit":
                option.required_unit,

            "product_name":
                option.product_name,

            "package_quantity":
                option.package_quantity,

            "package_unit":
                option.package_unit,

            "packages_needed":
                option.packages_needed,

            "price_per_package":
                option.price_per_package,

            "total_cost":
                option.total_cost,

            "store":
                option.store,

            "source_url":
                option.source_url,

            "match_status":
                option.match_status,

            "match_quality":
                option.match_quality,

            "search_query":
                option.search_query,

            "note":
                option.note,
        }

        # -------------------------------------------------------------
        # No reliable product/price
        # -------------------------------------------------------------

        if (
            option.product_name
            is None
            or
            option.price_per_package
            is None
        ):

            missing_products.append(
                item
            )

        # -------------------------------------------------------------
        # Product + price found, but final purchase calculation unknown
        # -------------------------------------------------------------

        elif (
            option.total_cost
            is None
        ):

            incomplete_products.append(
                item
            )

        # -------------------------------------------------------------
        # Fully priced
        # -------------------------------------------------------------

        else:

            priced_products.append(
                item
            )

    return {
        "items_requested":
            len(options),

        "products_priced":
            len(
                priced_products
            ),

        "products_incomplete":
            len(
                incomplete_products
            ),

        "products_missing":
            len(
                missing_products
            ),

        "priced_products":
            priced_products,

        "incomplete_products":
            incomplete_products,

        "missing_products":
            missing_products,
    }


# ---------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------

_default_service: (
    GroceryService
    | None
) = None


def _service() -> GroceryService:

    global _default_service

    if (
        _default_service
        is None
    ):
        _default_service = (
            GroceryService()
        )

    return _default_service


def search_grocery_product(
    ingredient_name: str,
) -> GroceryOption:

    return (
        _service()
        .search_grocery_product(
            ingredient_name
        )
    )


def get_grocery_option(
    ingredient_name: str,
    required_quantity: float,
    unit: str,
    ingredient_id: str | None = None,
) -> GroceryOption:

    return (
        _service()
        .get_grocery_option(
            ingredient_name,
            required_quantity,
            unit,
            ingredient_id,
        )
    )


# ---------------------------------------------------------------------
# Dynamic PantryService -> GroceryService runner
# ---------------------------------------------------------------------

if __name__ == "__main__":
    from src.pantry.pantry_service import (
        examine_pantry,
        fetch_recipe_ingredients,
        filter_ingredient_list,
        load_pantry,
    )

    recipe_id = "R03943"

    print()
    print("=" * 70)
    print("DYNAMIC PANTRY -> FAIRPRICE GROCERY CHECK")
    print("=" * 70)

    # -------------------------------------------------------------
    # Get recipe ingredients
    # -------------------------------------------------------------

    ingredients = fetch_recipe_ingredients(
        recipe_id
    )

    # -------------------------------------------------------------
    # Load pantry
    # -------------------------------------------------------------

    pantry = examine_pantry(
        load_pantry()
    )

    # -------------------------------------------------------------
    # Determine what ingredients still need to be purchased
    # -------------------------------------------------------------

    grocery_list = filter_ingredient_list(
        pantry,
        ingredients,
    )

    print()
    print(f"Recipe: {recipe_id}")

    print()
    print("Grocery List From PantryService:")

    print(
        json.dumps(
            grocery_list,
            indent=2,
            ensure_ascii=False,
        )
    )

    # -------------------------------------------------------------
    # Send PantryService output directly to GroceryService
    # -------------------------------------------------------------

    service = GroceryService(
        verify_links=False
    )

    options = service.get_grocery_list(
        grocery_list
    )

    # -------------------------------------------------------------
    # Display individual FairPrice results
    # -------------------------------------------------------------

    print()
    print("=" * 70)
    print("FAIRPRICE GROCERY RESULTS")
    print("=" * 70)

    for option in options:
        print()

        print(
            f"Ingredient: {option.ingredient_name}"
        )

        required_quantity = (
            option.required_quantity
            if option.required_quantity is not None
            else "NA"
        )

        required_unit = (
            option.required_unit
            if option.required_unit
            else ""
        )

        print(
            f"Required: {required_quantity} {required_unit}".strip()
        )

        product_name = (
            option.product_name
            if option.product_name
            else "NA"
        )

        print(
            f"Product: {product_name}"
        )

        if option.price_per_package is not None:
            price_text = (
                f"S${option.price_per_package:.2f}"
            )
        else:
            price_text = "NA"

        print(
            f"Price/package: {price_text}"
        )

        if (
            option.package_quantity is not None
            and option.package_unit is not None
        ):
            package_text = (
                f"{option.package_quantity} "
                f"{option.package_unit}"
            )
        else:
            package_text = "NA"

        print(
            f"Package size: {package_text}"
        )

        if option.packages_needed is not None:
            packages_text = str(
                option.packages_needed
            )
        else:
            packages_text = "NA"

        print(
            f"Packages needed: {packages_text}"
        )

        if option.total_cost is not None:
            total_text = (
                f"S${option.total_cost:.2f}"
            )
        else:
            total_text = "NA"

        print(
            f"Total purchase cost: {total_text}"
        )

        store_text = (
            option.store
            if option.store
            else "NA"
        )

        print(
            f"Store: {store_text}"
        )

        print(
            f"Match status: {option.match_status}"
        )

        match_quality = (
            option.match_quality
            if option.match_quality
            else "NA"
        )

        print(
            f"Match quality: {match_quality}"
        )

        search_query = (
            option.search_query
            if option.search_query
            else "NA"
        )

        print(
            f"Search query: {search_query}"
        )

        source_url = (
            option.source_url
            if option.source_url
            else "NA"
        )

        print(
            f"Source URL: {source_url}"
        )

        if option.note:
            print(
                f"Note: {option.note}"
            )

    # -------------------------------------------------------------
    # Build user-facing summary
    # -------------------------------------------------------------

    summary = grocery_summary(
        options
    )

    print()
    print("=" * 70)
    print("GROCERY SUMMARY")
    print("=" * 70)

    print(
        f"Items requested: "
        f"{summary['items_requested']}"
    )

    print(
        f"Fully priced: "
        f"{summary['products_priced']}"
    )

    print(
        f"Product/price found but purchase calculation incomplete: "
        f"{summary['products_incomplete']}"
    )

    print(
        f"Missing products/prices: "
        f"{summary['products_missing']}"
    )

    # -------------------------------------------------------------
    # Fully priced products
    # -------------------------------------------------------------

    priced_products = summary[
        "priced_products"
    ]

    if priced_products:
        print()
        print("Fully Priced Products:")

        for item in priced_products:
            price = item[
                "price_per_package"
            ]

            total = item[
                "total_cost"
            ]

            print(
                f"  - {item['ingredient']}: "
                f"{item['product_name']}"
            )

            print(
                f"    Price/package: "
                f"S${price:.2f}"
            )

            print(
                f"    Total purchase cost: "
                f"S${total:.2f}"
            )

            if item["source_url"]:
                print(
                    f"    Source: "
                    f"{item['source_url']}"
                )

    # -------------------------------------------------------------
    # Products with price but incomplete package calculation
    # -------------------------------------------------------------

    incomplete_products = summary[
        "incomplete_products"
    ]

    if incomplete_products:
        print()
        print(
            "Products With Price But "
            "Incomplete Purchase Calculation:"
        )

        for item in incomplete_products:
            price = item[
                "price_per_package"
            ]

            if price is not None:
                price_text = (
                    f"S${price:.2f}"
                )
            else:
                price_text = "NA"

            print(
                f"  - {item['ingredient']}: "
                f"{item['product_name']}"
            )

            print(
                f"    Price/package: "
                f"{price_text}"
            )

            if item["source_url"]:
                print(
                    f"    Source: "
                    f"{item['source_url']}"
                )

            if item["note"]:
                print(
                    f"    Note: "
                    f"{item['note']}"
                )

    # -------------------------------------------------------------
    # Missing products
    # -------------------------------------------------------------

    missing_products = summary[
        "missing_products"
    ]

    if missing_products:
        print()
        print("Missing Products:")

        for item in missing_products:
            print(
                f"  - {item['ingredient']}"
            )

            print(
                f"    Product: NA"
            )

            print(
                f"    Price: NA"
            )

            if item["note"]:
                print(
                    f"    Reason: "
                    f"{item['note']}"
                )

    print()
    print("=" * 70)