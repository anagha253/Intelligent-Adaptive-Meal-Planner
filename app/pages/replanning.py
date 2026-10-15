
"""Adaptive replanning: completed meals, prepared leftovers, and skipped slots.

Customer-facing actions:
1. Mark meals already eaten.
2. Record prepared leftovers for eligible meals.
3. Skip an upcoming meal and optionally approve leftovers.

Budget, dietary preferences, and pantry quantities are not edited here.
"""

from datetime import date
from uuid import uuid4

import streamlit as st

from app.components.presentation import (
    friendly_date,
    show_meals,
)
from app.components.state_persistence import (
    get_workspace_id,
    save_ui_state,
)
from app.components.background_jobs import (
    start_background_job,
    read_background_job,
)
from app.components.planning_jobs import read_job
from app.components.recipe_lookup import get_recipe_name


# ============================================================
# HELPERS
# ============================================================

def slot_of(meal):
    return meal.get("slot") or {}


def slot_id_of(meal):
    slot = slot_of(meal)
    return slot.get("slot_id") or meal.get("slot_id")


def day_of(meal):
    slot = slot_of(meal)
    return str(
        slot.get("date")
        or meal.get("date")
        or str(slot_id_of(meal) or "")[:10]
    )


def recipe_id_of(meal):
    decision = meal.get("decision") or {}

    return (
        meal.get("recipe_id")
        or decision.get("recipe_id")
        or decision.get("selected_recipe_id")
    )


def label_of(meal):
    """Display date, meal type and recipe name exactly once."""

    slot = slot_of(meal)

    recipe_name = get_recipe_name(
        recipe_id_of(meal)
    )

    meal_type = str(
        slot.get("meal_type")
        or meal.get("meal_type")
        or "Meal"
    ).title()

    return (
        f"{friendly_date(day_of(meal))}"
        f" · {meal_type}"
        f" — {recipe_name}"
    )


def get_leftovers(plan_state, plan):
    """Read current prepared leftovers."""

    if plan_state is not None:
        return list(
            getattr(
                plan_state,
                "prepared_leftovers",
                [],
            ) or []
        )

    return list(
        plan.get("prepared_leftovers") or []
    )


def skipped_slot_ids(plan, plan_state):
    """Collect skipped slot IDs from the result and PlanState."""

    skipped = set()

    for entry in plan.get("skipped_slots") or []:

        if isinstance(entry, dict):
            sid = entry.get("slot_id")
        else:
            sid = entry

        if sid:
            skipped.add(str(sid))

    if plan_state is not None:

        for entry in (
            getattr(plan_state, "skipped_slots", []) or []
        ):

            if isinstance(entry, dict):
                sid = entry.get("slot_id")
            else:
                sid = entry

            if sid:
                skipped.add(str(sid))

    return skipped


def valid_leftover(leftover):
    """Check basic availability for the approval dropdown."""

    try:
        servings = int(
            leftover.get("servings_remaining") or 0
        )

        expiry = date.fromisoformat(
            str(leftover.get("expires_on"))
        )

        return (
            servings > 0
            and bool(leftover.get("storage"))
            and expiry >= date.today()
            and bool(leftover.get("leftover_id"))
        )

    except (TypeError, ValueError):
        return False


# ============================================================
# PAGE HEADER
# ============================================================

st.title("Adjust your meal plan")

st.caption(
    "Mark meals eaten, record prepared leftovers, "
    "or skip an upcoming meal. "
    "Your budget and preferences remain unchanged."
)


# ============================================================
# LOAD CURRENT PLAN
# ============================================================

result = st.session_state.get("planner_result") or {}

plan = result.get("plan") or {}

meals = plan.get("selected_meals") or []

planner = st.session_state.get("live_planner")

plan_state = st.session_state.get("live_plan_state")

user_state = st.session_state.get("planner_user_state")

completed = set(
    st.session_state.get("completed_slot_ids") or []
)

workspace = get_workspace_id()


# ============================================================
# BACKGROUND GENERATION STATUS
# ============================================================

planning_id = st.session_state.get(
    "planning_job_id"
)

planning_job = (
    read_job(workspace, planning_id)
    if planning_id
    else None
)

is_generating = bool(
    planning_job
    and planning_job.get("status")
    in {"queued", "running"}
)


