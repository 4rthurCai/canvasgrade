"""Work out what each spreadsheet column means.

The detector is deliberately conservative: it only calls a column a rubric criterion
when the header carries an explicit max score, e.g. ``P1M1 Elm format (10)``. That rule
keeps bookkeeping columns (grader initials, ratios, running totals) from silently
becoming criteria. Every decision records a ``reason`` so the CLI table and the GUI can
explain themselves, and any of them can be overridden.
"""

from __future__ import annotations

import re

import pandas as pd

from canvasgrade.models import ColumnRole, ColumnSpec, SheetMapping

#: Bracket pairs a max score may be written in. Openers and closers are paired, so a
#: stray "(10]" is not read as a score.
BRACKET_PAIRS = (("(", ")"), ("（", "）"), ("[", "]"), ("【", "】"))
_NUMBER = r"(\d+(?:\.\d+)?)"
_UNIT = r"(?:分|点|marks?|pts?|points?)"
#: A trailing prime marks a variant of a question ("[10']"); it is decoration, not part
#: of the score. Excel turns a typed ' into a curly quote, so accept all three forms.
_PRIME = r"['’′]*"

#: A trailing bracket holding just the score: "Code Quality (35)", "某项 （10分）",
#: "Thing [7.5 pts]", "题目一 [10']".
POINTS_PATTERNS = tuple(
    re.compile(
        rf"{re.escape(opener)}\s*{_NUMBER}\s*{_UNIT}?\s*{_PRIME}\s*{re.escape(closer)}\s*$",
        re.IGNORECASE,
    )
    for opener, closer in BRACKET_PAIRS
)

#: A header wrapped end to end with the score inside it: "【设计 10分】". The unit is
#: required here - without it "【项目 2】", Project 2, would be misread as a criterion
#: worth two points.
WRAPPED_PATTERNS = tuple(
    re.compile(
        rf"^{re.escape(opener)}\s*(.*?\S)\s+{_NUMBER}\s*{_UNIT}\s*{_PRIME}\s*{re.escape(closer)}\s*$",
        re.IGNORECASE,
    )
    for opener, closer in BRACKET_PAIRS
)

#: Unambiguous names for the Canvas user id, compared with separators removed so
#: "Canvas_ID", "canvas id" and "CanvasID" are all the same thing.
CANVAS_ID_STRONG = frozenset({"canvasid", "canvasuid", "canvasuserid"})
#: Plausible, but weak. A sheet that also carries a "CanvasID" column means something
#: else by a bare "ID" - usually the institution's student number, which would push
#: grades at user ids that do not exist.
CANVAS_ID_WEAK = frozenset({"id", "uid", "userid"})
NAME_NAMES = frozenset(
    {"student", "students", "name", "names", "student name", "full name", "姓名", "学生", "学生姓名"}
)
SIS_TOKENS = ("sis", "login id", "student number", "学号", "jaccount")
TEAM_TOKENS = ("team", "group", "小组", "组别", "队伍")
TOTAL_TOKENS = ("total", "sum", "subtotal", "overall", "grand", "总分", "合计", "总计", "小计")
RATIO_TOKENS = ("ratio", "weight", "factor", "multiplier", "coefficient", "系数", "比例", "权重", "占比")
COMMENT_SUFFIXES = (
    "_comment",
    "_comments",
    "_feedback",
    "_note",
    "_notes",
    " comment",
    " comments",
    " feedback",
    " note",
    " notes",
    "评语",
    "备注",
    "反馈",
    "评论",
)


def normalise(header: str) -> str:
    """Lower-case, collapse whitespace, unify full-width punctuation."""
    text = str(header).strip().lower()
    text = text.replace("（", "(").replace("）", ")").replace("：", ":")
    return " ".join(text.split())


def squash(header: str) -> str:
    """Normalise, then drop separators, so "Canvas_ID" and "CanvasID" compare equal."""
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", normalise(header))


def parse_header(header: str) -> tuple[str, float | None]:
    """Split a header into its criterion name and its declared max score.

    Returns the header unchanged with ``None`` when no score is declared::

        "Code Quality (35)" -> ("Code Quality", 35.0)
        "题目一 [10']"       -> ("题目一", 10.0)
        "【设计 10分】"       -> ("设计", 10.0)
        "Milestone 2"       -> ("Milestone 2", None)
    """
    text = str(header).strip()

    for pattern in POINTS_PATTERNS:
        match = pattern.search(text)
        if match:
            return text[: match.start()].strip(" -:_") or text, float(match.group(1))

    for pattern in WRAPPED_PATTERNS:
        match = pattern.match(text)
        if match:
            return match.group(1).strip(" -:_"), float(match.group(2))

    return text, None


