
"""
Ingredient-aware retail product equivalence validator.

Checks whether a retail product represents the requested
recipe ingredient rather than merely containing its name.

No external API or model dependency.

Public interface:
    validate_product(ingredient, title, url="")

Returns:
    Equivalence(accepted, reason, match_type)

Designed for use before GroceryService price ranking.
"""

from __future__ import annotations

import re
import unicodedata

from dataclasses import dataclass
from urllib.parse import urlparse, unquote


@dataclass(frozen=True)
class Equivalence:
    accepted: bool
    reason: str
    match_type: str = "exact"


# ------------------------------------------------------------
# Text normalization
# ------------------------------------------------------------

IRREGULAR = {
    "tomatoes": "tomato",
    "potatoes": "potato",
    "strawberries": "strawberry",
    "blueberries": "blueberry",
    "raspberries": "raspberry",
    "berries": "berry",
    "cherries": "cherry",
    "leaves": "leaf",
    "loaves": "loaf",
    "gummies": "gummy",
    "cookies": "cookie",
    "crisps": "crisp",
    "chips": "chip",
    "beans": "bean",
    "eggs": "egg",
    "almonds": "almond",
    "noodles": "noodle",
    "crackers": "cracker",
    "biscuits": "biscuit",
    "sachets": "sachet",
    "oranges": "orange",
}


def tokens(text: str) -> list[str]:
    text = unicodedata.normalize(
        "NFKC", str(text or "")
    ).lower()

    result = re.findall(r"[a-z]+", text)

    normalized = []

    for word in result:
        if word in IRREGULAR:
            word = IRREGULAR[word]
        elif (
            len(word) > 4
            and word.endswith("s")
            and not word.endswith(("ss", "us", "is"))
        ):
            word = word[:-1]

        normalized.append(word)

    return normalized


def has_phrase(words: list[str], phrase: str) -> bool:
    wanted = tokens(phrase)

    if not wanted:
        return False

    return any(
        words[i:i + len(wanted)] == wanted
        for i in range(len(words) - len(wanted) + 1)
    )


def reject(reason: str) -> Equivalence:
    return Equivalence(False, reason, "rejected")


# ------------------------------------------------------------
# Common ingredient aliases
# ------------------------------------------------------------

ALIASES = {
    "green onion": {
        "green onion",
        "spring onion",
        "scallion",
    },
    "scallion": {
        "scallion",
        "spring onion",
        "green onion",
    },
    "coriander": {
        "coriander",
        "cilantro",
    },
    "cilantro": {
        "cilantro",
        "coriander",
    },
    "all purpose flour": {
        "all purpose flour",
        "plain flour",
    },
    "plain flour": {
        "plain flour",
        "all purpose flour",
    },
    "garbanzo bean": {
        "garbanzo bean",
        "chickpea",
    },
    "chickpea": {
        "chickpea",
        "garbanzo bean",
    },
}


# ------------------------------------------------------------
# Product-form vocabulary
#
# These describe types of retail products, not brands.
# ------------------------------------------------------------

PRODUCT_FORMS = {
    "ice cream",
    "gelato",
    "gummy",
    "candy",
    "chocolate",
    "cookie",
    "biscuit",
    "cake",
    "pastry",
    "dessert",
    "pudding",
    "granola",
    "cereal",
    "muesli",
    "potato chip",
    "chip",
    "crisp",
    "cracker",
    "popcorn",
    "snack",
    "instant noodle",
    "noodle",
    "wrap",
    "bread",
    "pizza",
    "pizza crust",
    "soup",
    "sauce",
    "ketchup",
    "paste",
    "spread",
    "dip",
    "dressing",
    "marinade",
    "stock",
    "broth",
    "seasoning",
    "syrup",
    "jam",
    "jelly",
    "juice",
    "smoothie",
    "cordial",
    "soda",
    "tea",
    "coffee",
    "milk",
    "yogurt",
    "yoghurt",
    "cheese",
    "butter",
    "oil",
    "flour",
    "starch",
    "powder",
    "soju",
    "vodka",
    "beer",
    "wine",
    "liqueur",
    "supplement",
    "vitamin",
    "capsule",
    "tablet",
    "pet food",
    "soap",
    "shampoo",
    "detergent",
    "cleaner",
    "lotion",
}

