from src.planning.cooking_schedule import build_cooking_schedule


def meal(recipe_id, day, meal_type):
    return {
        "recipe_id": recipe_id,
        "slot": {
            "slot_id": f"{day}_{meal_type}",
            "date": day,
            "meal_type": meal_type,
        },
    }


def test_two_sessions_cover_four_meals():
    meals = [
        meal("A", "2026-10-12", "lunch"),
        meal("A", "2026-10-12", "dinner"),
        meal("B", "2026-10-13", "lunch"),
        meal("B", "2026-10-13", "dinner"),
    ]

    result = build_cooking_schedule(
        selected_meals=meals,
        max_sessions=2,
    )

    assert result["valid"] is True
    assert result["session_count"] == 2
    assert sum(s["portions_prepared"] for s in result["sessions"]) == 4


def test_frequency_violation():
    meals = [
        meal("A", "2026-10-12", "lunch"),
        meal("B", "2026-10-13", "lunch"),
        meal("C", "2026-10-14", "lunch"),
    ]

    result = build_cooking_schedule(
        selected_meals=meals,
        max_sessions=2,
    )

    assert result["valid"] is False
    assert result["session_count"] == 3


def test_same_recipe_requires_new_session_after_storage_window():
    meals = [
        meal("A", "2026-10-12", "lunch"),
        meal("A", "2026-10-16", "lunch"),
    ]

    result = build_cooking_schedule(
        selected_meals=meals,
        max_sessions=1,
    )

    assert result["session_count"] == 2
    assert result["valid"] is False
