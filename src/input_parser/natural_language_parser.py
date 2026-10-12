"""Member 3: Natural-language -> validated User State parser.



The module keeps the team's existing User State contract unchanged.

It supports an injected LLM callable and includes a deterministic

fallback for offline testing.



Important rule:

Unknown pantry quantities remain None.

The parser never invents a quantity or unit that the user did not provide.

"""

from __future__ import annotations


import json

import re

from copy import deepcopy

from dataclasses import dataclass, field

from typing import Any, Callable, Mapping

USER_STATE_FIELDS = (
    "budget",
    "cook_frequency",
    "cook_time_preference_hrs",
    "preferred_cuisines",
    "dietary_restrictions",
    "allergies",
    "preferred_meal_types",
    "preferred_ingredients",
    "disliked_ingredients",
    "budget_flexible",
    "ingredient_availability",
)


LIST_FIELDS = {
    "preferred_cuisines",
    "dietary_restrictions",
    "allergies",
    "preferred_meal_types",
    "preferred_ingredients",
    "disliked_ingredients",
}


DEFAULT_STATE = {
    "budget": None,
    "cook_frequency": None,
    "cook_time_preference_hrs": None,
    "preferred_cuisines": [],
    "dietary_restrictions": [],
    "allergies": [],
    "preferred_meal_types": [],
    "preferred_ingredients": [],
    "disliked_ingredients": [],
    "budget_flexible": False,
    "ingredient_availability": {},
}


@dataclass
class UserStateSchema:

    budget: float | None = None

    cook_frequency: int | None = None

    cook_time_preference_hrs: float | None = None

    preferred_cuisines: list[str] = field(default_factory=list)

    dietary_restrictions: list[str] = field(default_factory=list)

    allergies: list[str] = field(default_factory=list)

    preferred_meal_types: list[str] = field(default_factory=list)

    preferred_ingredients: list[str] = field(default_factory=list)

    disliked_ingredients: list[str] = field(default_factory=list)

    budget_flexible: bool = False

    ingredient_availability: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:

        return {
            "budget": self.budget,
            "cook_frequency": self.cook_frequency,
            "cook_time_preference_hrs": (self.cook_time_preference_hrs),
            "preferred_cuisines": (self.preferred_cuisines),
            "dietary_restrictions": (self.dietary_restrictions),
            "allergies": self.allergies,
            "preferred_meal_types": (self.preferred_meal_types),
            "preferred_ingredients": (self.preferred_ingredients),
            "disliked_ingredients": (self.disliked_ingredients),
            "budget_flexible": self.budget_flexible,
            "ingredient_availability": (self.ingredient_availability),
        }


@dataclass
class ValidationResult:

    valid: bool

    data: dict[str, Any]

    errors: list[str] = field(default_factory=list)

    missing_fields: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:

        result = {
            "valid": self.valid,
            "data": self.data,
        }

        if self.errors:

            result["errors"] = self.errors

        if self.missing_fields:

            result["missing_fields"] = self.missing_fields

        return result


def build_ollama_prompt(
    user_text: str,
) -> str:
    """Build strict JSON extraction prompt for an LLM."""

    return f"""

You are the natural-language input parser for an

intelligent adaptive meal planner.



Extract ONLY information explicitly stated by the user.



Return ONE valid JSON object using exactly these fields:



{json.dumps(DEFAULT_STATE, indent=2)}



Rules:



1. Do not invent values.

2. Unknown scalar values must be null.

3. Unknown pantry quantities must be null.

4. Example:

   "I have rice"

   -> "rice": null



5. If quantity and unit are explicitly stated:

   "I have 2 kg potatoes"

   -> "potatoes": {{

        "quantity": 2,

        "unit": "kg"

      }}



6. Convert cooking time to hours.

   Example:

   30 minutes -> 0.5



7. Convert explicit weekly cooking frequency.

   Example:

   3 times a week -> 3



8. Allergies belong in "allergies".



9. Vegetarian, vegan, halal, etc.

   belong in "dietary_restrictions".



10. Cuisine preferences such as

    "I prefer Asian food" belong in

    "preferred_cuisines", not

    "preferred_ingredients".



11. Pantry descriptions such as

    "2 kg of rice" should store

    "rice" as the ingredient name.



12. Do not add explanations.



13. Do not add extra JSON fields.



User input:

{user_text}

"""


