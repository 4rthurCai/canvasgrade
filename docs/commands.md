# Command reference

Every command also has built-in help:

```bash
canvasgrade help              # the command list
canvasgrade help push         # one command in detail
canvasgrade push --help       # the same thing
```

Commands that talk to Canvas share these:

| Option | Meaning |
|---|---|
| `-p, --profile NAME` | a named profile from `~/.canvasgrade.toml` |
| `-u, --api-url URL` | Canvas base URL, e.g. `https://jicanvas.com/` |
| `-k, --api-key TOKEN` | access token — prefer `$CANVAS_API_KEY` or the config file |
| `-c, --course-id N` | course id, from the page URL |
| `-a, --assignment-id N` | assignment id, from the page URL |

---

## `inspect` — see how a sheet will be read

Offline. No token, no assignment, no network.

```bash
canvasgrade inspect grades.xlsx
canvasgrade inspect grades.xlsx -I 'P1M1 *'
canvasgrade inspect grades.xlsx --rename 'Q1 (10)=Design'
```

Prints every column with the role it was given and **why**, then the rubric that would
be built from it — criterion names, maxima and the total.

| Option | Meaning |
|---|---|
| `--sheet NAME\|N` | worksheet of an Excel file, by name or index |
| `--no-header` | positional layout: first column is the id, the rest are criteria |
| `-I, --include GLOB` | keep only criteria matching this pattern; repeatable |
| `-E, --exclude GLOB` | drop criteria matching this pattern; repeatable |
| `--id-column NAME` | which column holds the Canvas user id |
| `--total-column NAME` | which column holds the assignment total |
| `--rename COLUMN=NAME` | criterion name students will see; repeatable |
| `--columns-only` | skip the rubric preview |

---

## `push` — send grades to Canvas

```bash
canvasgrade push grades.xlsx --create-rubric --dry-run    # always look first
canvasgrade push grades.xlsx --create-rubric
canvasgrade push grades.xlsx -I 'P1M1 *' --total sum -a 7081
```

**Which rubric** — exactly one of these, or none for the default:

| Option | Meaning |
|---|---|
| *(omitted)* | use the rubric already attached to the assignment |
| `--create-rubric` | build a new one from the column headers |
| `--rubric-id N` | score against an existing rubric (`canvasgrade rubrics` lists them) |
| `--no-rubric` | push totals only, no rubric assessment |

Combining them is refused rather than silently ranked.

| Option | Meaning |
|---|---|
| `--rubric-title TEXT` | title for a rubric being created |
| `--use-for-grading` | let Canvas recompute the grade from the rubric total — **off by default**, since it would overwrite your sheet's total |
| `--rename COLUMN=NAME` | criterion name students see; repeatable |
| `--describe COLUMN=TEXT` | detail Canvas shows when a student opens that criterion; repeatable |

**Where the total comes from**

| Option | Meaning |
|---|---|
| `--total auto` *(default)* | the sheet's total column if it has one, else the sum of criteria |
| `--total sum` | always add the criteria up |
| `--total sheet` | always use the total column; fail if it is empty |
| `--total-column NAME` | which column *is* the total, when several look like one |
| `--apply-ratio` | multiply by the ratio column — **off by default**, a total column usually has it applied already |

**Reading the sheet** — `--sheet`, `--no-header`, `-I/--include`, `-E/--exclude`,
`--id-column` all behave as in `inspect`.

**Scores**

| Option | Meaning |
|---|---|
| `--keep-blank` | leave a blank criterion unscored instead of writing 0 |
| `--no-clamp` | refuse a score above a criterion's maximum instead of capping it |

**Comments**

| Option | Meaning |
|---|---|
| `--comment / --no-comment` | leave a submission comment; off by default |
| `--comment-text TEXT` | comment template; `{timestamp}` is substituted |

Per-criterion feedback comes from the sheet, in a `<criterion> comment` column.

**Before it writes**

| Option | Meaning |
|---|---|
| `-n, --dry-run` | build and print the whole plan, send nothing |
| `-y, --yes` | skip the confirmation; it still says when it is passing warnings |
| `--strict` | treat every warning as an error and refuse — the right default in a script |
| `--batch-size N` | students per bulk request (default 200) |

With `--create-rubric`, the rubric is created **after** you confirm, so declining leaves
nothing behind.

---

## `pull` — download a template to fill in

```bash
canvasgrade pull -o p2.xlsx                  # blank template for the current roster
canvasgrade pull -o p2.xlsx --with-grades    # pre-filled with what is on Canvas
canvasgrade pull -o p2.xlsx --merge          # refresh the roster, keep what you typed
```

One row per enrolled student with their Canvas id already filled in, one column per
rubric criterion. The headers are written so that `push` reads them straight back.

| Option | Meaning |
|---|---|
| `-o, --output PATH` | file to write, `.xlsx` or `.csv` |
| `--with-grades` | pre-fill the scores already on Canvas |
| `--merge` | update the roster in an existing file, keeping scores already entered |
| `--force` | overwrite the file, discarding whatever is in it |

`--merge` exists for the case where the roster changes mid-marking. It takes the current
enrolment as the truth, carries over every score already typed — matched on Canvas id, so
reordering rows or fixing a name cannot lose one — and then says what changed: how many
scores it kept, who joined, who left, and which columns are no longer in the rubric.

`--merge` and `--force` cannot be combined: one keeps your work, the other discards it.

---

## `courses`, `assignments`, `rubrics` — find ids

```bash
canvasgrade courses                # id, name, code
canvasgrade assignments -c 786     # id, name, points, whether a rubric is attached
canvasgrade rubrics -c 786         # id, title, criteria count, points
```

No id ever has to come out of the browser's dev tools.

---

## `plot` — grade distribution

```bash
canvasgrade plot grades.xlsx -o dist.pdf
canvasgrade plot grades.xlsx -o dist.png --by-criterion
```

Offline. The totals as a histogram against a fitted normal and a kernel density
estimate, with a box plot above.

| Option | Meaning |
|---|---|
| `-o, --output PATH` | PNG, PDF or SVG |
| `--by-criterion` | add a panel showing each criterion's mean as a fraction of its maximum |
| `--title TEXT` | plot title |
| `--xmin`, `--xmax` | score axis bounds; `xmax` defaults to the rubric total |
| `--bins N` | histogram bins (default 20) |
| `--dpi N` | output resolution (default 200) |
| `--sheet`, `-I/--include` | as in `inspect` |

---

## `gui` — the browser interface

```bash
canvasgrade gui
```

Pick the course and assignment, drop the spreadsheet, correct anything the detector got
wrong, preview, push. Binds to `127.0.0.1`; the access token stays in the server process
and is never sent to the page.

| Option | Meaning |
|---|---|
| `--host ADDR` | interface to bind (default `127.0.0.1`) |
| `--port N` | port (default 8765) |
| `--no-browser` | do not open a browser window |

Binding to anything other than loopback prints a warning, because anyone who can reach
the port can grade as you.

---

## `config` — credentials

```bash
canvasgrade config init      # write ~/.canvasgrade.toml with owner-only permissions
canvasgrade config show      # what resolved, token redacted
```

```toml
api_url = "https://jicanvas.com/"
api_key = "your-token"

[profiles.vv186]
course_id = 786
assignment_id = 7081
```

Precedence is flag > `$CANVAS_API_KEY` / `$CANVAS_API_URL` > config file. `config show`
warns if the file is readable by other users.

---

## `help`

```bash
canvasgrade help             # the command list
canvasgrade help pull        # one command
```