# ============================================================
# BACKGROUND REPLANNING STATUS
# ============================================================

replan_id = st.session_state.get(
    "replanning_job_id"
)

replan_job = (
    read_background_job(workspace, replan_id)
    if replan_id
    else None
)

is_replanning = bool(
    replan_job
    and replan_job.get("status")
    in {"queued", "running"}
)

locked = is_generating or is_replanning


if is_replanning:

    st.info(
        "Your remaining meals are being updated. "
        "You can visit other pages while replanning continues."
    )

    @st.fragment(run_every="3s")
    def watch_replanning():

        current_id = st.session_state.get(
            "replanning_job_id"
        )

        if not current_id:
            return

        current = read_background_job(
            workspace,
            current_id,
        )

        status = (
            current.get("status")
            if current
            else "unknown"
        )

        if status in {"queued", "running"}:

            with st.status(
                "Updating your remaining meals...",
                state="running",
            ):
                st.write(
                    f"Replanning status: {status.title()}"
                )

                st.caption(
                    "Checking automatically every 3 seconds."
                )

        elif status in {"completed", "failed"}:

            from app.components.background_status import (
                sync_background_jobs,
            )

            sync_background_jobs()

            st.rerun(scope="app")

        else:
            st.warning(
                "Replanning status is unavailable."
            )

    watch_replanning()


if st.session_state.get("replanning_error"):

    st.error(
        st.session_state["replanning_error"]
    )


if st.session_state.pop(
    "replanning_done",
    False,
):

    st.success(
        "Your meal plan has been updated."
    )


# ============================================================
# NO PLAN AVAILABLE
# ============================================================

if not meals:

    if is_generating:
        st.info(
            "Your meal plan is being prepared."
        )

    else:
        st.info(
            "No planned meals are available. "
            "Create a meal plan first."
        )


# ============================================================
# EXISTING PLAN
# ============================================================

