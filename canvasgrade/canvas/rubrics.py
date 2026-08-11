"""Create rubrics from a spec, and read back the ones that already exist.

Creating the rubric ourselves is what removes the two worst steps of the old workflow:
the response carries the criterion ids directly, so there is no id to hunt for in
DevTools and no need to "warm up" a fresh rubric by scoring someone in SpeedGrader.
"""

from __future__ import annotations

from typing import Any

from canvasgrade.canvas.client import API_ERRORS, _explain
from canvasgrade.errors import CanvasError
from canvasgrade.grading.rubric import CanvasCriterion
from canvasgrade.models import RubricSpec

FULL_MARKS = "Full marks"
NO_MARKS = "No marks"


def _criteria_payload(spec: RubricSpec) -> dict[int, dict[str, Any]]:
    """Build ``rubric[criteria][i][...]``.

    Each criterion gets a full/zero rating pair because Canvas will not render a
    criterion that has no ratings, and free-form comments are enabled at the rubric
    level so per-criterion feedback can be anything we like.
    """
    return {
        index: {
            "description": criterion.description,
            "long_description": criterion.long_description,
            "points": criterion.points,
            "criterion_use_range": False,
            "ratings": {
                0: {"description": FULL_MARKS, "points": criterion.points},
                1: {"description": NO_MARKS, "points": 0},
            },
        }
        for index, criterion in enumerate(spec.criteria)
    }


def _read_criteria(data: Any) -> tuple[CanvasCriterion, ...]:
    """Normalise Canvas's criteria array, which arrives as a list of dicts."""
    if not isinstance(data, list):
        return ()
    criteria: list[CanvasCriterion] = []
    for item in data:
        if not isinstance(item, dict) or "id" not in item:
            continue
        criteria.append(
            CanvasCriterion(
                criterion_id=str(item["id"]),
                description=str(item.get("description") or ""),
                points=float(item.get("points") or 0),
            )
        )
    return tuple(criteria)


def find_attached_rubric(assignment: Any) -> tuple[int | None, tuple[CanvasCriterion, ...]]:
    """Read the rubric already attached to an assignment, if any.

    Assignments carry their rubric inline, so this needs no extra request and no
    rubric id from the user.
    """
    settings = getattr(assignment, "rubric_settings", None) or {}
    rubric_id = settings.get("id") if isinstance(settings, dict) else None
    criteria = _read_criteria(getattr(assignment, "rubric", None))
    return (int(rubric_id) if rubric_id else None), criteria


def load_rubric(course: Any, rubric_id: int) -> tuple[CanvasCriterion, ...]:
    """Fetch a rubric's criteria by id, trying the richer view if the plain one is bare."""
    try:
        rubric = course.get_rubric(rubric_id)
        criteria = _read_criteria(getattr(rubric, "data", None))
        if criteria:
            return criteria
        detailed = course.get_rubric(rubric_id, include=["assessments"], style="full")
        criteria = _read_criteria(getattr(detailed, "data", None))
        if criteria:
            return criteria
        assessments = getattr(detailed, "assessments", None)
        if isinstance(assessments, list) and assessments:
            criteria = _read_criteria(assessments[0].get("data"))
    except API_ERRORS as exc:
        raise _explain(exc, f"loading rubric {rubric_id}") from exc

    if not criteria:
        raise CanvasError(
            f"Rubric {rubric_id} came back without any criteria. Let canvasgrade create the "
            "rubric instead with --create-rubric, which avoids this entirely."
        )
    return criteria


def create_rubric(
    course: Any,
    assignment: Any,
    spec: RubricSpec,
    *,
    use_for_grading: bool = False,
    hide_score_total: bool = False,
) -> RubricSpec:
    """Create ``spec`` on Canvas, attach it to ``assignment``, return it with ids bound.

    ``use_for_grading`` is off by default: with it on, Canvas recomputes the assignment
    grade from the rubric total and would overwrite the total column from your sheet.
    """
    if not spec.criteria:
        raise CanvasError("Refusing to create a rubric with no criteria.")

    payload = {
        "rubric": {
            "title": spec.title,
            "free_form_criterion_comments": True,
            "criteria": _criteria_payload(spec),
        },
        "rubric_association": {
            "association_id": assignment.id,
            "association_type": "Assignment",
            "purpose": "grading",
            "use_for_grading": use_for_grading,
            "hide_score_total": hide_score_total,
        },
    }

    try:
        result = course.create_rubric(**payload)
    except API_ERRORS as exc:
        raise _explain(exc, f"creating rubric {spec.title!r}") from exc

    rubric = result.get("rubric") if isinstance(result, dict) else None
    if rubric is None:
        raise CanvasError(
            "Canvas accepted the rubric but did not return it. Check the assignment page; "
            "if the rubric is there, re-run without --create-rubric."
        )

    criteria = _read_criteria(getattr(rubric, "data", None))
    if len(criteria) != len(spec.criteria):
        raise CanvasError(
            f"Created rubric {getattr(rubric, 'id', '?')} came back with {len(criteria)} criteria "
            f"but {len(spec.criteria)} were sent. Delete it on Canvas and try again."
        )

    # Canvas preserves the order we sent, so bind positionally rather than by name -
    # descriptions can be silently truncated or HTML-escaped on the way through.
    bound = tuple(
        criterion.with_id(canvas.criterion_id) for criterion, canvas in zip(spec.criteria, criteria, strict=True)
    )
    return RubricSpec(title=spec.title, criteria=bound, rubric_id=int(rubric.id))


def attach_rubric(course: Any, rubric_id: int, assignment: Any, *, use_for_grading: bool = False) -> None:
    """Associate an existing rubric with an assignment."""
    try:
        course.create_rubric_association(
            rubric_association={
                "rubric_id": rubric_id,
                "association_id": assignment.id,
                "association_type": "Assignment",
                "purpose": "grading",
                "use_for_grading": use_for_grading,
            }
        )
    except API_ERRORS as exc:
        raise _explain(exc, f"attaching rubric {rubric_id} to assignment {assignment.id}") from exc