class UserInputParser:
    """Convert natural-language input into the project's User State schema."""

    def __init__(
        self,
        llm: Callable[[str], str] | None = None,
    ) -> None:

        self.llm = llm

    def parse(
        self,
        user_text: str,
    ) -> ValidationResult:

        if not isinstance(user_text, str) or not user_text.strip():

            return ValidationResult(
                valid=False,
                data=deepcopy(DEFAULT_STATE),
                errors=["user_text must be a non-empty string"],
            )

        # Use LLM if supplied

        if self.llm is not None:

            try:

                raw_response = self.llm(build_ollama_prompt(user_text))

                extracted = self._decode_llm_json(raw_response)

                return self.validate(extracted)

            except (
                ValueError,
                TypeError,
                json.JSONDecodeError,
            ) as exc:

                # Deterministic fallback

                fallback = self._deterministic_extract(user_text)

                result = self.validate(fallback)

                result.errors.insert(
                    0,
                    f"LLM extraction failed; " f"fallback used: {exc}",
                )

                return result

        # Offline / testing mode

        return self.validate(self._deterministic_extract(user_text))

    def validate(
        self,
        data: Mapping[str, Any],
        required_fields: list[str] | None = None,
    ) -> ValidationResult:

        if not isinstance(data, Mapping):

            return ValidationResult(
                valid=False,
                data=deepcopy(DEFAULT_STATE),
                errors=["Parser output must be a JSON object"],
            )

        normalized = deepcopy(DEFAULT_STATE)

        errors = []

        # -----------------------------

        # Check unknown fields

        # -----------------------------

        for key in data:

            if key not in USER_STATE_FIELDS:

                errors.append(f"unknown field: {key}")

        # -----------------------------

        # Copy known fields

        # -----------------------------

        for key in USER_STATE_FIELDS:

            if key in data:

                normalized[key] = data[key]

        # -----------------------------

        # Budget

        # -----------------------------

        if normalized["budget"] is not None:

            if isinstance(
                normalized["budget"],
                bool,
            ) or not isinstance(
                normalized["budget"],
                (int, float),
            ):

                errors.append("budget must be a number or null")

            elif normalized["budget"] < 0:

                errors.append("budget cannot be negative")

            else:

                normalized["budget"] = float(normalized["budget"])

        # -----------------------------

        # Cooking frequency

        # -----------------------------

        if normalized["cook_frequency"] is not None:

            if isinstance(
                normalized["cook_frequency"],
                bool,
            ) or not isinstance(
                normalized["cook_frequency"],
                int,
            ):

                errors.append("cook_frequency must be " "an integer or null")

            elif normalized["cook_frequency"] < 1:

                errors.append("cook_frequency must be at least 1")

        # -----------------------------

        # Cooking time

        # -----------------------------

        if normalized["cook_time_preference_hrs"] is not None:

            if isinstance(
                normalized["cook_time_preference_hrs"],
                bool,
            ) or not isinstance(
                normalized["cook_time_preference_hrs"],
                (int, float),
            ):

                errors.append("cook_time_preference_hrs " "must be a number or null")

            elif normalized["cook_time_preference_hrs"] < 0:

                errors.append("cook_time_preference_hrs " "cannot be negative")

        # -----------------------------

        # Budget flexible

        # -----------------------------

        if not isinstance(
            normalized["budget_flexible"],
            bool,
        ):

            errors.append("budget_flexible must be boolean")

        # -----------------------------

        # List fields

        # -----------------------------

        for key in LIST_FIELDS:

            value = normalized[key]

            if not isinstance(value, list) or not all(
                isinstance(x, str) for x in value
            ):

                errors.append(f"{key} must be a list of strings")

            else:

                normalized[key] = _clean_list(value)

        # -----------------------------

        # Pantry

        # -----------------------------

        pantry = normalized["ingredient_availability"]

        if not isinstance(pantry, dict):

            errors.append("ingredient_availability " "must be an object")

        else:

            clean_pantry = {}

            for ingredient, value in pantry.items():

                if (
                    not isinstance(
                        ingredient,
                        str,
                    )
                    or not ingredient.strip()
                ):

                    errors.append(
                        "pantry ingredient names " "must be non-empty strings"
                    )

                    continue

                ingredient = ingredient.strip()

                # Unknown quantity

                if value is None:

                    clean_pantry[ingredient] = None

                # Known quantity

                elif isinstance(value, dict):

                    quantity = value.get("quantity")

                    unit = value.get("unit")

                    if isinstance(
                        quantity,
                        bool,
                    ) or not isinstance(
                        quantity,
                        (int, float),
                    ):

                        errors.append(
                            f"invalid quantity " f"for pantry item: " f"{ingredient}"
                        )

                        continue

                    if quantity < 0:

                        errors.append(
                            f"negative quantity " f"for pantry item: " f"{ingredient}"
                        )

                        continue

                    if (
                        not isinstance(
                            unit,
                            str,
                        )
                        or not unit.strip()
                    ):

                        errors.append(
                            f"missing unit " f"for pantry item: " f"{ingredient}"
                        )

                        continue

                    clean_pantry[ingredient] = {
                        "quantity": float(quantity),
                        "unit": unit.strip().lower(),
                    }

                else:

                    errors.append(
                        f"pantry value for "
                        f"{ingredient} must be "
                        f"null or quantity/unit object"
                    )

            normalized["ingredient_availability"] = clean_pantry

        # -----------------------------

        # Required fields

        # -----------------------------

        missing_fields = []

        for field_name in required_fields or []:

            value = normalized.get(field_name)

            if value is None or value == [] or value == {}:

                missing_fields.append(field_name)

        if missing_fields:

            errors.append("required fields are missing: " + ", ".join(missing_fields))

        return ValidationResult(
            valid=not errors,
            data=normalized,
            errors=errors,
            missing_fields=missing_fields,
        )

    @staticmethod
    def _decode_llm_json(
        raw: str,
    ) -> dict[str, Any]:

        if not isinstance(raw, str):

            raise TypeError("LLM response must be a string")

        text = raw.strip()

        # Remove markdown code block

        if text.startswith("```"):

            text = re.sub(
                r"^```(?:json)?\s*|\s*```$",
                "",
                text,
                flags=re.I | re.S,
            ).strip()

        start = text.find("{")

        end = text.rfind("}")

        if start < 0 or end < start:

            raise ValueError("LLM response did not contain " "a JSON object")

        obj = json.loads(text[start : end + 1])

        if not isinstance(obj, dict):

            raise ValueError("LLM response JSON must be an object")

        return obj

    @staticmethod
    def _deterministic_extract(
        text: str,
    ) -> dict[str, Any]:

        lower = text.lower()

        result = deepcopy(DEFAULT_STATE)

        # -----------------------------

        # Budget

        # -----------------------------

        budget_patterns = [
            # Explicit budget ceilings: "under $30", "up to S$50",
            # "less than $40", "at most $25", or "within $60".
            r"\b(?:under|below|less than|at most|up to|within)\s+"
            r"(?:s\s*)?\$\s*(\d+(?:\.\d+)?)",
            # "I have $50" or "I have S$50".
            r"\b(?:have|has)\s+" r"(?:s\s*)?\$\s*(\d+(?:\.\d+)?)",
            # "my budget is $50" or "budget of S$50".
            r"\bbudget\s*" r"(?:is|of|:)?\s*" r"(?:s\s*)?\$\s*(\d+(?:\.\d+)?)",
            # "$50 budget", "$50 to spend", "$50 for ...".
            r"(?:s\s*)?\$\s*(\d+(?:\.\d+)?)" r"\s*(?:budget|to spend|for)",
        ]

        for pattern in budget_patterns:

            match = re.search(
                pattern,
                lower,
            )

            if match:

                result["budget"] = float(match.group(1))

                break

        # -----------------------------

        # Flexible budget

        # -----------------------------

        if re.search(
            r"budget.{0,20}" r"(?:flexible|can stretch|stretch)",
            lower,
        ):

            result["budget_flexible"] = True

        elif re.search(
            r"(?:flexible|can stretch|stretch)" r".{0,20}budget",
            lower,
        ):

            result["budget_flexible"] = True

        # -----------------------------

        # Cooking time

        # -----------------------------

        time_match = re.search(
            r"(?:cook|cooking)"
            r"[^.!?]{0,40}?"
            r"(\d+(?:\.\d+)?)"
            r"\s*(minutes?|mins?|hours?|hrs?)",
            lower,
        )

        if time_match:

            value = float(time_match.group(1))

            unit = time_match.group(2)

            if unit.startswith("min"):

                result["cook_time_preference_hrs"] = value / 60

            else:

                result["cook_time_preference_hrs"] = value

        # -----------------------------

        # Cooking frequency

        # -----------------------------

        frequency_patterns = [
            r"\b(?:cook|cooking)\s+"
            r"(once|twice|one|two|three|four|five|six|seven)"
            r"(?:\s+times?)?\s+(?:a|per)\s+week\b",
            r"\b(?:cook|cooking)\s+" r"(\d+)\s*(?:times?|x)\s*(?:a|per)\s+week\b",
            r"\b(\d+)\s*(?:times?|x)\s*(?:a|per)\s+week\b",
        ]

        frequency_words = {
            "once": 1,
            "one": 1,
            "twice": 2,
            "two": 2,
            "three": 3,
            "four": 4,
            "five": 5,
            "six": 6,
            "seven": 7,
        }

        for pattern in frequency_patterns:
            match = re.search(pattern, lower)

            if match:
                value = match.group(1)
                result["cook_frequency"] = (
                    int(value) if value.isdigit() else frequency_words[value]
                )
                break
        # -----------------------------

        # Dietary restrictions

        # -----------------------------

        dietary = [
            ("vegan", "Vegan"),
            ("vegetarian", "Vegetarian"),
            ("halal", "Halal"),
            ("keto", "Keto"),
            (
                "gluten[- ]free",
                "Gluten-Free",
            ),
            (
                "dairy[- ]free",
                "Dairy-Free",
            ),
        ]

        for pattern, value in dietary:

            if re.search(
                r"\b" + pattern + r"\b",
                lower,
            ):

                result["dietary_restrictions"].append(value)

        # -----------------------------

        # Allergies

        # -----------------------------

        allergy_match = re.search(
            r"allerg(?:ic|y)" r"[^.!?]{0,80}?" r"\bto\s+([^.!?,;]+)",
            lower,
        )

        if allergy_match:

            raw = allergy_match.group(1)

            for item in re.split(
                r"\s*(?:,|\band\b)\s*",
                raw,
            ):

                item = item.strip()

                if item:

                    result["allergies"].append(_title(item))

        # -----------------------------

        # Cuisine

        # -----------------------------

        cuisines = {
            "asian": "Asian",
            "indian": "Indian",
            "italian": "Italian",
            "chinese": "Chinese",
            "japanese": "Japanese",
            "mexican": "Mexican",
            "korean": "Korean",
            "mediterranean": "Mediterranean",
        }

        for token, value in cuisines.items():

            if re.search(
                r"\b" + token + r"\b",
                lower,
            ) and re.search(
                r"(?:prefer|like|want|cuisine|food)",
                lower,
            ):

                result["preferred_cuisines"].append(value)

        # -----------------------------

        # Meal type

        # -----------------------------

        meal_types = {
            "breakfast": "Breakfast",
            "lunch": "Lunch",
            "dinner": "Dinner",
            "snack": "Snack",
        }

        for token, value in meal_types.items():

            if re.search(
                r"\b" + token + r"\b",
                lower,
            ):

                result["preferred_meal_types"].append(value)

        # -----------------------------

        # Preferred ingredients

        # -----------------------------

        preferred = re.search(
            r"(?:prefer|love|like)" r"\s+([^.!?]+)",
            lower,
        )

        if preferred:

            preferred_text = preferred.group(1).strip()

            # Cuisine phrases such as:

            # "prefer Asian food"

            # "like Italian cuisine"

            # are not ingredients.

            is_cuisine_phrase = bool(
                re.search(
                    r"\b(?:food|cuisine)\b",
                    preferred_text,
                    re.I,
                )
            )

            if not is_cuisine_phrase:

                result["preferred_ingredients"].extend(_split_items(preferred_text))

        # -----------------------------

        # Disliked ingredients

        # -----------------------------

        disliked = re.search(
            r"(?:dislike|don't like|" r"do not like|hate)" r"\s+([^.!?]+)",
            lower,
        )

        if disliked:

            result["disliked_ingredients"].extend(_split_items(disliked.group(1)))

        # -----------------------------

        # Pantry

        # -----------------------------

        pantry_pattern = re.compile(
            r"(?:i\s+have|have|"
            r"in\s+my\s+"
            r"(?:pantry|fridge|kitchen))"
            r"\s+(.+?)(?:[.!?]|$)",
            re.I,
        )

        for pantry_match in pantry_pattern.finditer(lower):

            pantry_text = pantry_match.group(1)

            # Ignore budget statements such as:

            # "I have $50 for the next three days."

            #

            # This is a budget statement, not a pantry item.

            if re.search(
                r"\$\s*\d+(?:\.\d+)?",
                pantry_text,
            ):

                continue

            pantry_text = re.split(
                r"\s+(?:and\s+)?"
                r"(?:i'm|i am|my budget|"
                r"i cook|i prefer|"
                r"i dislike|i don't)\b",
                pantry_text,
                maxsplit=1,
            )[0]

            for item in _split_items(pantry_text):

                parsed = _parse_pantry_item(item)

                if parsed:

                    name, quantity = parsed

                    result["ingredient_availability"][name] = quantity

        # -----------------------------

        # Remove duplicate values

        # -----------------------------

        for key in LIST_FIELDS:

            result[key] = _unique(result[key])

        return result


