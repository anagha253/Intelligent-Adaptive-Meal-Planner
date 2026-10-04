"""src/grocery/food_filter.py

Clean recipe ingredient text and determine whether a grocery product
is a reliable match for the requested ingredient.

This module is responsible for:

- removing quantities, units and preparation words
- rejecting non-food products
- rejecting processed products when the raw ingredient was requested
- identifying exact and approximate ingredient matches
- generating progressively simpler ingredient search queries

Store selection is handled by tavily_client.py and grocery_service.py.
"""

import re


# ---------------------------------------------------------------------
# Products that must never be treated as grocery ingredients
# ---------------------------------------------------------------------

NON_FOOD = [
    # Pets
    "pet",
    "pets",
    "dog",
    "dogs",
    "cat",
    "cats",
    "puppy",
    "kitten",
    "kibble",
    "litter",
    "aquarium",
    "pedigree",
    "whiskas",
    "friskies",
    "purina",
    "iams",
    "cesar",
    "sheba",
    "felix",
    "loveabowl",
    "canin",
    "smartheart",
    "nutrience",
    "acana",
    "orijen",

    # Appliances / kitchenware
    "cooker",
    "maker",
    "kettle",
    "blender",
    "juicer",
    "fryer",
    "oven",
    "microwave",
    "toaster",
    "machine",
    "appliance",
    "processor",
    "dispenser",
    "container",
    "lunchbox",
    "tumbler",
    "flask",
    "mug",
    "tray",
    "mould",
    "mold",
    "cutter",
    "press",
    "pan",
    "pot",
    "wok",
    "knife",
    "spatula",
    "storage",
    "scale",
    "steamer",
    "grinder",

    # Household / personal care
    "detergent",
    "cleaner",
    "soap",
    "shampoo",
    "conditioner",
    "lotion",
    "wash",
    "tissue",
    "diaper",
    "wipes",
    "cosmetic",
    "skincare",
    "mask",
    "perfume",
    "fragrance",
    "candle",
    "bleach",
    "bath",
    "soak",
    "scent",
    "scented",
    "bubble",
    "body",
    "skin",
    "moisturiser",
    "moisturizer",

    # Home / furniture
    "panel",
    "wall",
    "tile",
    "paint",
    "fabric",
    "curtain",
    "sofa",
    "furniture",
    "rug",

    # Health
    "supplement",
    "vitamin",
    "vitamins",
    "capsule",
    "capsules",
    "tablet",
    "tablets",
    "collagen",

    # Electronics / fashion / misc
    "phone",
    "iphone",
    "ipad",
    "macbook",
    "airpods",
    "watch",
    "charger",
    "cable",
    "speaker",
    "headphones",
    "laptop",
    "cover",
    "toy",
    "toys",
    "plush",
    "keychain",
    "sticker",
    "costume",
    "shirt",
    "book",
    "fake",
    "artificial",
    "replica",
    "seeds",
    "plant",
    "planter",
]


# ---------------------------------------------------------------------
# Processed products
# ---------------------------------------------------------------------

PROCESSED = [
    "sauce",
    "ketchup",
    "paste",
    "puree",
    "flavour",
    "flavor",
    "flavoured",
    "flavored",
    "chips",
    "crisps",
    "cracker",
    "crackers",
    "biscuit",
    "biscuits",
    "cookie",
    "cookies",
    "cake",
    "cakes",
    "candy",
    "chocolate",
    "soup",
    "stock",
    "cube",
    "cubes",
    "seasoning",
    "powder",
    "noodle",
    "noodles",
    "snack",
    "snacks",
    "nugget",
    "nuggets",
    "jam",
    "jelly",
    "drink",
    "drinks",
    "tea",
    "wafer",
    "bar",
    "bars",
    "ice cream",
    "yogurt",
    "yoghurt",
    "dessert",
    "pudding",
    "spread",
    "dressing",
    "marinade",
    "mix",
    "sausage",
    "sausages",
    "ball",
    "balls",
    "bun",
    "buns",
    "pie",
    "vinegar",
    "flour",
    "wine",
    "oil",
    "starch",
    "bran",
    "kinder",
    "surprise",
    "easter",
    "creme",
    "formula",
    "infant",
    "toddler",
    "growing",
]


# ---------------------------------------------------------------------
# Recipe description/preparation words
# ---------------------------------------------------------------------

