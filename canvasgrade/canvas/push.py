"""Push grades to Canvas in bulk.

Canvas has an asynchronous bulk endpoint that takes every student in one request and
hands back a job to poll. That is one request per batch instead of two per student, so a
class of fifty goes from a couple of minutes of serial round-trips to a few seconds.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from canvasgrade.canvas.client import API_ERRORS, _explain
from canvasgrade.errors import CanvasError
from canvasgrade.models import GradeEntry

DEFAULT_BATCH_SIZE = 200
POLL_INTERVAL_SECONDS = 1.5
DEFAULT_TIMEOUT_SECONDS = 600.0

#: Called with (stage, done, total) so callers can drive a progress bar.
ProgressCallback = Callable[[str, int, int], None]


@dataclass(frozen=True)
class BatchResult:
    """What happened to one batch of students."""

    size: int
    progress_id: int | None
    state: str
    message: str = ""

    @property
    def ok(self) -> bool:
        return self.state == "completed"


@dataclass(frozen=True)
class PushResult:
    """The outcome of a whole push."""

    batches: tuple[BatchResult, ...]

    @property
    def submitted(self) -> int:
        return sum(batch.size for batch in self.batches if batch.ok)

    @property
    def failed(self) -> tuple[BatchResult, ...]:
        return tuple(batch for batch in self.batches if not batch.ok)

    @property
    def ok(self) -> bool:
        return bool(self.batches) and not self.failed


def _grade_data(entries: Sequence[GradeEntry]) -> dict[int, dict[str, Any]]:
    """Shape entries into Canvas's ``grade_data[<user_id>][...]`` payload."""
    payload: dict[int, dict[str, Any]] = {}
    for entry in entries:
        item: dict[str, Any] = {"posted_grade": entry.posted_grade}
        assessment = entry.rubric_assessment()
        if assessment:
            item["rubric_assessment"] = assessment
        if entry.text_comment:
            item["text_comment"] = entry.text_comment
        payload[entry.user_id] = item
    return payload


def _await_progress(progress: Any, timeout: float, on_progress: ProgressCallback | None) -> tuple[str, str]:
    """Poll an async job to completion; return its final state and message."""
    deadline = time.monotonic() + timeout
    while True:
        state = str(getattr(progress, "workflow_state", "") or "queued")
        if state in ("completed", "failed"):
            return state, str(getattr(progress, "message", "") or "")
        if time.monotonic() > deadline:
            return "timeout", (
                f"Canvas was still working after {timeout:g}s. The grades may still land; "
                "check the gradebook before re-running."
            )
        if on_progress:
            completion = getattr(progress, "completion", None)
            on_progress("polling", int(completion or 0), 100)
        time.sleep(POLL_INTERVAL_SECONDS)
        try:
            progress = progress.query()
        except API_ERRORS as exc:
            raise _explain(exc, "checking the status of the grade upload") from exc


def push_grades(
    assignment: Any,
    entries: Sequence[GradeEntry],
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    wait: bool = True,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    on_progress: ProgressCallback | None = None,
) -> PushResult:
    """Upload every entry, in batches, and wait for Canvas to finish applying them."""
    if not entries:
        raise CanvasError("There is nothing to push.")
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")

    batches: list[BatchResult] = []
    chunks = [entries[i : i + batch_size] for i in range(0, len(entries), batch_size)]

    for index, chunk in enumerate(chunks, start=1):
        if on_progress:
            on_progress("uploading", index - 1, len(chunks))
        try:
            progress = assignment.submissions_bulk_update(grade_data=_grade_data(chunk))
        except API_ERRORS as exc:
            raise _explain(exc, f"uploading grades for {len(chunk)} students") from exc

        progress_id = getattr(progress, "id", None)
        if not wait:
            batches.append(BatchResult(len(chunk), progress_id, "queued"))
            continue

        state, message = _await_progress(progress, timeout, on_progress)
        batches.append(BatchResult(len(chunk), progress_id, state, message))
        if on_progress:
            on_progress("uploading", index, len(chunks))

    return PushResult(batches=tuple(batches))
