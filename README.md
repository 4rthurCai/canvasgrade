<div align="center">

# canvasgrade

**Build a Canvas rubric straight from your grading spreadsheet, then push every score,
comment and total back — in one command.**

[![PyPI](https://img.shields.io/pypi/v/canvasgrade?color=1f4ea1)](https://pypi.org/project/canvasgrade/)
[![Python](https://img.shields.io/pypi/pyversions/canvasgrade)](https://pypi.org/project/canvasgrade/)
[![CI](https://github.com/4rthurCai/canvasgrade/actions/workflows/ci.yml/badge.svg)](https://github.com/4rthurCai/canvasgrade/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-MIT-blue)](https://github.com/4rthurCai/canvasgrade/blob/master/LICENSE)

</div>

---

No rubric id to hunt for in Chrome DevTools. No reshaping your gradebook into a bare
positional CSV. No clicking through SpeedGrader to "warm up" a fresh rubric.

```bash
pip3 install "canvasgrade[all]"
canvasgrade push grades.xlsx --create-rubric --dry-run   # look first
canvasgrade push grades.xlsx --create-rubric             # then push
```

## The problem

Grading spreadsheets are messy in specific, predictable ways: three milestones side by
side, team header rows with nothing in them, a ratio column, running subtotals, a column
of grader initials. Tools want a bare `uid,score,score` CSV. So every marking session
ends with somebody reshaping a spreadsheet by hand.

canvasgrade reads the sheet you already have, and tells you exactly what it made of
every column before it writes anything.

`canvasgrade inspect grades.xlsx`:

| Column | Role | Max | Why |
|---|---|---:|---|
| `Student` | name | | header names a student |
| `ID` | canvas_id | | header is a Canvas user id |
| `Design (10)` | **criterion** | 10 | header declares a max of 10 |
| `Tests (20)` | **criterion** | 20 | header declares a max of 20 |
| `Code Quality (35)` | **criterion** | 35 | header declares a max of 35 |
| `Docs (5)` | **criterion** | 5 | header declares a max of 5 |
| `Total (70)` | total | 70 | header contains 'total' |

> 44 students, 44 with a total in the sheet from 44 rows in the file
> 4 criteria worth 70 points in total

Every decision carries its reason, and every one of them can be overridden. `inspect`
touches no network.

## Look before you write

`--dry-run` builds the whole plan — including the rubric that *would* be created — and
sends nothing:

```bash
canvasgrade push grades.xlsx --create-rubric --dry-run
```

> Project 1 (id 418271) out of 70
> Would create rubric 'Project 1 rubric' with 4 criteria.

**The rubric it would build**

| # | Criterion | Max | Canvas id |
|---:|---|---:|---|
| 1 | Design | 10 | `_preview_1` |
| 2 | Tests | 20 | `_preview_2` |
| 3 | Code Quality | 35 | `_preview_3` |
| 4 | Docs | 5 | `_preview_4` |
| | **total** | **70** | |

**The grades it would push**

| Student | Canvas id | Total | Criteria | Comments |
|---|---:|---:|---|---:|
| Student 01 | 1001 | **66** | 7.8 · 19.8 · 34.4 · 4 | |
| Student 02 | 1002 | **52.6** | 8.3 · 9.9 · 32.2 · 2.2 | |
| *… and 42 more* | | | | |

> **44 students ready**  |  totals 43.6-66, mean 54.7

Criterion ids read `_preview_N` because nothing has been created yet. Confirm, and they
become the real ids Canvas hands back.

## What it does

| | |
|---|---|
| **Builds the rubric for you** | Column headers become criteria. The API hands back the criterion ids, so there is nothing to look up and no need to warm up a new rubric in SpeedGrader. |
| **Reads your real sheet** | Identity columns, team header rows, ratios, per-milestone subtotals and grader initials are all recognised — and the ones that are not scores stay out of the rubric. |
| **Pushes in one batch** | Canvas's asynchronous bulk endpoint: one request per batch instead of two per student. |
| **Per-criterion comments** | A `Design comment` column becomes feedback attached to that criterion. |
| **Closes the loop** | `pull` writes a template with every student and criterion already filled in; fill in the numbers and push the same file back. |
| **Refuses to guess** | Students match by Canvas id, then SIS/login id, then name — and it stops rather than pick between two plausible people. |

## Install

```bash
pip3 install "canvasgrade[all]"       # CLI + web GUI + plots
pip3 install canvasgrade              # CLI only
pip3 install "canvasgrade[web]"       # CLI + web GUI
```

Python 3.11 or newer.

> **Young project.** Creating a rubric, pushing grades and comments in bulk, and pulling
> a filled-in template have all been exercised end to end against a live Canvas
> instance, but this has had few users. Every write is previewed and confirmed first,
> and `--dry-run` sends nothing — use it.

## Set up

Generate an access token under **Account → Settings → New Access Token**, then:

```bash
canvasgrade config init     # writes ~/.canvasgrade.toml, chmod 600
canvasgrade config show     # check what resolved, token redacted
canvasgrade courses         # course ids
canvasgrade assignments     # assignment ids, and which have a rubric
canvasgrade rubrics         # rubric ids, for --rubric-id
```

No id ever has to come out of the browser's dev tools.

```toml
# ~/.canvasgrade.toml
api_url = "https://jicanvas.com/"
api_key = "your-token"

[profiles.vv186]
course_id = 786
assignment_id = 7081
```

Then `canvasgrade push grades.xlsx -p vv186`. `$CANVAS_API_KEY` and `--api-key` also
work; the environment beats the file and the flag beats both.

## How your headers are read

A header that declares a maximum becomes a rubric criterion:

| Header | Read as |
|---|---|
| `Code Quality (35)` | criterion "Code Quality", out of 35 |
| `Design [10]` | criterion "Design", out of 10 |
| `设计 （10分）`, `【设计 10分】` | criterion "设计", out of 10 |
| `题目一 [10']` | criterion "题目一", out of 10 — the prime is decoration |
| `Student`, `ID`, `SIS Login ID` | student identity |
| `P1 Total (70)` | the assignment total |
| `Ratio`, `Weight`, `系数` | a multiplier, ignored unless `--apply-ratio` |
| `Code Quality comment` | per-student feedback on that criterion |
| `Joe`, `Vonda` | ignored — numeric, but no declared maximum |

Rules worth knowing:

- **Only headers with an explicit maximum become criteria.** Round or square brackets,
  ASCII or full-width, optionally with a unit (`分`, `pts`) and a trailing prime. That
  rule keeps bookkeeping columns out of your rubric. If *no* header declares a maximum,
  a maximum is inferred from the data instead.
- **A declared maximum outranks everything but a total.** `Bug reports (team) [5]` is a
  criterion, not the team column.
- **A bare trailing number is never a score.** `Milestone 2` keeps its name.
- **When several columns look like totals, the last one wins** — override with
  `--total-column`.
- **A row with a name but no id and no scores is a team header.** The rows below it
  inherit that team name.

Run `canvasgrade inspect <file>` on your own sheet to see which rule each column hit.

## One sheet, several assignments

```bash
canvasgrade push "p1.xlsx" --create-rubric -I 'P1M1 *' --total sum -a 7081
canvasgrade push "p1.xlsx" --create-rubric -I 'P1M2 *' --total sum -a 7082
```

**Filtering changes the criteria, not the total.** With `--total auto` the grade still
comes from whichever total column the sheet ends with — for a three-milestone sheet that
is the whole-project total. Pushing one milestone usually means `--total sum` as well,
or `--total-column 'P1M1 Total'`. `--dry-run` shows both, so the mismatch is visible
before you push.

## Which rubric

| Flag | Behaviour |
|---|---|
| *(none)* | use the rubric already attached to the assignment |
| `--create-rubric` | build a new one from the column headers |
| `--rubric-id 7457` | score against an existing rubric |
| `--no-rubric` | push totals only |

## Where the total comes from

| Flag | Behaviour |
|---|---|
| `--total auto` *(default)* | the sheet's total column when it has one, else the sum of criteria |
| `--total sum` | always add the criteria up |
| `--total sheet` | always use the total column, and fail if it is empty |
| `--total-column 'P1M1 Total'` | pick which column *is* the total |
| `--apply-ratio` | multiply the total by the ratio column |

`--apply-ratio` is off by default because a total column has usually had the ratio
applied to it already. `--use-for-grading` lets Canvas recompute the grade from the
rubric total; it is off by default, since it would overwrite your sheet's total.

## Pull a template, fill it in, push it back

```bash
canvasgrade pull -c 786 -a 7081 -o p2.xlsx --with-grades
```

One row per enrolled student with their Canvas id already filled in, one column per
rubric criterion, existing scores pre-filled. Type in the numbers and push the same file
back — no ids to copy by hand.

## The GUI

```bash
canvasgrade gui
```

Pick the course and assignment, drop the spreadsheet, correct anything the detector got
wrong, preview the diff, push. It binds to `127.0.0.1` and your access token never
leaves the server process.

## Plots

```bash
canvasgrade plot grades.xlsx -o dist.pdf --by-criterion
```

<div align="center">
  <img src="https://raw.githubusercontent.com/4rthurCai/canvasgrade/master/docs/grade-distribution.png" alt="Grade distribution with a per-criterion breakdown" width="720">
</div>

The totals as a histogram against a fitted normal and a kernel density estimate;
`--by-criterion` adds the panel showing each criterion's mean as a fraction of its
maximum, which is the view that tells you a rubric needs adjusting.

## Safety

- `-n/--dry-run` shows exactly what would change and sends nothing.
- Nothing is written until you answer `y`. The prompt defaults to no, says whether a
  rubric will be created, and repeats the warning count. Declining leaves nothing
  behind: the rubric is created *after* you confirm, not before.
- Errors block the push. Warnings do not, because several of them fire on ordinary runs
  — grading half a class, or leaving criteria blank. `--strict` promotes every warning
  to an error, which is the right default for a script.
- Scores above a criterion's maximum are capped with a warning (`--no-clamp` makes it an
  error). Negative totals, and two rows resolving to the same student, are always
  errors.

## Development

```bash
git clone https://github.com/4rthurCai/canvasgrade && cd canvasgrade
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
.venv/bin/ruff check canvasgrade tests
```

**Never commit a real gradebook.** The fixtures under `tests/fixtures/` are synthetic
and must stay that way; `.gitignore` covers the obvious cases but is not a substitute
for looking at what you are about to commit.

## License

MIT