DESCRIPTORS = {
    "fresh",
    "large",
    "small",
    "medium",
    "big",
    "boneless",
    "skinless",
    "chopped",
    "diced",
    "minced",
    "sliced",
    "grated",
    "shredded",
    "ground",
    "crushed",
    "peeled",
    "deveined",
    "trimmed",
    "halved",
    "quartered",
    "cubed",
    "julienned",
    "finely",
    "thinly",
    "roughly",
    "coarsely",
    "lightly",
    "freshly",
    "organic",
    "raw",
    "cooked",
    "uncooked",
    "ripe",
    "lean",
    "extra",
    "virgin",
    "whole",
    "unsalted",
    "salted",
    "softened",
    "melted",
    "beaten",
    "packed",
    "divided",
    "optional",
    "taste",
    "room",
    "temperature",
    "cold",
    "warm",
    "hot",
    "dried",
    "rinsed",
    "drained",
    "washed",
    "of",
    "and",
    "or",
    "for",
    "a",
    "an",
    "the",
    "to",
    "about",
    "plus",
    "more",
    "into",
    "cut",
    "pieces",
    "piece",

    # Portion words
    "clove",
    "sprig",
    "leaf",
    "leave",
    "stalk",
    "bunch",
    "head",
    "can",
    "tin",
    "slice",
    "pinch",
    "dash",
    "handful",

    # Recipe measurement units
    "cup",
    "tbsp",
    "tsp",
    "tablespoon",
    "teaspoon",
    "g",
    "kg",
    "ml",
    "l",
    "oz",
    "lb",
}


# ---------------------------------------------------------------------
# Generic product heads
# ---------------------------------------------------------------------

# These words are not specific enough to identify the requested food
# by themselves.
#
# Example:
#
# "duck breast"
#
# must NOT match:
#
# "Fresh Chicken Breast 500g"

GENERIC_HEADS = {
    "breast",
    "thigh",
    "fillet",
    "leg",
    "wing",
    "mince",
    "meat",
    "steak",
    "chop",
    "loin",
    "belly",
    "shoulder",
    "cheese",
    "milk",
    "oil",
    "sauce",
    "bean",
    "pepper",
}


# ---------------------------------------------------------------------
# Regex helpers
# ---------------------------------------------------------------------

_TECH_SPECS = re.compile(
    r"\b\d+\s?(gb|tb|mah)\b"
    r"|\b(5g|4g|bluetooth|wi-?fi|usb)\b",
    re.IGNORECASE,
)

_WORD = re.compile(r"[a-z]+")


# ---------------------------------------------------------------------
# Small plural normalizer
# ---------------------------------------------------------------------

def _stem(word: str) -> str:
    """
    Perform minimal plural normalization.

    Examples:
        tomatoes -> tomato
        eggs     -> egg
        berries  -> berry
        leaves   -> leave
    """

    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"

    if len(word) > 4 and word.endswith("oes"):
        return word[:-2]

    if (
        len(word) > 3
        and word.endswith("s")
        and not word.endswith("ss")
    ):
        return word[:-1]

    return word


# ---------------------------------------------------------------------
# Tokenization
# ---------------------------------------------------------------------

def words(text: str) -> list[str]:
    """
    Return normalized lowercase words from text.
    """

    return [
        _stem(word)
        for word
        in _WORD.findall(
            str(text).lower()
        )
    ]


def _core_tokens(
    text: str,
) -> list[str]:
    """
    Remove quantities, units, preparation words and recipe descriptions.

    Example:

        "2 boneless skinless chicken breasts, diced (about 500g)"

    becomes approximately:

        ["chicken", "breasts"]
    """

    text = str(text).lower()

    # Remove parenthesized recipe notes.
    #
    # Example:
    # "(about 500g)"
    text = re.sub(
        r"\([^)]*\)",
        " ",
        text,
    )

    # Preparation instructions after a comma usually do not describe
    # the grocery product.
    #
    # Example:
    # "chicken breasts, diced"
    text = text.split(",")[0]

    raw = _WORD.findall(text)

    core = [
        word
        for word in raw
        if _stem(word) not in DESCRIPTORS
    ]

    return core or raw


def clean_ingredient(
    text: str,
) -> list[str]:
    """
    Return normalized ingredient words.

    Example:

        "2 boneless skinless chicken breasts, diced"

    becomes:

        ["chicken", "breast"]
    """

    return [
        _stem(word)
        for word
        in _core_tokens(text)
    ]


# ---------------------------------------------------------------------
# Pre-computed filtering sets
# ---------------------------------------------------------------------

