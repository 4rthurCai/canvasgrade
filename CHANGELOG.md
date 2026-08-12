# Changelog

## 0.2.0

Everything here came out of running the tool against real gradebooks.

### Fixed

- **A criterion whose name contained an identity keyword was silently dropped.**
  `Bug reports (team) [5]` was read as the team column, because the keyword was tested
  before the declared maximum. On a real sheet that lost a whole criterion: 19 criteria
  worth 95 points where the sheet's own total said 100. A header that declares a maximum
  is now something being marked, whatever else its name contains. Totals still win.
- **A student number could be taken for the Canvas user id.** `CanvasID` was not
  recognised at all — identity names were compared with separators intact — so a bare
  `ID` column holding a twelve-digit institution number was used instead. Identity
  headers are now compared with separators removed, and an explicit Canvas id column
  wins over a bare `ID` when a sheet carries both.
- **A role assigned by hand could be ignored.** Setting a second column to `canvas_id`
  in the GUI left two, and lookups then picked by column order rather than by what was
  just chosen.
- **`--strict` and the column overrides were missing from the GUI**, so the browser
  could not express pushes the command line could.

### Added

- `--id-column` and `--total-column` to name the column holding the Canvas user id or
  the assignment total, when the detector picks the wrong one. Both are also available
  in the GUI.
- **When rows fail to match, the tool names the column that would have worked.** Canvas
  ids and student numbers are both just integers and cannot be told apart by looking at
  them, so the roster is asked instead: every other numeric column is checked against
  the enrolled ids and the one that actually hits is reported.
- **Criteria can be renamed before the rubric is created.** Column headers are written
  for whoever is marking; the criterion name is what students read. Scores still join on
  the column name, so renaming cannot detach a criterion from its marks.
- **The preview shows the rubric as a rubric** — each criterion, its maximum, the
  running total, and whether its id is real or still to be assigned — rather than
  leaving it implied by truncated column headers.
- `canvasgrade rubrics` lists a course's rubrics, and the GUI offers them in a dropdown,
  so choosing an existing rubric no longer means hunting an id in browser dev tools.
- `--strict` promotes every warning to an error, for use in scripts.
- Square brackets, full-width brackets and a trailing prime are accepted in headers:
  `Design [10]`, `【设计 10分】`, `题目一 [10']`.

## 0.1.0

First release. Builds a Canvas rubric from spreadsheet headers, pushes grades, comments
and rubric assessments in bulk, and pulls a filled-in template back.
