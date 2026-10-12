"""Conservative ingredient-specific recipe-to-mass estimates.

All results are estimates, not exact retail package conversions.
"""
from dataclasses import dataclass
import ast
import csv
from functools import lru_cache
from pathlib import Path
import math


@dataclass(frozen=True)
class IngredientConversion:
    source: str
    grams_per_tablespoon: float | None = None
    grams_per_sprig: float | None = None
    preparation: str | None = None
    estimated: bool = True
    grams_per_head: float | None = None
    grams_per_piece: float | None = None
    grams_per_clove: float | None = None
    grams_per_wedge: float | None = None
    grams_per_pinch: float | None = None
    grams_per_bunch: float | None = None
    grams_per_cup: float | None = None
    grams_per_bulb: float | None = None
    grams_per_pack: float | None = None

_SOURCE = "provisional culinary estimate; verify for production"

INGREDIENT_CONVERSIONS = {
    "sugar": IngredientConversion(_SOURCE, grams_per_tablespoon=12.5),
    "white sugar": IngredientConversion(_SOURCE, grams_per_tablespoon=12.5),
    "granulated sugar": IngredientConversion(_SOURCE, grams_per_tablespoon=12.5),
    "white granulated sugar": IngredientConversion(_SOURCE, grams_per_tablespoon=12.5),
    "butter lettuce": IngredientConversion(_SOURCE, grams_per_head=150),
    "butterhead lettuce": IngredientConversion(_SOURCE, grams_per_head=150),
    "lettuce": IngredientConversion(
        _SOURCE,
        grams_per_head=300,
        grams_per_cup=36,
    ),
    "garlic": IngredientConversion(_SOURCE, grams_per_clove=3),
    "lime": IngredientConversion(_SOURCE, grams_per_piece=65, grams_per_wedge=8),
    "fresh lime": IngredientConversion(_SOURCE, grams_per_piece=65, grams_per_wedge=8),
    "lemon": IngredientConversion(_SOURCE, grams_per_piece=100, grams_per_wedge=12),
    "firm tofu": IngredientConversion(_SOURCE, grams_per_piece=300),
    "tofu": IngredientConversion(_SOURCE, grams_per_piece=300),
    "carrot": IngredientConversion(_SOURCE, grams_per_tablespoon=9, grams_per_piece=70),
    "yellow onion": IngredientConversion(_SOURCE, grams_per_tablespoon=10, grams_per_piece=150),
    "onion": IngredientConversion(_SOURCE, grams_per_tablespoon=10, grams_per_piece=150),
    "green onion": IngredientConversion(_SOURCE,grams_per_tablespoon=6,grams_per_bunch=100),
    "spring onion": IngredientConversion(_SOURCE,grams_per_tablespoon=6,grams_per_bunch=100,),
    "zucchini": IngredientConversion(_SOURCE, grams_per_tablespoon=9, grams_per_piece=200),
    "mint": IngredientConversion(_SOURCE, grams_per_tablespoon=1.5, grams_per_sprig=1),
    "salt": IngredientConversion(_SOURCE, grams_per_tablespoon=18, grams_per_pinch=0.35),
    "kosher salt": IngredientConversion(_SOURCE, grams_per_tablespoon=15, grams_per_pinch=0.3),
    "fine sea salt": IngredientConversion(_SOURCE, grams_per_tablespoon=18, grams_per_pinch=0.35),
    "black pepper": IngredientConversion(_SOURCE, grams_per_tablespoon=7, grams_per_pinch=0.2),
    "garlic powder": IngredientConversion(_SOURCE, grams_per_tablespoon=9, grams_per_pinch=0.3),
    "hoisin sauce": IngredientConversion(_SOURCE, grams_per_tablespoon=17),
    "soy sauce": IngredientConversion(_SOURCE, grams_per_tablespoon=16),
    "mustard seed": IngredientConversion(
        _SOURCE,
        grams_per_tablespoon=9.0,
        grams_per_pinch=0.3,
    ),
    "mustard seeds": IngredientConversion(
        _SOURCE,
        grams_per_tablespoon=9.0,
        grams_per_pinch=0.3,
    ),
    "cucumber": IngredientConversion(
        _SOURCE,
        grams_per_piece=250,
    ),
    "masa harina": IngredientConversion(
    _SOURCE,
    grams_per_cup=120,
    ),
    "black beans": IngredientConversion(
       _SOURCE,
        grams_per_cup=172,
    ),
        # Additional ingredient-specific estimates
    "plum tomato": IngredientConversion(
        _SOURCE,
        grams_per_piece=65,
    ),
    "jack cheese": IngredientConversion(
        _SOURCE,
        grams_per_tablespoon=7,
    ),
    "sour cream": IngredientConversion(
        _SOURCE,
        grams_per_tablespoon=15,
    ),
    "cilantro": IngredientConversion(
        _SOURCE,
        grams_per_tablespoon=1,
        grams_per_bunch=30,
    ),
    "jalapeno": IngredientConversion(
        _SOURCE,
        grams_per_piece=15,
    ),
    "kidney bean": IngredientConversion(
        _SOURCE,
        grams_per_cup=175,
    ),
    "urad dal": IngredientConversion(
        _SOURCE,
        grams_per_tablespoon=12,
    ),
    "curry leaf": IngredientConversion(
        _SOURCE,
        grams_per_piece=0.2,
        grams_per_bunch=20,
    ),
    "garlic": IngredientConversion(
    _SOURCE,
    grams_per_clove=3,
    grams_per_bulb=30,
    grams_per_pack=90,
    ),
}


