"""src/grocery/tavily_client.py

Find Singapore grocery prices from FairPrice using Tavily web search.

For each ingredient, Tavily searches FairPrice and converts usable
FairPrice product pages into normalized product dictionaries containing:

    title
    price
    currency
    package-size text
    store
    URL
    stock status

Only individual FairPrice product pages are accepted. Search pages,
category pages, promotion pages, and pages without a reliable price
are rejected.
"""

import hashlib
import os
import re
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv


# ---------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------

load_dotenv(Path(__file__).resolve().parents[2] / ".env")


# ---------------------------------------------------------------------
# Grocery source
# ---------------------------------------------------------------------

GROCERY_DOMAIN = "fairprice.com.sg"
GROCERY_STORE = "FairPrice"


# ---------------------------------------------------------------------
# FairPrice page detection
# ---------------------------------------------------------------------

# Individual product pages.
_PRODUCT_URL = re.compile(
    r"/(product|products|p)/"
    r"|-i\d+(-s\d+)?\.html"
    r"|[-/]\d{5,}/?$",
    re.IGNORECASE,
)

# Pages that may contain many products/prices and therefore must not
# be treated as one grocery product.
_NON_PRODUCT_URL = re.compile(
    r"/(search|category|categories|promotions?|collections?|brands?|"
    r"recipes?|blog|deals|offers?|product-listing|tag)(/|$|\?)"
    r"|[?&](q|query|keyword|search|category|pageType|tag)=",
    re.IGNORECASE,
)