def parse_points(header: str) -> float | None:
    """Extract the max score from a header like ``Code Quality (35)``."""
    return parse_header(header)[1]


def strip_points(header: str) -> str:
    """Return the header without its max-score marker."""
    return parse_header(header)[0]


def _contains(text: str, tokens: tuple[str, ...]) -> str | None:
    for token in tokens:
        if token in text:
            return token
    return None


def _comment_base(header: str) -> str | None:
    """If the header looks like a comment column, return the name it annotates."""
    text = normalise(header)
    for suffix in COMMENT_SUFFIXES:
        if text.endswith(suffix):
            return text[: -len(suffix)].strip(" -:_")
    return None


def _is_numericish(series: pd.Series) -> bool:
    """True when at least one cell parses as a number."""
    values = pd.to_numeric(series, errors="coerce")
    return bool(values.notna().any())


def _observed_max(series: pd.Series) -> float | None:
    values = pd.to_numeric(series, errors="coerce")
    if values.notna().sum() == 0:
        return None
    top = float(values.max())
    return top if top > 0 else None


def _classify(header: str, index: int, series: pd.Series, explicit_points_present: bool) -> ColumnSpec:
    """Assign a role to a single column, ignoring cross-column conflicts."""
    text = normalise(header)
    points = parse_points(header)

    def spec(role: ColumnRole, reason: str, **kwargs: object) -> ColumnSpec:
        return ColumnSpec(name=header, index=index, role=role, reason=reason, **kwargs)  # type: ignore[arg-type]

    # An explicit maximum settles it: a column worth 5 points is something being
    # marked, whatever else its name happens to contain. Without this, a criterion
    # like "Bug reports (team) [5]" is read as the team column and silently dropped.
    if points is not None:
        matched = _contains(text, TOTAL_TOKENS)
        if matched:
            # "P1 Total (70)" is a sum of criteria and must not be pushed as one.
            return spec(ColumnRole.TOTAL, f"header contains '{matched}'", points=points)
        return spec(ColumnRole.CRITERION, f"header declares a max of {points:g}", points=points)

    # Identity columns first: "SIS Login ID" also contains "id", so order matters.
    if text in NAME_NAMES:
        return spec(ColumnRole.NAME, "header names a student")
    matched = _contains(text, SIS_TOKENS)
    if matched:
        return spec(ColumnRole.SIS_ID, f"header contains '{matched}'")
    squashed = squash(header)
    if squashed in CANVAS_ID_STRONG:
        return spec(ColumnRole.CANVAS_ID, "header names the Canvas user id")
    if squashed in CANVAS_ID_WEAK:
        return spec(ColumnRole.CANVAS_ID, "header looks like a Canvas user id")
    matched = _contains(text, TEAM_TOKENS)
    if matched:
        return spec(ColumnRole.TEAM, f"header contains '{matched}'")

    # Comment columns must resolve to a criterion later; provisionally tag them.
    base = _comment_base(header)
    if base is not None:
        return spec(ColumnRole.COMMENT, "header looks like a comment", target=base)

    matched = _contains(text, TOTAL_TOKENS)
    if matched:
        return spec(ColumnRole.TOTAL, f"header contains '{matched}'", points=points)
    matched = _contains(text, RATIO_TOKENS)
    if matched:
        return spec(ColumnRole.RATIO, f"header contains '{matched}'")

    # Without an explicit max we only guess when the whole sheet lacks them, so that
    # bookkeeping columns in an annotated sheet stay ignored.
    if not explicit_points_present and _is_numericish(series):
        inferred = _observed_max(series)
        if inferred is not None:
            return spec(ColumnRole.CRITERION, f"max {inferred:g} inferred from data", points=inferred)

    if _is_numericish(series):
        return spec(ColumnRole.IGNORE, "numeric, but header declares no max score")
    return spec(ColumnRole.IGNORE, "not a score column")