def _parse_pantry_item(
    item: str,
) -> tuple[str, Any] | None:

    item = item.strip(" .")

    # Remove common grammatical words when

    # they appear before an ingredient.

    #

    # Examples:

    # "some tofu" -> "tofu"

    # "a tomato"  -> "tomato"

    # "an apple"  -> "apple"

    item = re.sub(
        r"^(?:some|a|an)\s+",
        "",
        item,
        flags=re.I,
    )

    # -----------------------------

    # Known quantity

    # -----------------------------

    match = re.match(
        r"^(\d+(?:\.\d+)?)\s*"
        r"(kg|kgs|g|grams?|ml|"
        r"millilit(?:er|re)s?|"
        r"l|lit(?:er|re)s?|"
        r"cups?|tbsp|tablespoons?|"
        r"tsp|teaspoons?|"
        r"pieces?|pcs?|count|cloves?)"
        r"\s+(.+)$",
        item,
        flags=re.I,
    )

    if match:

        quantity = float(match.group(1))

        unit = _normalize_unit(match.group(2))

        ingredient_name = match.group(3).strip()

        # Remove "of" after quantity/unit.

        #

        # Example:

        # "2 kg of rice" -> "rice"

        ingredient_name = re.sub(
            r"^of\s+",
            "",
            ingredient_name,
            flags=re.I,
        ).strip()

        if not ingredient_name:

            return None

        return (
            _title(ingredient_name),
            {
                "quantity": quantity,
                "unit": unit,
            },
        )

    # -----------------------------

    # Unknown quantity

    # -----------------------------

    if item and re.fullmatch(
        r"[a-z][a-z\s-]{1,50}",
        item,
        flags=re.I,
    ):

        return (
            _title(item),
            None,
        )

    return None


