"""Minimal batch-cooking schedule for selected meals."""

from collections import defaultdict
from datetime import date


def build_cooking_schedule(
    selected_meals: list[dict],
    max_sessions: int,
    max_storage_days: int = 1,
) -> dict:
    if not isinstance(max_sessions, int) or isinstance(max_sessions, bool):
        raise ValueError("Cooking sessions must be an integer")

    if max_sessions < 1:
        raise ValueError("Cooking sessions must be at least 1")

    if max_storage_days < 0:
        raise ValueError("Storage days cannot be negative")

    grouped = defaultdict(list)

    for meal in selected_meals:
        slot = meal["slot"]
        grouped[meal["recipe_id"]].append(
            {
                "slot_id": slot["slot_id"],
                "date": date.fromisoformat(slot["date"]),
            }
        )

    sessions = []

    for recipe_id, meals in sorted(grouped.items()):
        meals.sort(key=lambda x: (x["date"], x["slot_id"]))

        batch = []

        def finish_batch(items):
            if not items:
                return

            sessions.append(
                {
                    "session_id": f"B{len(sessions) + 1:03d}",
                    "recipe_id": recipe_id,
                    "cook_date": items[0]["date"].isoformat(),
                    "portions_prepared": len(items),
                    "meal_slot_ids": [item["slot_id"] for item in items],
                }
            )

        for meal in meals:
            if not batch:
                batch = [meal]
                continue

            age = (meal["date"] - batch[0]["date"]).days

            if age <= max_storage_days:
                batch.append(meal)
            else:
                finish_batch(batch)
                batch = [meal]

        finish_batch(batch)

    sessions.sort(key=lambda s: (s["cook_date"], s["session_id"]))

    # Enforce the limit within each calendar week.
    weekly_counts = defaultdict(int)

    for session in sessions:
        d = date.fromisoformat(session["cook_date"])
        iso_year, iso_week, _ = d.isocalendar()
        weekly_counts[f"{iso_year}-W{iso_week:02d}"] += 1

    violations = {
        week: count for week, count in weekly_counts.items() if count > max_sessions
    }

    return {
        "sessions": sessions,
        "session_count": len(sessions),
        "weekly_session_counts": dict(weekly_counts),
        "max_sessions_per_week": max_sessions,
        "valid": not violations,
        "violations": violations,
        "storage_assumption_days": max_storage_days,
    }
