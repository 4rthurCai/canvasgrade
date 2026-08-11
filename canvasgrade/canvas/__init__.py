"""Everything that talks to Canvas over the network."""

from canvasgrade.canvas.client import CanvasSession
from canvasgrade.canvas.pull import build_template, fetch_roster, write_template
from canvasgrade.canvas.push import PushResult, push_grades
from canvasgrade.canvas.rubrics import attach_rubric, create_rubric, find_attached_rubric, load_rubric

__all__ = [
    "CanvasSession",
    "PushResult",
    "attach_rubric",
    "build_template",
    "create_rubric",
    "fetch_roster",
    "find_attached_rubric",
    "load_rubric",
    "push_grades",
    "write_template",
]