def _normalize_unit(
    unit: str,
) -> str:

    aliases = {
        "kgs": "kg",
        "grams": "g",
        "gram": "g",
        "milliliters": "ml",
        "millilitres": "ml",
        "milliliter": "ml",
        "millilitre": "ml",
        "liters": "l",
        "litres": "l",
        "liter": "l",
        "litre": "l",
        "cups": "cup",
        "tablespoons": "tablespoon",
        "tbsp": "tablespoon",
        "teaspoons": "teaspoon",
        "tsp": "teaspoon",
        "pieces": "piece",
        "pcs": "piece",
        "counts": "count",
        "cloves": "clove",
    }

    return aliases.get(
        unit.lower(),
        unit.lower(),
    )


def _split_items(
    text: str,
) -> list[str]:

    items = re.split(
        r"\s*(?:,|\band\b)\s*",
        text.strip(),
    )

    cleaned = []

    for item in items:

        item = item.strip(" .")

        if item:

            cleaned.append(_title(item))

    return cleaned


def _title(
    text: str,
) -> str:

    return " ".join(word.capitalize() for word in text.split())


def _clean_list(
    values: list[str],
) -> list[str]:

    return _unique([x.strip() for x in values if x.strip()])


def _unique(
    values: list[str],
) -> list[str]:

    seen = set()

    result = []

    for value in values:

        marker = value.casefold()

        if marker not in seen:

            seen.add(marker)

            result.append(value)

    return result