# Preparations that substantially change a food.
# A requested preparation is allowed; an unexpected
# preparation is not silently treated as exact.

SPECIAL_PREPARATIONS = {
    "century",
    "preserved",
    "fermented",
    "pickled",
    "salted",
    "sugared",
    "sweetened",
    "candied",
    "smoked",
    "flavoured",
    "flavored",
    "gluten free",
    "sugar free",
}

# Words that do not change primary ingredient identity.

NEUTRAL_WORDS = {
    "fresh",
    "frozen",
    "raw",
    "organic",
    "whole",
    "ground",
    "crushed",
    "chopped",
    "sliced",
    "diced",
    "peeled",
    "roasted",
    "toasted",
    "baked",
    "shredded",
    "grated",
    "fine",
    "coarse",
    "boneless",
    "skinless",
    "seedless",
    "natural",
    "plain",
    "premium",
    "quality",
    "local",
    "imported",
}

CHEESE_VARIETIES = {
    "mozzarella",
    "brie",
    "cheddar",
    "parmesan",
    "gouda",
    "feta",
    "ricotta",
    "mascarpone",
    "camembert",
}

# Important multiword ingredient identities.
# A compound ingredient must not be confused with
# another food that merely contains one of its words.

COMPOUND_IDENTITIES = {
    "peanut butter",
    "almond butter",
    "cashew butter",
    "cocoa butter",
    "lemon grass",
    "lemongrass",
    "century egg",
    "coconut water",
    "salted egg",
    "salted egg yolk",
    "sugared egg yolk",
    "black eyed bean",
    "black eye bean",
    "black eyed pea",
    "fermented black bean",
    "coconut milk",
    "almond milk",
    "oat milk",
    "soy milk",
    "rice milk",
    "corn flour",
    "corn starch",
    "potato flour",
    "potato starch",
    "gluten free flour",
}


def requested_identity_present(
    wanted: list[str],
    actual: list[str],
) -> bool:
    ingredient = " ".join(wanted)

    alternatives = ALIASES.get(ingredient)

    if alternatives:
        return any(
            has_phrase(actual, alias)
            for alias in alternatives
        )

    return all(
        word in actual
        for word in wanted
    )


def check_compound_identity(
    wanted: list[str],
    actual: list[str],
) -> str | None:
    """
    Reject a distinct compound food when the requested
    ingredient is only a component of that compound.
    """

    for compound in COMPOUND_IDENTITIES:
        if not has_phrase(actual, compound):
            continue

        if has_phrase(wanted, compound):
            continue

        compound_words = set(tokens(compound))
        wanted_words = set(wanted)

        if compound_words & wanted_words:
            return (
                "different compound ingredient: "
                + compound
            )

    # Prevent the ingredient lemon being interpreted
    # as lemon grass, even when tokenization differs.
    if (
        "lemon" in wanted
        and "grass" not in wanted
        and (
            "lemongrass" in actual
            or has_phrase(actual, "lemon grass")
        )
    ):
        return "lemongrass is not lemon"

    return None


def check_product_form(
    wanted: list[str],
    actual: list[str],
) -> str | None:

    requested_forms = {
        form
        for form in PRODUCT_FORMS
        if has_phrase(wanted, form)
    }

    observed_forms = {
        form
        for form in PRODUCT_FORMS
        if has_phrase(actual, form)
    }

    extra = observed_forms - requested_forms

    # A cheese variety may legitimately be called cheese.
    if set(wanted) & CHEESE_VARIETIES:
        extra.discard("cheese")

    # Pizza crust naturally contains the word pizza.
    if "pizza crust" in requested_forms:
        extra.discard("pizza")

    # The word "powder" is not inherently incompatible
    # with ground spices, but keep it conservative
    # unless the requested ingredient supports it.
    if "pepper" in wanted:
        extra.discard("powder")

    if extra:
        form = sorted(
            extra,
            key=lambda x: (-len(x.split()), x),
        )[0]

        return "different retail product form: " + form

    return None


