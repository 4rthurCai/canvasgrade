"""Match spreadsheet rows to Canvas users.

Identifiers are tried strongest-first: Canvas user id, then SIS/login id, then the
name. Name matching handles the shapes that show up in practice - a sheet that writes
names in two scripts against a Canvas record that uses one, or a sortable "Last, First"
- and refuses to guess when two students could both be meant.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

from canvasgrade.models import StudentRow

#: Below this similarity a fuzzy name match is not offered at all.
FUZZY_CUTOFF = 0.88
PUNCTUATION_RE = re.compile(r"[^\w\s]", re.UNICODE)


@dataclass(frozen=True)
class RosterEntry:
    """One enrolled student, as far as we care about them."""

    user_id: int
    name: str = ""
    sortable_name: str = ""
    sis_user_id: str | None = None
    login_id: str | None = None

    @property
    def identifiers(self) -> tuple[str, ...]:
        raw = (self.sis_user_id, self.login_id)
        return tuple(str(value).strip() for value in raw if value)


@dataclass(frozen=True)
class Match:
    """The outcome of resolving one row against the roster."""

    user_id: int | None
    method: str
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.user_id is not None


def normalise_name(name: str) -> str:
    """Casefold, drop punctuation and accents, collapse whitespace."""
    decomposed = unicodedata.normalize("NFKC", str(name)).strip().casefold()
    without_punctuation = PUNCTUATION_RE.sub(" ", decomposed)
    return " ".join(without_punctuation.split())


def _name_tokens(name: str) -> frozenset[str]:
    return frozenset(normalise_name(name).split())


def _flip_sortable(name: str) -> str:
    """ "Li, Ruochong" -> "Ruochong Li" so both orders compare equal."""
    if "," not in name:
        return name
    last, _, first = name.partition(",")
    return f"{first.strip()} {last.strip()}"


@dataclass(frozen=True)
class Roster:
    """The set of students enrolled in the assignment's course."""

    entries: tuple[RosterEntry, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.entries

    def by_id(self, user_id: int) -> RosterEntry | None:
        for entry in self.entries:
            if entry.user_id == user_id:
                return entry
        return None

    def _by_identifier(self, value: str) -> list[RosterEntry]:
        wanted = value.strip().casefold()
        return [e for e in self.entries if any(i.casefold() == wanted for i in e.identifiers)]

    def _candidate_names(self, entry: RosterEntry) -> tuple[str, ...]:
        names = (entry.name, entry.sortable_name, _flip_sortable(entry.sortable_name))
        return tuple(normalise_name(n) for n in names if n)

    def _by_name(self, name: str) -> Match:
        wanted = normalise_name(name)
        if not wanted:
            return Match(None, "unmatched", "row has no name")

        exact = [e for e in self.entries if wanted in self._candidate_names(e)]
        if len(exact) == 1:
            return Match(exact[0].user_id, "name")
        if len(exact) > 1:
            return Match(None, "ambiguous", f"{len(exact)} students share the name {name!r}")

        # A sheet name may carry extra tokens the Canvas record lacks: accept a superset.
        wanted_tokens = _name_tokens(name)

        def overlaps(entry: RosterEntry) -> bool:
            for candidate in self._candidate_names(entry):
                tokens = _name_tokens(candidate)
                if tokens and (tokens <= wanted_tokens or wanted_tokens <= tokens):
                    return True
            return False

        subset = [e for e in self.entries if overlaps(e)]
        if len(subset) == 1:
            return Match(subset[0].user_id, "name (partial)")
        if len(subset) > 1:
            return Match(None, "ambiguous", f"{len(subset)} students partially match {name!r}")

        scored = sorted(
            (
                (max(SequenceMatcher(None, wanted, candidate).ratio() for candidate in self._candidate_names(e)), e)
                for e in self.entries
                if self._candidate_names(e)
            ),
            key=lambda pair: pair[0],
            reverse=True,
        )
        if scored and scored[0][0] >= FUZZY_CUTOFF:
            best_score, best = scored[0]
            runner_up = scored[1][0] if len(scored) > 1 else 0.0
            if best_score - runner_up < 0.05:
                return Match(None, "ambiguous", f"{name!r} is equally close to two students")
            return Match(best.user_id, "name (fuzzy)", f"{best.name!r} at {best_score:.0%} similarity")

        return Match(None, "unmatched", f"no student on Canvas matches {name!r}")

    def resolve(self, row: StudentRow) -> Match:
        """Resolve one row to a Canvas user id, explaining the choice either way."""
        if row.canvas_id is not None:
            if self.is_empty:
                return Match(row.canvas_id, "canvas id (unverified)")
            if self.by_id(row.canvas_id):
                return Match(row.canvas_id, "canvas id")
            return Match(None, "unmatched", f"user id {row.canvas_id} is not enrolled in this course")

        if row.sis_id:
            if self.is_empty:
                return Match(None, "unmatched", f"cannot resolve SIS id {row.sis_id} without a roster")
            found = self._by_identifier(row.sis_id)
            if len(found) == 1:
                return Match(found[0].user_id, "sis id")
            if len(found) > 1:
                return Match(None, "ambiguous", f"{len(found)} students share SIS id {row.sis_id}")

        if row.name and not self.is_empty:
            return self._by_name(row.name)

        if row.sis_id:
            return Match(None, "unmatched", f"no student on Canvas has SIS/login id {row.sis_id}")
        return Match(None, "unmatched", "row has no Canvas id, SIS id or name")
