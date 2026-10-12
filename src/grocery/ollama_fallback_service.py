
"""
Grocery Service with optional local Ollama price fallback.

Tavily remains the primary source.

Ollama is used only when no usable retail purchase cost
or quantity-based retail estimate exists.

Only validated Ollama estimates are cached.
LLM estimates never become verified retailer prices.
"""

from __future__ import annotations

import math
import os
from dataclasses import asdict

from src.cache.cache_service import cache_key as cache_key_fn
from src.grocery.grocery_service import GroceryService
from src.grocery.ollama_price_estimator import (
    GroceryPriceEstimate,
    OLLAMA_MODEL,
    estimate_grocery_price,
)


OLLAMA_CACHE_CATEGORY = "ollama_grocery_v2"
OLLAMA_CACHE_TTL_SECONDS = 7 * 86400
OLLAMA_ESTIMATE_VERSION = "v2"


def _valid_ollama_estimate(estimate) -> bool:
    """Validate an Ollama estimate before caching or using it."""

    if not isinstance(estimate, GroceryPriceEstimate):
        return False

    try:
        price = float(estimate.estimated_price_sgd)
        total = float(estimate.estimated_total_cost)
        quantity = float(estimate.estimated_package_quantity)

        raw_count = estimate.estimated_packages_needed
        count = int(raw_count)

        if isinstance(raw_count, bool):
            return False

        if float(raw_count) != count:
            return False

        if not all(
            math.isfinite(value)
            for value in (price, total, quantity)
        ):
            return False

        if not (
            0 < price <= 1000
            and 0 < total <= 10000
            and quantity > 0
            and 1 <= count <= 1000
        ):
            return False

        if not isinstance(
            estimate.estimated_product, str
        ) or not estimate.estimated_product.strip():
            return False

        if not isinstance(
            estimate.estimated_package_unit, str
        ) or not estimate.estimated_package_unit.strip():
            return False

        expected_total = price * count

        if abs(total - expected_total) > max(
            0.03,
            expected_total * 0.01,
        ):
            return False

        return True

    except (
        TypeError,
        ValueError,
        AttributeError,
        OverflowError,
    ):
        return False