def estimate_ingredient_mass(
    ingredient_name: str, quantity: float, unit: str
) -> tuple[float, str] | None:
    """Return estimated grams for supported ingredient/unit pairs only."""
    if not ingredient_name or not unit or quantity is None:
        return None
    try:
        quantity = float(quantity)
    except (ValueError, TypeError):
        return None
    if not math.isfinite(quantity) or quantity <= 0:
        return None

    name = " ".join(ingredient_name.strip().lower().split())
    measure = unit.strip().lower()
    conversion = INGREDIENT_CONVERSIONS.get(name)
    if conversion is None:
        canonical = _mapping_aliases().get(name)
        if canonical:
            conversion = INGREDIENT_CONVERSIONS.get(canonical)
    if conversion is None:
        return None

    mapping = {
        "tablespoon": (conversion.grams_per_tablespoon, 1),
        "tablespoons": (conversion.grams_per_tablespoon, 1),
        "tbsp": (conversion.grams_per_tablespoon, 1),
        "teaspoon": (conversion.grams_per_tablespoon, 1 / 3),
        "teaspoons": (conversion.grams_per_tablespoon, 1 / 3),
        "tsp": (conversion.grams_per_tablespoon, 1 / 3),
        "head": (conversion.grams_per_head, 1),
        "heads": (conversion.grams_per_head, 1),
        "piece": (conversion.grams_per_piece, 1),
        "pieces": (conversion.grams_per_piece, 1),
        "pc": (conversion.grams_per_piece, 1),
        "pcs": (conversion.grams_per_piece, 1),
        "count": (conversion.grams_per_piece, 1),
        "unit": (conversion.grams_per_piece, 1),
        "each": (conversion.grams_per_piece, 1),
        "clove": (conversion.grams_per_clove, 1),
        "cloves": (conversion.grams_per_clove, 1),
        "wedge": (conversion.grams_per_wedge, 1),
        "wedges": (conversion.grams_per_wedge, 1),
        "pinch": (conversion.grams_per_pinch, 1),
        "pinches": (conversion.grams_per_pinch, 1),
        "sprig": (conversion.grams_per_sprig, 1),
        "sprigs": (conversion.grams_per_sprig, 1),
        "bunch": (conversion.grams_per_bunch, 1),
        "bunches": (conversion.grams_per_bunch, 1),
        "cup": (conversion.grams_per_cup, 1),
        "cups": (conversion.grams_per_cup, 1),
        "bulb": (conversion.grams_per_bulb, 1),
        "bulbs": (conversion.grams_per_bulb, 1),
        "pack": (conversion.grams_per_pack, 1),
        "packs": (conversion.grams_per_pack, 1),
        
    }
    factor, multiplier = mapping.get(measure, (None, 1))
    if factor is None:
        return None
    return round(quantity * factor * multiplier, 4), "g"


@lru_cache(maxsize=1)
def _mapping_aliases() -> dict[str, str]:
    """Read existing recipe mapping aliases, without inferring missing weights.

    Ambiguous aliases are discarded to avoid cross-ingredient deductions.
    """
    mapping_path = (Path(__file__).resolve().parents[2] / "data" / "processed"
                    / "recipe_ingredient_mapping.csv")
    aliases: dict[str, str] = {}
    ambiguous: set[str] = set()
    try:
        with mapping_path.open(newline="", encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                canonical = " ".join((row.get("ingredient_name") or "").lower().split())
                if not canonical:
                    continue
                names = [canonical]
                try:
                    listed = ast.literal_eval(row.get("alias_name") or "[]")
                    if isinstance(listed, list):
                        names.extend(x for x in listed if isinstance(x, str))
                except (ValueError, SyntaxError):
                    pass
                for raw in names:
                    alias = " ".join(raw.lower().split())
                    if alias in aliases and aliases[alias] != canonical:
                        ambiguous.add(alias)
                    else:
                        aliases[alias] = canonical
    except (OSError, csv.Error):
        return {}
    return {key: value for key, value in aliases.items() if key not in ambiguous}
