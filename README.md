# canvasgrade

Build a Canvas rubric straight from your grading spreadsheet, then push every score,
comment and total back to Canvas in one batch.

No rubric id to dig out of Chrome DevTools. No reshaping your gradebook into a bare
positional CSV. No clicking through SpeedGrader to "warm up" a new rubric.

```bash
canvasgrade inspect "p1 tech.xlsx"                 # see how your sheet will be read
canvasgrade push "p1 tech.xlsx" --create-rubric -n # preview the changes
canvasgrade push "p1 tech.xlsx" --create-rubric    # sheet -> rubric -> grades
canvasgrade gui                                    # or do it all in a browser
```

## Why

Grading spreadsheets are messy in specific, predictable ways: three milestones side by
side, team header rows with nothing in them, a `Ratio` column, running subtotals, a
column of grader initials. canvasgrade reads that sheet as-is and tells you what it
made of every column before it writes anything.

## Install

```bash
pip3 install "canvasgrade[all]"       # CLI + web GUI + plots
pip3 install canvasgrade              # CLI only
pip3 install "canvasgrade[web]"       # CLI + web GUI
```

Python 3.11 or newer. To run the very latest instead of the last release:

```bash
pip3 install "git+https://github.com/4rthurCai/canvasgrade#egg=canvasgrade[all]"
```

## Set up credentials

Generate an access token on Canvas under **Account → Settings → New Access Token**, then:

```bash
canvasgrade config init     # writes ~/.canvasgrade.toml, chmod 600
canvasgrade config show     # check what resolved, token redacted
canvasgrade courses         # confirm it works, and list course ids
```

`~/.canvasgrade.toml`:

```toml
api_url = "https://jicanvas.com/"
api_key = "your-token"

[profiles.vv186]
course_id = 786
assignment_id = 7081
```

Then `canvasgrade push grades.xlsx -p vv186`. `$CANVAS_API_KEY` and `--api-key` also
work; the environment beats the file and the flag beats both.

## How your spreadsheet is read

A column header that declares a maximum becomes a rubric criterion:

| Header | Read as |
|---|---|
| `Code Quality (35)` | criterion "Code Quality", out of 35 |
| `Design [10]` | criterion "Design", out of 10 |
| `设计 （10分）`, `【设计 10分】` | criterion "设计", out of 10 |
| `题目一 [10']` | criterion "题目一", out of 10 — the prime is decoration |
| `[10]` and `[10']` | two criteria out of 10, named by their markers |
| `Student`, `ID`, `SIS Login ID` | student identity |
| `P1 Total (70)` | the assignment total |
| `Ratio`, `Weight`, `系数` | a multiplier (ignored unless `--apply-ratio`) |
| `Code Quality comment` | per-student comment on that criterion |
| `Joe`, `Vonda` | ignored — numeric, but no declared maximum |

Rules worth knowing:

- **Only headers with an explicit maximum become criteria.** Round or square brackets,
  ASCII or full-width, optionally with a unit (`分`, `pts`) and a trailing prime. That
  rule keeps grader initials and bookkeeping columns out of your rubric. If *no* header
  in the sheet declares a maximum, the detector falls back to inferring one from the
  data.
- **A bare trailing number is never a score.** `Milestone 2` and `【项目 2】` keep their
  names, because they are far more likely to be labels than two-point criteria. Inside
  brackets a number only counts as a score if it carries a unit: `【设计 10分】` works,
  `【设计 10】` does not.
- **Brackets must pair.** `Thing (10]` is left alone rather than half-parsed.
- **When several columns look like totals or ratios, the last one wins.** Per-milestone
  subtotals are ignored in favour of the final figure.
- **A row with a name but no id and no scores is a team header.** Rows below it inherit
  that team name; the header row itself is not a student.

Run `canvasgrade inspect <file>` to see every decision and the reason for it. Nothing in
`inspect` touches the network.

## One sheet, several assignments

A sheet covering three milestones has more criteria than any single Canvas assignment
wants. Filter with globs:

```bash
canvasgrade push "p1 tech.xlsx" --create-rubric -I 'P1M1 *' -a 7081
canvasgrade push "p1 tech.xlsx" --create-rubric -I 'P1M2 *' -a 7082
```