_OUT_OF_STOCK = re.compile(
    r"out of stock|sold out|currently unavailable|not available",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------
# Price extraction
# ---------------------------------------------------------------------

# Matches:
# $3.45
# S$3.45
# S$ 3.45
# SGD 3.45
_PRICE = re.compile(
    r"(?:S\$|SGD\s?|\$)\s?"
    r"(\d{1,4}(?:,\d{3})*(?:\.\d{1,2})?)"
)

# Prices immediately following these phrases are usually promotional
# thresholds, fees or rewards rather than the product price.
#
# Example:
# "Free delivery above $79"
_IGNORE_BEFORE = re.compile(
    r"\b("
    r"deliver\w*|above|min|minimum|spend|save|voucher|cashback|"
    r"over|free|shipping|fee|off|worth|up to|earn|reward"
    r")\b[^$]{0,25}$",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------
# FairPrice title cleanup
# ---------------------------------------------------------------------

_TITLE_SUFFIX = re.compile(
    r"\s+[|\-–—]\s+.*"
    r"(fairprice|ntuc fairprice|singapore|online|shop).*$",
    re.IGNORECASE,
)


class SearchError(Exception):
    """Raised when Tavily itself fails rather than simply finding no products."""


def store_for(url: str) -> tuple[str | None, str | None]:
    """
    Return FairPrice information when a URL belongs to FairPrice.

    Subdomains such as omni.fairprice.com.sg are also recognised.
    """

    host = urlparse(url or "").netloc.lower().removeprefix("www.")

    if host == GROCERY_DOMAIN or host.endswith("." + GROCERY_DOMAIN):
        return GROCERY_DOMAIN, GROCERY_STORE

    return None, None


def is_product_page(url: str) -> bool:
    """
    Return True only when the URL looks like an individual product page.

    Category, search, tag and promotional pages are rejected because
    they may contain multiple products and multiple unrelated prices.
    """

    parsed = urlparse(url or "")

    path_and_query = parsed.path

    if parsed.query:
        path_and_query += "?" + parsed.query

    if _NON_PRODUCT_URL.search(path_and_query):
        return False

    return bool(_PRODUCT_URL.search(path_and_query))


def clean_title(title: str) -> str:
    """
    Remove FairPrice page decorations from a product title.

    Example:
        "Buy Meiji Fresh Milk 2L | FairPrice Singapore"
        -> "Meiji Fresh Milk 2L"
    """

    title = str(title or "")

    title = re.sub(
        r"^\s*buy\s+",
        "",
        title,
        flags=re.IGNORECASE,
    )

    return _TITLE_SUFFIX.sub("", title).strip()


def extract_price(text: str) -> float | None:
    """
    Extract the first reliable product price from FairPrice text.

    Promotional thresholds such as:
        "Free delivery above $79"

    and unit prices such as:
        "$0.35/100g"

    are ignored.

    FairPrice offer pages commonly show:
        $16.50
        $18.20
        Save $1.70

    where the first price is the current offer price and the second is
    the previous price. Therefore page order is preserved.
    """

    text = str(text or "")

    matches = list(_PRICE.finditer(text))
    prices = []

    for match in matches:
        before = text[
            max(0, match.start() - 50):
            match.start()
        ]

        after = text[
            match.end():
            match.end() + 30
        ]

        # Ignore delivery thresholds, minimum spends, vouchers, etc.
        if _IGNORE_BEFORE.search(before):
            continue

        # Ignore unit prices such as "$0.35/100g".
        if after.lstrip().startswith("/"):
            continue

        value = float(
            match.group(1).replace(",", "")
        )

        if 0 < value <= 1000:
            prices.append(value)

    if not prices:
        return None

    # Preserve FairPrice page order.
    # The first valid price is normally the current selling price.
    return round(prices[0], 2)


def normalize(result: dict) -> dict | None:
    """
    Convert one Tavily result into the grocery product format.

    Returns None when the result is not a usable FairPrice product page
    or when a reliable product price cannot be extracted.
    """

    url = result.get("url") or ""

    domain, store = store_for(url)

    # FairPrice only.
    if not domain:
        return None

    # Reject categories, searches, tags and promotional pages.
    if not is_product_page(url):
        return None

    title = clean_title(
        result.get("title") or ""
    )

    snippet = result.get("content") or ""
    raw = result.get("raw_content") or ""

    if not title:
        return None

    # Try to locate the product title inside the raw page.
    # Starting near the product name reduces the chance of reading
    # unrelated prices elsewhere on a large page.
    if raw:
        start = raw.lower().find(
            title.lower()[:30]
        )
    else:
        start = -1

    if start < 0:
        start = 0

    raw_price_section = raw[
        start:
        start + 3000
    ]

    # Prefer raw product-page content.
    # Fall back to the Tavily search snippet if necessary.
    price = extract_price(raw_price_section)

    if price is None:
        price = extract_price(snippet)

    if price is None:
        return None

    page_text = (
        f"{snippet} "
        f"{raw[start:start + 1500]}"
    )

    size_text = (
        f"{snippet[:500]} "
        f"{raw[start:start + 500]}"
    )

    return {
        "product_id": hashlib.sha1(
            url.encode()
        ).hexdigest()[:12],

        "title": title,

        "price": price,

        "currency": "SGD",

        "merchant_id": domain,

        "store": store,

        "url": url,

        "size_text": size_text,

        "availability": "local",

        "in_stock": (
            False
            if _OUT_OF_STOCK.search(page_text)
            else None
        ),

        "country_code": "SG",

        "region": "sg",

        # FairPrice/Tavily pages do not reliably provide the date on
        # which the displayed grocery price was last updated.
        "source_updated_at": None,
    }


class TavilyGroceryClient:
    """
    Tavily client restricted to FairPrice grocery results.
    """

    def __init__(
        self,
        api_key: str | None = None,
        max_results: int = 10,
        search_depth: str = "basic",
    ):
        self.api_key = (
            api_key
            or os.environ.get("TAVILY_API_KEY", "")
        )

        self.max_results = max_results
        self.search_depth = search_depth
        self._client = None

    def _tavily(self):
        if self._client is None:

            if not self.api_key:
                raise SearchError(
                    "TAVILY_API_KEY is not set "
                    "(add it to .env)"
                )

            from tavily import TavilyClient

            self._client = TavilyClient(
                api_key=self.api_key
            )

        return self._client

    def search_raw(self, query: str) -> dict:
        """
        Search FairPrice through Tavily.

        The FairPrice restriction is handled by include_domains,
        so the text query itself does not need to contain the store name.
        """

        try:
            response = self._tavily().search(
            query=f"price of {query} in Singapore",
            search_depth=self.search_depth,
            max_results=self.max_results,
            include_domains=[GROCERY_DOMAIN],
            include_raw_content="text",
        )

            return response

        except SearchError:
            raise

        except Exception as exc:
            raise SearchError(
                f"Tavily search failed: "
                f"{type(exc).__name__}: {exc}"
            ) from exc

    def search(
        self,
        query: str,
        limit: int | None = None,
    ) -> list[dict]:

        search_terms = [
            query,
            f"{query} grocery product",
            f"buy {query}",
        ]

        products = []
        seen_urls = set()

        for search_term in search_terms:

            results = (
                self.search_raw(search_term)
                .get("results")
                or []
            )

            normalized = [
                product
                for product in (
                    normalize(result)
                    for result in results
                )
                if product is not None
            ]

            for product in normalized:

                url = product.get("url")

                if url not in seen_urls:
                    seen_urls.add(url)
                    products.append(product)

            # We found usable individual FairPrice products.
            # Do not make unnecessary additional Tavily searches.
            if products:
                break

        if limit is not None:
            return products[:limit]

        return products