_NON_FOOD_STEMS = {
    _stem(word)
    for word in NON_FOOD
}

_PROCESSED_SINGLE = {
    _stem(word)
    for word in PROCESSED
    if " " not in word
}

_PROCESSED_PHRASES = [
    phrase
    for phrase in PROCESSED
    if " " in phrase
]


# ---------------------------------------------------------------------
# Product matching
# ---------------------------------------------------------------------

def check_match(
    ingredient: str,
    title: str,
) -> tuple[bool, str]:
    """
    Determine whether a grocery product title is a valid match.

    Returns:

        (True, "exact")
        (True, "approximate")

    or:

        (False, reason)
    """

    core = clean_ingredient(
        ingredient
    )

    if not core:
        return False, "ingredient has no usable words"

    core_set = set(core)

    title_words = set(
        words(title)
    )

    # -------------------------------------------------------------
    # Reject non-food products
    # -------------------------------------------------------------

    bad = (
        title_words
        & _NON_FOOD_STEMS
    ) - core_set

    if bad:
        return (
            False,
            f"non-food word: "
            f"{sorted(bad)[0]}",
        )

    # -------------------------------------------------------------
    # Reject obvious electronics
    # -------------------------------------------------------------

    if _TECH_SPECS.search(
        str(title)
    ):
        return (
            False,
            "electronics spec in title",
        )

    # -------------------------------------------------------------
    # Reject processed versions unless explicitly requested
    # -------------------------------------------------------------

    processed = (
        title_words
        & _PROCESSED_SINGLE
    ) - core_set

    ingredient_text = " ".join(
        core
    )

    processed_phrases = [
        phrase
        for phrase
        in _PROCESSED_PHRASES

        if (
            phrase in str(title).lower()
            and
            phrase not in ingredient_text
        )
    ]

    if processed or processed_phrases:

        reason = (
            sorted(processed)[0]
            if processed
            else processed_phrases[0]
        )

        return (
            False,
            f"processed product: {reason}",
        )

    # -------------------------------------------------------------
    # Exact match
    # -------------------------------------------------------------

    if core_set <= title_words:
        return True, "exact"

    # -------------------------------------------------------------
    # Approximate match
    # -------------------------------------------------------------

    head = core[-1]

    if head in title_words:

        # Generic words cannot establish a match by themselves.
        #
        # Example:
        #
        # ingredient = duck breast
        # product    = chicken breast
        #
        # "breast" matches, but "duck" does not.
        if (
            head in GENERIC_HEADS
            and
            len(core) > 1
            and
            core[-2] not in title_words
        ):
            return (
                False,
                f"'{head}' matched but not "
                f"'{core[-2]}'",
            )

        return True, "approximate"

    return (
        False,
        f"main ingredient word missing: "
        f"{head}",
    )


# ---------------------------------------------------------------------
# Search query generation
# ---------------------------------------------------------------------

def search_queries(
    ingredient: str,
) -> list[str]:
    """
    Generate ingredient searches from specific to more general.

    Store/domain restriction is handled by TavilyGroceryClient,
    so this function only generates ingredient names.

    Examples:

        "2 boneless skinless chicken breasts, diced"

        -> [
            "chicken breasts",
            "chicken"
        ]


        "1 cup fresh cherry tomatoes"

        -> [
            "cherry tomatoes",
            "tomatoes"
        ]


        "tofu"

        -> [
            "tofu"
        ]
    """

    tokens = _core_tokens(
        ingredient
    )

    if not tokens:
        return []

    base = " ".join(
        tokens
    )

    stemmed = [
        _stem(token)
        for token in tokens
    ]

    queries = [
        base
    ]

    if len(tokens) > 1:

        # ---------------------------------------------------------
        # Generic meat/product head
        #
        # chicken breasts -> chicken
        # duck breast     -> duck
        # pork loin       -> pork
        # ---------------------------------------------------------

        if stemmed[-1] in GENERIC_HEADS:

            main_food = tokens[-2]

            if main_food:
                queries.append(
                    main_food
                )

        # ---------------------------------------------------------
        # Descriptive ingredient
        #
        # cherry tomatoes -> tomatoes
        #
        # This allows a broader grocery result when the exact
        # ingredient wording is unavailable.
        # ---------------------------------------------------------

        else:

            broader = tokens[-1]

            if broader:
                queries.append(
                    broader
                )

    # Remove duplicates while preserving search order.
    return list(
        dict.fromkeys(queries)
    )