else:

    can_replan = all(
        value is not None
        for value in (
            planner,
            plan_state,
            user_state,
        )
    )

    if not can_replan:

        st.warning(
            "Your saved meals are available, but "
            "adaptive replanning requires the live "
            "planning state."
        )

    skipped = skipped_slot_ids(
        plan,
        plan_state,
    )

    # ========================================================
    # 1. MARK MEALS ALREADY EATEN
    # ========================================================

    st.subheader("Mark meals already eaten")

    completion_options = {}

    for meal in meals:

        sid = slot_id_of(meal)

        if not sid or sid in skipped:
            continue

        completion_options[sid] = label_of(meal)

    with st.form("completed_meals_form"):

        selected_completed = st.multiselect(
            "Meals completed",
            options=list(completion_options.keys()),
            default=[
                sid
                for sid in completion_options
                if sid in completed
            ],
            format_func=lambda sid: (
                completion_options[sid]
            ),
            key=(
                "completed_select_"
                f"{st.session_state.get('completed_selection_revision', 0)}"
            ),
        )

        save_completed = st.form_submit_button(
            "Save completed meals",
            disabled=locked,
        )

    if save_completed:

        previous = set(completed)

        updated = set(
            selected_completed
        )

        st.session_state[
            "completed_slot_ids"
        ] = updated

        try:
            save_ui_state()

        except Exception as exc:

            st.session_state[
                "completed_slot_ids"
            ] = previous

            st.error(
                f"Could not save completed meals: {exc}"
            )

        else:

            completed = updated

            st.session_state[
                "completed_selection_revision"
            ] = (
                st.session_state.get(
                    "completed_selection_revision",
                    0,
                ) + 1
            )

            print(
                "[REPLAN COMPLETED MEALS SAVED]",
                sorted(completed),
                flush=True,
            )

            st.rerun()

    # ========================================================
    # 2. PREPARED LEFTOVERS
    # ========================================================

    st.divider()

    st.subheader("Prepared leftovers")

    st.caption(
        "Record only food that has already been cooked "
        "and safely stored. Leftovers are reused only "
        "when you explicitly approve them during replanning."
    )

    leftovers = get_leftovers(
        plan_state,
        plan,
    )

    if leftovers:

        for leftover in leftovers:

            if not isinstance(leftover, dict):
                continue

            recipe_name = get_recipe_name(
                leftover.get("recipe_id")
            )

            servings = leftover.get(
                "servings_remaining",
                0,
            )

            storage = str(
                leftover.get("storage")
                or "Not specified"
            ).replace("_", " ").title()

            expiry = leftover.get(
                "expires_on"
            )

            with st.container(border=True):

                st.markdown(
                    f"**{recipe_name}**"
                )

                col1, col2, col3 = st.columns(3)

                col1.metric(
                    "Servings",
                    servings,
                )

                col2.write(
                    f"**Storage:** {storage}"
                )

                col3.write(
                    "**Use by:** "
                    + (
                        friendly_date(expiry)
                        if expiry
                        else "Not specified"
                    )
                )

    else:

        st.caption(
            "No prepared leftovers recorded."
        )

    # ========================================================
    # 3. RECORD PREPARED LEFTOVERS
    # ========================================================

    if can_replan:

        recipe_options = {}

        for meal in meals:

            sid = slot_id_of(meal)

            # Completed and skipped meals cannot be
            # selected for new leftover recording.
            if (
                not sid
                or sid in completed
                or sid in skipped
            ):
                continue

            recipe_id = recipe_id_of(meal)

            if not recipe_id:
                continue

            recipe_options[sid] = {
                "recipe_id": str(recipe_id),
                "label": label_of(meal),
            }

        with st.expander(
            "Record prepared leftovers"
        ):

            if recipe_options:

                with st.form(
                    "record_leftovers_form"
                ):

                    selected_slot_id = st.selectbox(
                        "Cooked recipe",
                        options=list(
                            recipe_options.keys()
                        ),
                        format_func=lambda sid: (
                            recipe_options[sid]["label"]
                        ),
                    )

                    servings = st.number_input(
                        "Remaining cooked servings",
                        min_value=1,
                        step=1,
                        value=1,
                    )

                    prepared = st.date_input(
                        "Prepared on",
                        value=date.today(),
                    )

                    expires = st.date_input(
                        "Use by",
                        value=date.today(),
                    )

                    storage = st.selectbox(
                        "Storage",
                        [
                            "refrigerated",
                            "frozen",
                        ],
                    )

                    record = st.form_submit_button(
                        "Record leftovers",
                        disabled=locked,
                    )

                if record:

                    if expires < prepared:

                        st.error(
                            "Use-by date must not precede "
                            "the preparation date."
                        )

                    elif prepared > date.today():

                        st.error(
                            "Preparation date cannot be "
                            "in the future."
                        )

                    else:

                        try:

                            selected_recipe = (
                                recipe_options[
                                    selected_slot_id
                                ]
                            )

                            recipe_id = (
                                selected_recipe[
                                    "recipe_id"
                                ]
                            )

                            leftover_id = (
                                "L"
                                + uuid4().hex[:12].upper()
                            )

                            # Existing GC1 PlanState method.
                            plan_state.record_prepared_leftover(
                                leftover_id=leftover_id,
                                recipe_id=recipe_id,
                                servings_remaining=int(
                                    servings
                                ),
                                prepared_date=(
                                    prepared.isoformat()
                                ),
                                storage=storage,
                                expires_on=(
                                    expires.isoformat()
                                ),
                            )

                            # Preserve nutrition metadata.
                            selected_meal = next(
                                (
                                    meal
                                    for meal in meals
                                    if slot_id_of(meal)
                                    == selected_slot_id
                                ),
                                None,
                            )

                            if selected_meal:

                                nutrition = (
                                    (
                                        selected_meal.get(
                                            "decision"
                                        ) or {}
                                    ).get("recipe") or {}
                                )

                                if nutrition:

                                    plan_state.prepared_leftovers[
                                        -1
                                    ]["nutrition"] = nutrition

                            st.session_state[
                                "live_plan_state"
                            ] = plan_state

                            # Save a displayable snapshot.
                            if isinstance(
                                result.get("plan"),
                                dict,
                            ):

                                result["plan"][
                                    "prepared_leftovers"
                                ] = list(
                                    plan_state.prepared_leftovers
                                )

                            save_ui_state()

                            print(
                                "[LEFTOVER RECORDED]",
                                "recipe=",
                                recipe_id,
                                "servings=",
                                servings,
                                flush=True,
                            )

                            st.rerun()

                        except Exception as exc:

                            st.error(
                                "Could not record leftovers: "
                                f"{exc}"
                            )

            else:

                st.info(
                    "No eligible meals are available "
                    "for recording leftovers."
                )

    # ========================================================
    # 4. SKIP AN UPCOMING MEAL
    # ========================================================

    st.divider()

    st.subheader(
        "Skip an upcoming meal"
    )

    today = date.today()

    choices = {}

    for meal in meals:

        sid = slot_id_of(meal)

        if not sid:
            continue

        if sid in completed:
            continue

        if sid in skipped:
            continue

        try:
            upcoming = (
                date.fromisoformat(
                    day_of(meal)
                ) >= today
            )

        except (TypeError, ValueError):
            upcoming = False

        if not upcoming:
            continue

        choices[sid] = label_of(meal)

    # ========================================================
    # APPROVABLE PREPARED LEFTOVERS
    # ========================================================

    approved_leftovers = {}

    for leftover in get_leftovers(
        plan_state,
        plan,
    ):

        if not isinstance(leftover, dict):
            continue

        if not valid_leftover(leftover):
            continue

        leftover_id = leftover.get(
            "leftover_id"
        )

        if leftover_id:

            approved_leftovers[
                leftover_id
            ] = leftover

    # ========================================================
    # SKIP FORM
    # ========================================================

    if choices:

        with st.form(
            "skip_meal_form"
        ):

            selected_slot_id = st.selectbox(
                "Meal to skip",
                options=list(
                    choices.keys()
                ),
                format_func=lambda sid: (
                    choices[sid]
                ),
            )

            if approved_leftovers:

                approvals = st.multiselect(
                    "Approve prepared leftovers "
                    "for eligible remaining meals "
                    "(optional)",
                    options=list(
                        approved_leftovers.keys()
                    ),
                    format_func=lambda lid: (
                        f"{get_recipe_name(approved_leftovers[lid].get('recipe_id'))}"
                        f" · {approved_leftovers[lid].get('servings_remaining', 0)} serving(s)"
                        f" · Use by {friendly_date(approved_leftovers[lid].get('expires_on'))}"
                    ),
                )

            else:

                approvals = []

            st.caption(
                "The selected meal slot will be skipped. "
                "Completed meals stay unchanged. "
                "Approved leftovers may be allocated "
                "to other unfinished meal slots."
            )

            submit_skip = st.form_submit_button(
                "Skip meal and update plan",
                disabled=(
                    locked
                    or not can_replan
                ),
            )

        if submit_skip:

            try:

                job_id = start_background_job(
                    workspace,
                    "replan",
                    planner=planner,
                    user_state=user_state,
                    plan_state=plan_state,
                    slot_id=selected_slot_id,
                    completed=set(completed),
                    approved_leftover_ids=list(
                        approvals
                    ),
                )

                st.session_state[
                    "replanning_job_id"
                ] = job_id

                st.session_state[
                    "replanning_error"
                ] = None

                print(
                    "[REPLAN UI SUBMITTED]",
                    "job=",
                    job_id,
                    "slot=",
                    selected_slot_id,
                    "approved_leftovers=",
                    len(approvals),
                    flush=True,
                )

                save_ui_state()

                st.rerun()

            except Exception as exc:

                st.error(
                    "Could not start replanning: "
                    f"{exc}"
                )

    else:

        st.info(
            "There are no upcoming uncompleted "
            "meals available to skip."
        )

    # ========================================================
    # 5. CURRENT AND COMPLETED MEALS
    # ========================================================

    st.divider()

    upcoming_display = [
        meal
        for meal in meals
        if slot_id_of(meal) not in completed
        and slot_id_of(meal) not in skipped
    ]

    completed_display = [
        meal
        for meal in meals
        if slot_id_of(meal) in completed
    ]

    st.subheader(
        "Current meals"
    )

    if upcoming_display:

        show_meals(
            upcoming_display
        )

    else:

        st.info(
            "No uncompleted meals remain "
            "in your current plan."
        )

    with st.expander(
        f"Meals already eaten ({len(completed_display)})"
    ):

        if completed_display:

            show_meals(
                completed_display
            )

        else:

            st.caption(
                "No meals marked as eaten yet."
            )
