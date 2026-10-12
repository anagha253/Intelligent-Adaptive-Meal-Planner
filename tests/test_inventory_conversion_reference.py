import pytest
from src.grocery import ingredient_conversions as conversions
from src.state.inventory_state import consume_inventory, normalize_inventory


def test_existing_exact_conversion():
    result = consume_inventory(normalize_inventory({"rice": "1 kg"}),
                               [{"ingredient_name": "rice", "quantity": 250, "unit": "g"}])
    assert result["rice"]["quantity"] == pytest.approx(0.75)


def test_existing_ingredient_conversion():
    result = consume_inventory(normalize_inventory({"salt": "50 g"}),
                               [{"ingredient_name": "salt", "quantity": 1, "unit": "pinch"}])
    assert result["salt"]["quantity"] == pytest.approx(49.65)
    assert result["salt"]["conversion_status"] == "estimated"


def test_approved_reference_conversion(monkeypatch):
    monkeypatch.setattr(conversions, "_mass_reference", lambda: {("cauliflower", "head"): 600.0})
    result = consume_inventory(normalize_inventory({"cauliflower": "1 head"}),
                               [{"ingredient_name": "cauliflower", "quantity": 125, "unit": "g"}])
    assert result["cauliflower"]["quantity"] == pytest.approx(475 / 600)


def test_ambiguous_count_remains_unresolved():
    with pytest.raises(ValueError, match="Incompatible inventory units"):
        consume_inventory(normalize_inventory({"cumin": "50 g"}),
                          [{"ingredient_name": "cumin", "quantity": 1, "unit": "count"}])


def test_insufficient_inventory_is_not_hidden():
    with pytest.raises(ValueError, match="Insufficient inventory"):
        consume_inventory(normalize_inventory({"salt": "0.1 g"}),
                          [{"ingredient_name": "salt", "quantity": 1, "unit": "pinch"}])