def check_preparation(
    wanted: list[str],
    actual: list[str],
) -> str | None:

    requested = {
        prep
        for prep in SPECIAL_PREPARATIONS
        if has_phrase(wanted, prep)
    }

    observed = {
        prep
        for prep in SPECIAL_PREPARATIONS
        if has_phrase(actual, prep)
    }

    extra = observed - requested

    # Salted butter is a common variant of butter.
    # It should not automatically be rejected solely
    # because the product is salted.
    if "butter" in wanted and "peanut" not in actual:
        extra.discard("salted")

    # Ordinary fresh produce can have harmless
    # packaging/preparation descriptions.
    if extra:
        preparation = sorted(extra)[0]

        return (
            "different ingredient preparation: "
            + preparation
        )

    return None


def check_url_identity(
    wanted: list[str],
    actual: list[str],
    url: str,
) -> str | None:
    """
    Detect clear title/URL disagreement.

    Do not reject opaque numeric product URLs.
    """

    if not url:
        return None

    path = unquote(urlparse(url).path).lower()

    if "/product/" not in path:
        return None

    slug = path.split("/product/", 1)[-1]

    # Remove trailing product identifiers and numbers.
    slug = re.sub(
        r"-\d+(?:-\d+)*$",
        "",
        slug,
    )

    slug_words = tokens(slug)

    if len(slug_words) < 2:
        return None

    # Product-title tokens provide a stronger
    # consistency check than search snippets.
    title_identity = set(actual)
    slug_identity = set(slug_words)

    # Ignore generic retail descriptors.
    ignore = NEUTRAL_WORDS | {
        "fairprice",
        "pasar",
        "product",
        "pack",
        "sg",
        "the",
        "of",
        "and",
    }

    meaningful_title = title_identity - ignore
    meaningful_slug = slug_identity - ignore

    if not meaningful_title or not meaningful_slug:
        return None

    if not (meaningful_title & meaningful_slug):
        return "product title and URL disagree"

    # If the ingredient is not in the descriptive URL,
    # require stronger evidence from the title.
    if not requested_identity_present(
        wanted, slug_words
    ):
        # Only reject if there is no clear overlap
        # with the ingredient's identity.
        if not (set(wanted) & meaningful_slug):
            ingredient = " ".join(wanted)

            aliases = ALIASES.get(ingredient, set())

            if not any(
                has_phrase(slug_words, alias)
                for alias in aliases
            ):
                return (
                    "product URL does not support "
                    "ingredient identity"
                )

    return None


# ------------------------------------------------------------
# Main validator
# ------------------------------------------------------------

def validate_product(
    ingredient: str,
    title: str,
    url: str = "",
) -> Equivalence:

    wanted = tokens(ingredient)
    actual = tokens(title)

    if not wanted or not actual:
        return reject(
            "empty ingredient or product title"
        )

    # 1. Ingredient identity must appear in the title
    # or be recognized through a supported alias.

    if not requested_identity_present(wanted, actual):
        return reject(
            "ingredient identity missing from title"
        )

    # 2. Distinct compound food identities.

    compound_issue = check_compound_identity(
        wanted, actual
    )

    if compound_issue:
        return reject(compound_issue)

    # 3. Product category and form.

    form_issue = check_product_form(
        wanted, actual
    )

    if form_issue:
        return reject(form_issue)

    # 4. Ingredient preparation.

    preparation_issue = check_preparation(
        wanted, actual
    )

    if preparation_issue:
        return reject(preparation_issue)

    # 5. Product title versus URL.

    url_issue = check_url_identity(
        wanted, actual, url
    )

    if url_issue:
        return reject(url_issue)

    # 6. Accepted ingredient identity.

    return Equivalence(
        True,
        "ingredient identity and retail form compatible",
        "exact",
    )