class OllamaFallbackGroceryService(GroceryService):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.enable_ollama_fallback = (
            os.getenv(
                "ENABLE_OLLAMA_GROCERY_FALLBACK",
                "1",
            ) == "1"
        )

        self._ollama_estimate_cache = {}

    def get_grocery_option(
        self,
        ingredient_name,
        required_quantity=None,
        unit=None,
        *args,
        **kwargs,
    ):
        # --------------------------------------------------
        # 1. Tavily remains the primary source
        # --------------------------------------------------

        option = super().get_grocery_option(
            ingredient_name,
            required_quantity,
            unit,
            *args,
            **kwargs,
        )

        if not self.enable_ollama_fallback:
            return option

        if option.total_cost is not None:
            return option

        if option.estimated_total_cost is not None:
            return option


        
        # Normalize missing units for the Ollama request.
        # Preserve the original GroceryOption requirement.

        ollama_unit = str(unit or "").strip().lower()

        if ollama_unit in {"nan", "none", "null", ""}:
            ingredient_key = " ".join(
                str(ingredient_name or "").lower().split()
            )

            if ingredient_key in {
                "lemon", "lemons",
                "orange", "oranges",
                "lime", "limes",
                "apple", "apples",
                "egg", "eggs",
            }:
                ollama_unit = "count"
            else:
                ollama_unit = None


        # --------------------------------------------------
        # 2. Build deterministic cache keys
        # --------------------------------------------------

        request_key = (
            " ".join(str(ingredient_name or "").lower().split()),
            str(required_quantity),
            str(ollama_unit or ""),
            OLLAMA_MODEL,
            OLLAMA_ESTIMATE_VERSION,
        )

        persistent_key = cache_key_fn(
            OLLAMA_CACHE_CATEGORY,
            {
                "ingredient": request_key[0],
                "quantity": request_key[1],
                "unit": request_key[2],
                "model": request_key[3],
                "version": request_key[4],
            },
        )

        estimate = None

        # --------------------------------------------------
        # 3. In-memory cache
        # --------------------------------------------------

        cached_memory = self._ollama_estimate_cache.get(
            request_key
        )

        if _valid_ollama_estimate(cached_memory):
            print(
                f"[MEMORY OLLAMA CACHE HIT] {ingredient_name}"
            )
            estimate = cached_memory

        elif cached_memory is not None:
            self._ollama_estimate_cache.pop(
                request_key,
                None,
            )

        # --------------------------------------------------
        # 4. Persistent SQLite cache
        # --------------------------------------------------

        if (
            estimate is None
            and self.persistent_cache is not None
        ):
            saved = self.persistent_cache.get(
                OLLAMA_CACHE_CATEGORY,
                persistent_key,
            )

            if saved is not None:
                try:
                    restored = (
                        GroceryPriceEstimate(**saved)
                        if isinstance(saved, dict)
                        else None
                    )
                except (TypeError, ValueError):
                    restored = None

                if _valid_ollama_estimate(restored):
                    print(
                        f"[SQLITE OLLAMA CACHE HIT] "
                        f"{ingredient_name}"
                    )

                    estimate = restored
                    self._ollama_estimate_cache[
                        request_key
                    ] = restored

                else:
                    self.persistent_cache.delete(
                        OLLAMA_CACHE_CATEGORY,
                        persistent_key,
                    )

        # --------------------------------------------------
        # 5. Live Ollama fallback
        # --------------------------------------------------

        if estimate is None:
            print(
                f"[LIVE OLLAMA GROCERY FALLBACK] "
                f"{ingredient_name}"
            )

            estimate = estimate_grocery_price(
                ingredient_name=ingredient_name,
                required_quantity=required_quantity,
                required_unit=ollama_unit,
            )

        if not _valid_ollama_estimate(estimate):
            print("\n[OLLAMA ESTIMATE REJECTED]")
            print("Ingredient:", ingredient_name)
            print("Required quantity:", required_quantity)
            print("Required unit:", unit)
            print("Raw estimate:", repr(estimate))

            option.note = (
                (option.note or "")
                + " Ollama could not provide a usable estimate."
            ).strip()

            return option

            # Save only valid estimates in memory.
            self._ollama_estimate_cache[
                request_key
            ] = estimate

            # Save only valid estimates in SQLite.
            if self.persistent_cache is not None:
                self.persistent_cache.set(
                    OLLAMA_CACHE_CATEGORY,
                    persistent_key,
                    asdict(estimate),
                    OLLAMA_CACHE_TTL_SECONDS,
                )

                print(
                    f"[OLLAMA CACHE SAVED] {ingredient_name}"
                )

        # --------------------------------------------------
        # 6. Populate GroceryOption
        # --------------------------------------------------

        option.product_name = estimate.estimated_product

        option.price_per_package = float(
            estimate.estimated_price_sgd
        )

        option.package_quantity = float(
            estimate.estimated_package_quantity
        )

        option.package_unit = (
            estimate.estimated_package_unit
        )

        option.packages_needed = int(
            estimate.estimated_packages_needed
        )

        option.minimum_package_cost = None

        # Both Tavily and Ollama costs enter the same grocery total.
        option.total_cost = float(
            estimate.estimated_total_cost
        )

        # Preserve the legacy field for compatibility.
        option.estimated_total_cost = float(
            estimate.estimated_total_cost
        )

        option.purchase_basis = (
            "llm_estimated_package"
        )

        option.match_status = (
            "estimated_no_retail_match"
        )

        option.match_quality = None
        option.currency = "SGD"

        # Never present an Ollama estimate as a retailer listing.
        option.store = None
        option.source_url = None
        option.source_updated_at = None

        option.purchase_channel = (
            "availability_unverified"
        )

        option.quantity_estimated = True

        option.note = (
            "Unverified Singapore grocery price estimated "
            "by local Ollama. No live retailer price or "
            "package coverage was confirmed. "
            "Confidence: LOW."
        )

        return option