def _prefer_specific_canvas_id(columns: list[ColumnSpec]) -> list[ColumnSpec]:
    """When a sheet has both "CanvasID" and a bare "ID", the specific one wins.

    Getting this backwards is expensive: the bare column is usually the institution's
    student number, and grading against it addresses users who do not exist.
    """
    candidates = [c for c in columns if c.role is ColumnRole.CANVAS_ID]
    if len(candidates) < 2:
        return columns
    strong = [c for c in candidates if squash(c.name) in CANVAS_ID_STRONG]
    if not strong:
        return columns

    winner = strong[0]
    losers = {c.name for c in candidates if c is not winner}
    return [
        c
        if c.name not in losers
        else ColumnSpec(
            name=c.name,
            index=c.index,
            role=ColumnRole.IGNORE,
            reason=f"'{winner.name}' is the explicit Canvas user id",
        )
        for c in columns
    ]


def _dedupe_single(columns: list[ColumnSpec], role: ColumnRole, keep: str) -> list[ColumnSpec]:
    """Keep one column for a role that only allows one; ignore the others.

    ``keep`` is "first" for identity columns and "last" for totals and ratios, where a
    trailing column is the final figure and earlier ones are per-milestone subtotals.
    """
    matches = [c for c in columns if c.role is role]
    if len(matches) <= 1:
        return columns
    winner = matches[0] if keep == "first" else matches[-1]
    losers = {c.name for c in matches if c is not winner}
    label = role.value.replace("_", " ")
    return [
        c
        if c.name not in losers
        else ColumnSpec(
            name=c.name,
            index=c.index,
            role=ColumnRole.IGNORE,
            reason=f"another column is the {label} ('{winner.name}')",
        )
        for c in columns
    ]


def _resolve_comment_targets(columns: list[ColumnSpec]) -> list[ColumnSpec]:
    """Point each comment column at a criterion, or demote it to IGNORE.

    Both spellings are accepted: "Design comment" and "Design (10) comment" find the
    criterion "Design (10)", because people write the header either way.
    """
    criteria: dict[str, str] = {}
    for column in columns:
        if column.role is ColumnRole.CRITERION:
            criteria.setdefault(normalise(strip_points(column.name)), column.name)
            criteria.setdefault(normalise(column.name), column.name)

    resolved: list[ColumnSpec] = []
    for column in columns:
        if column.role is not ColumnRole.COMMENT:
            resolved.append(column)
            continue
        wanted = column.target or ""
        target = criteria.get(normalise(wanted)) or criteria.get(normalise(strip_points(wanted)))
        if target is None:
            resolved.append(
                ColumnSpec(
                    name=column.name,
                    index=column.index,
                    role=ColumnRole.IGNORE,
                    reason=f"comment for unknown criterion '{column.target}'",
                )
            )
        else:
            resolved.append(
                ColumnSpec(
                    name=column.name,
                    index=column.index,
                    role=ColumnRole.COMMENT,
                    target=target,
                    reason=f"comment for '{target}'",
                )
            )
    return resolved


def detect_mapping(frame: pd.DataFrame, *, has_header: bool = True) -> SheetMapping:
    """Infer a :class:`SheetMapping` for a raw sheet.

    Without a header row the layout is positional, matching the classic format: first
    column is the Canvas user id, every other column is a criterion in rubric order.
    """
    headers = [str(c) for c in frame.columns]

    if not has_header:
        columns = [
            ColumnSpec(
                name=header,
                index=index,
                role=ColumnRole.CANVAS_ID if index == 0 else ColumnRole.CRITERION,
                points=None if index == 0 else _observed_max(frame.iloc[:, index]),
                reason="positional layout (no header row)",
            )
            for index, header in enumerate(headers)
        ]
        return SheetMapping(columns=tuple(columns))

    explicit_points_present = any(parse_points(h) is not None for h in headers)
    columns = [
        _classify(header, index, frame.iloc[:, index], explicit_points_present) for index, header in enumerate(headers)
    ]

    columns = _prefer_specific_canvas_id(columns)
    columns = _dedupe_single(columns, ColumnRole.CANVAS_ID, keep="first")
    columns = _dedupe_single(columns, ColumnRole.SIS_ID, keep="first")
    columns = _dedupe_single(columns, ColumnRole.NAME, keep="first")
    columns = _dedupe_single(columns, ColumnRole.TEAM, keep="first")
    columns = _dedupe_single(columns, ColumnRole.TOTAL, keep="last")
    columns = _dedupe_single(columns, ColumnRole.RATIO, keep="last")
    columns = _resolve_comment_targets(columns)

    return SheetMapping(columns=tuple(columns))
