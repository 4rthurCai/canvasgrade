# Changelog

## Unreleased

### Added

- **`--criterion 'COLUMN[=MAX]'`** forces a column into the rubric. Only headers that
  declare a maximum became criteria, which is the right default — it is what keeps grader
  initials and running notes out of your rubric — but it left no way at all to score a
  penalty or bonus column short of editing the spreadsheet's headers. A penalty column's
  maximum is 0, so that is accepted and a negative one is refused; omit the `=MAX` and it
  comes from the header, which puts a per-milestone subtotal back.
- **`--all-criteria`** does the same for every column that holds a number. Maxima come
  from the header where declared and from the column's largest value otherwise, and a
  column of zeroes and negatives is read as a deduction worth 0. Identity columns, the
  total and comment columns are never swept up — scoring the total would count every mark
  twice — so it is refused alongside `--apply-ratio`, which it would leave nothing to do.

### Fixed

- **`Weight (10)` was read as a criterion worth ten points.** A declared maximum outranked
  the ratio and team keywords, which is what stops `Bug reports (team) [5]` being mistaken
  for the team column — but it also put a multiplier in the rubric, next to the marks it
  was supposed to scale. The keyword now wins when it is the *whole* header, and loses
  when it is one word inside a longer one, so both headers are read the way they look.

## 0.3.0

### Added

- **`inspect` now previews the rubric**, not just the column mapping. Seeing what would
  be created previously meant `push --dry-run`, which needs a token and an assignment;
  the rubric a sheet implies is knowable offline, so now it is shown offline.
  `--columns-only` skips it.
- **`--describe 'Column=text'`** sets the detail Canvas shows when a student opens a
  criterion. The field already travelled all the way to the API payload — there was
  simply no way to fill it in. The GUI has an input for it under the criterion name.
- `inspect` accepts `--rename`, so you can see how a renamed rubric reads before pushing.
- **`pull --merge`** refreshes the roster in a template you have already started
  filling in. Previously the only options were to be blocked by "already exists" or to
  `--force` and lose every score typed so far; a roster that changes mid-marking is
  normal, and losing an afternoon's work to it should not be. Scores are matched on
  Canvas id, so reordering rows or fixing a name cannot drop one, and it reports what
  it kept, who joined, who left, and which columns are gone from the rubric.
- **`canvasgrade help [command]`**, because reaching for `help` first is the habit git,
  docker and npm all reward. `--help` still works everywhere.
- **A full command reference** at `docs/commands.md`, with a test that fails if a
  command or flag is added without documenting it.
- **The GUI reports progress while pushing.** The bulk job is asynchronous and a bare
  spinner is indistinguishable from a hang, so it now counts the seconds and says how
  many grades are in flight.

## 0.2.1

### Fixed

- **Contradictory rubric flags were silently ranked.** `--create-rubric --rubric-id 999
  --no-rubric` ran without complaint and quietly discarded two of them. On a command that
  writes to student records, a flag you typed should never be thrown away in silence; the
  combination is now refused.
- **The rubric dropdown in the GUI did not follow the course.** Switching course while
  "use an existing rubric" was selected left the previous course's rubrics on offer.

### Added

- `--rename 'Column=Name'` gives the command line the criterion renaming the GUI already
  had. The column must exist, and the error lists the criteria that do.

### Changed

- The two near-identical helpers behind `--id-column` and `--total-column` are now one.
  The error when a named column does not exist reports which columns currently hold that
  role, for whichever role was being set.

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

First release, verified end to end against a live Canvas instance.

### The core idea

A rubric is built from the spreadsheet's own column headers, and Canvas hands back the
criterion ids in the same response. That removes the two worst steps of doing this by
hand: there is no rubric id to hunt for in browser dev tools, and no need to score
somebody in SpeedGrader first to make a fresh rubric usable.

### Reading a real gradebook

Rather than requiring a bare `uid,score,score` file, the detector reads the sheet as it
is and records why it decided what it did, so `canvasgrade inspect` can explain itself
and every guess can be overridden:

- A column becomes a criterion only when its header declares a maximum — `Code Quality
  (35)`, `设计 （10分）`. That rule is what keeps grader initials, ratios and running
  subtotals out of the rubric. When no header declares one, a maximum is inferred from
  the data instead.
- Identity columns, team header rows, per-milestone subtotals, ratio columns and
  per-criterion comment columns are all recognised.
- `-I/--include` and `-E/--exclude` narrow a sheet covering several assignments down to
  the criteria for one, and comment columns follow their criterion out.

### Pushing

- Canvas's asynchronous bulk endpoint: one request per batch instead of two per student.
- Per-criterion comments from a `<criterion> comment` column.
- `--total` chooses between the sheet's own total and the sum of criteria;
  `--apply-ratio` applies a ratio column, off by default because a total column usually
  has it baked in already.
- `--use-for-grading` is off by default, since letting Canvas recompute the grade from
  the rubric would overwrite the sheet's total.

### Not writing by accident

- `-n/--dry-run` builds the whole plan, including the rubric that *would* be created,
  and sends nothing.
- Nothing is written until you answer `y`. The rubric is created *after* the
  confirmation, so declining leaves nothing behind.
- Errors block a push: a negative total, two rows resolving to the same student, or no
  student matching the course at all. Scores above a criterion's maximum are capped with
  a warning, or refused outright with `--no-clamp`.
- Students resolve by Canvas id, then SIS/login id, then name; name matching tolerates a
  second script and small typos but stops rather than choose between two plausible
  people.

### Also in the box

- `pull` writes a template with every enrolled student and criterion column already in
  place, optionally pre-filled with the scores on Canvas.
- A local browser GUI, bound to loopback, that never hands the access token to the page.
- `plot` draws the grade distribution against a fitted normal, with an optional
  per-criterion breakdown.
- Credentials come from `~/.canvasgrade.toml`, `$CANVAS_API_KEY` or `--api-key`, in that
  order of increasing precedence, with named profiles for per-course ids.