`-E/--exclude` drops matching columns instead. Comment columns follow their criterion,
so a filtered push never carries orphaned feedback.

**Filtering changes the criteria, not the total.** With `--total auto` the grade still
comes from whichever total column the sheet ends with — for a three-milestone sheet that
is the whole-project total, not the milestone you just filtered down to. Pushing one
milestone usually means `--total sum` as well:

```bash
canvasgrade push "p1 tech.xlsx" --create-rubric -I 'P1M1 *' --total sum -a 7081
```

Forget it and the rubric will show the milestone breakdown while the posted grade is the
project total. `--dry-run` shows both, so the mismatch is visible before you push.

## Where the total comes from

| Flag | Behaviour |
|---|---|
| `--total auto` (default) | the sheet's total column when it has one, otherwise the sum of criteria |
| `--total sum` | always add the criteria up |
| `--total sheet` | always use the total column, and fail if it is empty |
| `--total-column 'P1M1 Total (70)'` | pick which column *is* the total |
| `--apply-ratio` | multiply the total by the ratio column |

When several columns look like totals the detector keeps the last one, which in a
multi-milestone sheet is the whole-project figure. `--total-column` overrides that. The
name may be given with or without its max suffix, and matching is case-insensitive:

```bash
canvasgrade push "p1 tech.xlsx" -I 'P1M1 *' --total-column 'P1M1 Total' -a 7081
```

`--apply-ratio` is off by default because a total column has usually had the ratio
applied to it already in the spreadsheet.

`--use-for-grading` lets Canvas recompute the grade from the rubric total. It is off by
default, since it would overwrite the total from your sheet.

## Pull a template, fill it in, push it back

```bash
canvasgrade pull -c 786 -a 7081 -o p2.xlsx --with-grades
```

You get one row per enrolled student with their Canvas id already filled in, one column
per rubric criterion, and existing scores pre-filled. Type in the numbers and push the
same file back — no ids to copy by hand.

## The GUI

```bash
canvasgrade gui
```

Opens a local page: pick the course and assignment, drop the spreadsheet, correct
anything the detector got wrong, preview the diff, push. It binds to `127.0.0.1` and the
access token never leaves the server process.

## Plots

```bash
canvasgrade plot "p1 tech.xlsx" -I 'P1M1 *' -o dist.pdf --by-criterion
```

The totals as a histogram with a box plot, a fitted normal and a kernel density
estimate; `--by-criterion` adds a panel showing the mean of each criterion as a fraction
of its maximum, which is the view that tells you a rubric needs adjusting.

## Safety

Every write is preceded by a preview and a confirmation:

- `-n/--dry-run` shows exactly what would change and exits without contacting Canvas
  to write anything — including which rubric *would* be created.
- Nothing is written until you answer `y`. The prompt defaults to no, names the number
  of grades, says whether a rubric will be created, and repeats the warning count —
  warnings scroll past above it, so they are restated at the moment of decision.
  Declining leaves nothing behind: with `--create-rubric` the rubric is created *after*
  you confirm, not before.
- Errors block the push. Warnings do not, because several of them fire on perfectly
  ordinary runs — grading half a class, or leaving criteria blank. Use `--strict` to
  promote every warning to an error, which is the right default for a script.
- `-y/--yes` skips the prompt, and says out loud when it is skipping past warnings.
  Combine it with `--strict` in automation so a surprising sheet stops the run.
- Scores above a criterion's maximum are capped with a warning (`--no-clamp` to make it
  an error instead). Negative totals are always an error. Two rows resolving to the same
  student is always an error.
- Students are matched by Canvas id first, then SIS/login id, then name. Name matching
  handles extra tokens and small typos, and refuses to guess when two students are
  equally plausible.

## Development

```bash
git clone <this repo> && cd canvasgrade
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
.venv/bin/ruff check canvasgrade tests
```

**Never commit a real gradebook.** The fixtures under `tests/fixtures/` are synthetic and
must stay that way; `.gitignore` covers the obvious cases but it is not a substitute for
checking what you are about to commit.

## License

MIT
