"""Command line interface.

Argument parsing and presentation only - the real work lives in
:mod:`canvasgrade.workflow` so the web GUI can reuse it unchanged.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import click

from canvasgrade import __version__, render
from canvasgrade.canvas.client import CanvasSession
from canvasgrade.canvas.pull import build_template, fetch_existing_scores, fetch_roster, write_template
from canvasgrade.canvas.push import push_grades
from canvasgrade.canvas.rubrics import find_attached_rubric
from canvasgrade.config import CONFIG_PATH, check_permissions, load_profile
from canvasgrade.config import write_template as write_config
from canvasgrade.errors import CanvasGradeError
from canvasgrade.grading.plan import DEFAULT_COMMENT, GradeOptions
from canvasgrade.sheet.reader import list_sheets
from canvasgrade.workflow import RubricRequest, SheetRequest, load_sheet, prepare_push

CONNECTION_HELP = "Canvas connection"


def connection_options(command: Any) -> Any:
    """Attach the options every networked command shares."""
    for option in reversed(
        [
            click.option("-p", "--profile", "profile_name", help="Named profile from your config file."),
            click.option("-u", "--api-url", help="Canvas base URL, e.g. https://jicanvas.com/"),
            click.option("-k", "--api-key", help="Access token. Prefer $CANVAS_API_KEY or the config file."),
            click.option("-c", "--course-id", type=int, help="Course id, from the page URL."),
            click.option("-a", "--assignment-id", type=int, help="Assignment id, from the page URL."),
        ]
    ):
        command = option(command)
    return command


def _session(
    profile_name: str | None,
    api_url: str | None,
    api_key: str | None,
    **overrides: Any,
) -> tuple[CanvasSession, Any]:
    profile = load_profile(profile_name).merged_with(api_url=api_url, api_key=api_key, **overrides)
    warning = check_permissions()
    if warning:
        click.secho(f"warning: {warning}", fg="yellow", err=True)
    return CanvasSession(profile), profile


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(version=__version__, prog_name="canvasgrade")
def main() -> None:
    """Build Canvas rubrics from a spreadsheet and push grades back."""


# --------------------------------------------------------------------------- inspect


@main.command()
@click.argument("input_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--sheet", default="0", show_default=True, help="Worksheet name or index for Excel files.")
@click.option("--no-header", is_flag=True, help="Treat the file as positional: id first, then criteria.")
@click.option("-I", "--include", multiple=True, help="Only keep criteria matching this glob, e.g. 'P1M1 *'.")
@click.option("-E", "--exclude", multiple=True, help="Drop criteria matching this glob.")
@click.option("--total-column", help="Name of the column holding the total.")
def inspect(
    input_file: Path,
    sheet: str,
    no_header: bool,
    include: tuple[str, ...],
    exclude: tuple[str, ...],
    total_column: str | None,
) -> None:
    """Show how a spreadsheet will be read. Touches no network."""
    out = render.console()
    sheets = list_sheets(input_file)
    if len(sheets) > 1:
        out.print(f"[dim]Worksheets: {', '.join(sheets)} (using {sheet!r})[/]")

    prepared = load_sheet(
        SheetRequest(
            path=input_file,
            sheet=_parse_sheet(sheet),
            has_header=not no_header,
            include=include,
            exclude=exclude,
            total_column=total_column,
        )
    )
    out.print(render.mapping_table(prepared.mapping))
    out.print()
    out.print(f"[bold]{render.rows_summary(prepared.rows)}[/] from {prepared.data.n_rows} rows in the file")

    criteria = prepared.mapping.criteria_columns
    if criteria:
        total = sum(c.points or 0 for c in criteria)
        out.print(f"[bold]{len(criteria)} criteria[/] worth [bold]{total:g}[/] points in total")
    else:
        out.print("[yellow]No criteria found. Headers need a max score, e.g. 'Code Quality (35)'.[/]")


# --------------------------------------------------------------------------- push


@main.command()
@click.argument("input_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@connection_options
@click.option("--sheet", default="0", show_default=True, help="Worksheet name or index for Excel files.")
@click.option("--no-header", is_flag=True, help="Treat the file as positional: id first, then criteria.")
@click.option("-I", "--include", multiple=True, help="Only keep criteria matching this glob, e.g. 'P1M1 *'.")
@click.option("-E", "--exclude", multiple=True, help="Drop criteria matching this glob.")
@click.option("--create-rubric", is_flag=True, help="Build a new rubric from the column headers.")
@click.option("--rubric-id", type=int, help="Score against this existing rubric instead.")
@click.option("--no-rubric", is_flag=True, help="Push totals only, without a rubric assessment.")
@click.option("--rubric-title", help="Title for a rubric being created.")
@click.option("--use-for-grading", is_flag=True, help="Let Canvas derive the grade from the rubric total.")
@click.option(
    "--total",
    type=click.Choice(["auto", "sheet", "sum"]),
    default="auto",
    show_default=True,
    help="Where the assignment total comes from.",
)
@click.option(
    "--total-column",
    help="Name of the column holding the total, when the detector picks the wrong one.",
)
@click.option("--apply-ratio", is_flag=True, help="Multiply the total by the sheet's ratio column.")
@click.option("--strict", is_flag=True, help="Treat warnings as errors and refuse to push.")
@click.option("--comment/--no-comment", "add_comment", default=False, help="Leave a submission comment.")
@click.option("--comment-text", default=DEFAULT_COMMENT, show_default=True, help="Comment template.")
@click.option("--keep-blank", is_flag=True, help="Leave blank criteria unscored instead of writing 0.")
@click.option("--no-clamp", is_flag=True, help="Fail instead of capping scores above a criterion's max.")
@click.option("--batch-size", default=200, show_default=True, help="Students per bulk request.")
@click.option("-n", "--dry-run", is_flag=True, help="Show what would change and stop.")
@click.option("-y", "--yes", is_flag=True, help="Do not ask for confirmation.")
def push(input_file: Path, profile_name: str | None, api_url: str | None, api_key: str | None, **opts: Any) -> None:
    """Push grades from a spreadsheet to Canvas."""
    out = render.console()
    session, profile = _session(
        profile_name,
        api_url,
        api_key,
        course_id=opts["course_id"],
        assignment_id=opts["assignment_id"],
    )

    def prepare(*, dry_run: bool) -> Any:
        return prepare_push(
            session,
            course_id=profile.require_course(),
            assignment_id=profile.require_assignment(),
            sheet_request=SheetRequest(
                path=input_file,
                sheet=_parse_sheet(opts["sheet"]),
                has_header=not opts["no_header"],
                include=opts["include"],
                exclude=opts["exclude"],
                total_column=opts["total_column"],
            ),
            rubric_request=RubricRequest(
                mode=_rubric_mode(opts),
                rubric_id=opts["rubric_id"],
                title=opts["rubric_title"],
                use_for_grading=opts["use_for_grading"],
            ),
            options=GradeOptions(
                total=opts["total"],
                apply_ratio=opts["apply_ratio"],
                add_comment=opts["add_comment"],
                comment_template=opts["comment_text"],
                missing_as_zero=not opts["keep_blank"],
                clamp=not opts["no_clamp"],
            ),
            dry_run=dry_run,
        )

    # Always preview against a stand-in rubric. Creating it for real is deferred until
    # after the confirmation, so answering "no" leaves nothing behind on Canvas.
    prepared = prepare(dry_run=True)
    plan = prepared.plan.with_warnings_as_errors() if opts["strict"] else prepared.plan
    out.print(f"[bold]{prepared.assignment.name}[/] (id {prepared.assignment.id})", end="")
    if prepared.assignment.points_possible is not None:
        out.print(f" [dim]out of {prepared.assignment.points_possible:g}[/]")
    else:
        out.print()
    for note in prepared.notes:
        out.print(f"  [dim]{note}[/]")
    out.print()

    if prepared.rubric:
        out.print(render.rubric_table(prepared.rubric))
        out.print()
    out.print(render.plan_table(plan))
    out.print()
    render.print_issues(out, plan)
    out.print()
    out.print(render.plan_summary(plan))

    if opts["dry_run"]:
        out.print("\n[bold]Dry run - nothing was sent to Canvas.[/]")
        return
    if not plan.is_pushable:
        reason = "warnings (--strict)" if opts["strict"] and plan.errors else "errors"
        out.print(f"\n[bold red]Refusing to push while there are {reason}.[/]")
        sys.exit(1)

    prompt = f"\nPush {len(plan.entries)} grades"
    if prepared.is_preview_only:
        prompt += f" and create a {len(prepared.rubric.criteria)}-criterion rubric"
    if plan.warnings:
        # Say it again at the moment of decision: the warnings scrolled past above.
        prompt += f" despite {len(plan.warnings)} warning(s)"
    if opts["yes"] and plan.warnings:
        out.print(f"[yellow]Pushing despite {len(plan.warnings)} warning(s) because --yes was given.[/]")
    if not opts["yes"] and not click.confirm(f"{prompt}?", default=False):
        out.print("Cancelled - nothing was created or changed.")
        return

    if prepared.is_preview_only:
        # Only now does the rubric actually get created.
        prepared = prepare(dry_run=False)
        plan = prepared.plan
        for note in prepared.notes:
            out.print(f"  [dim]{note}[/]")

    with out.status("Uploading...") as status:

        def on_progress(stage: str, done: int, total: int) -> None:
            status.update(f"{stage.capitalize()} {done}/{total}")

        course = session.course(profile.require_course())
        assignment = session.assignment(course, profile.require_assignment())
        result = push_grades(
            assignment,
            plan.entries,
            batch_size=opts["batch_size"],
            on_progress=on_progress,
        )

    if result.ok:
        out.print(f"[bold green]Pushed {result.submitted} grades.[/]")
    else:
        out.print(f"[bold red]{len(result.failed)} of {len(result.batches)} batches failed.[/]")
        for batch in result.failed:
            out.print(f"  [red]{batch.state}[/]: {batch.message}")
        sys.exit(1)
    out.print(f"[dim]{session.speedgrader_url(profile.require_course(), profile.require_assignment())}[/]")


# --------------------------------------------------------------------------- pull


@main.command()
@connection_options
@click.option(
    "-o",
    "--output",
    required=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Template to write (.xlsx or .csv).",
)
@click.option("--with-grades", is_flag=True, help="Pre-fill the scores already on Canvas.")
@click.option("--force", is_flag=True, help="Overwrite the output file if it exists.")
def pull(
    profile_name: str | None,
    api_url: str | None,
    api_key: str | None,
    output: Path,
    with_grades: bool,
    force: bool,
    **ids: Any,
) -> None:
    """Download a ready-to-fill grading template for an assignment."""
    out = render.console()
    if output.exists() and not force:
        raise click.ClickException(f"{output} already exists. Pass --force to overwrite it.")

    session, profile = _session(profile_name, api_url, api_key, **ids)
    course = session.course(profile.require_course())
    assignment = session.assignment(course, profile.require_assignment())

    _, criteria = find_attached_rubric(assignment)
    roster = fetch_roster(course)
    existing = fetch_existing_scores(assignment, criteria) if (with_grades and criteria) else {}

    frame = build_template(roster, criteria, existing=existing)
    write_template(frame, output)

    out.print(f"[bold green]Wrote {output}[/]")
    out.print(f"  {len(roster.entries)} students, {len(criteria)} criteria")
    if not criteria:
        out.print("  [yellow]No rubric attached, so the template has no criterion columns.[/]")
        out.print("  [dim]Add columns like 'Code Quality (35)' then push with --create-rubric.[/]")


# --------------------------------------------------------------------------- listing


@main.command()
@connection_options
def courses(profile_name: str | None, api_url: str | None, api_key: str | None, **ids: Any) -> None:
    """List your courses and their ids."""
    out = render.console()
    session, _ = _session(profile_name, api_url, api_key)
    from rich.table import Table

    table = Table(header_style="bold")
    table.add_column("id", justify="right")
    table.add_column("Course")
    table.add_column("Code", style="dim")
    for course in session.courses():
        table.add_row(str(course.id), course.name, course.code)
    out.print(table)


@main.command()
@connection_options
def assignments(profile_name: str | None, api_url: str | None, api_key: str | None, **ids: Any) -> None:
    """List a course's assignments, their ids, and whether a rubric is attached."""
    out = render.console()
    session, profile = _session(profile_name, api_url, api_key, **ids)
    from rich.table import Table

    table = Table(header_style="bold")
    table.add_column("id", justify="right")
    table.add_column("Assignment")
    table.add_column("Points", justify="right")
    table.add_column("Rubric", style="dim")
    for item in session.assignments(session.course(profile.require_course())):
        points = f"{item.points_possible:g}" if item.points_possible is not None else "-"
        table.add_row(str(item.id), item.name, points, str(item.rubric_id or "-"))
    out.print(table)


# --------------------------------------------------------------------------- config


@main.group()
def config() -> None:
    """Manage your saved Canvas credentials."""


@config.command("init")
@click.option("--force", is_flag=True, help="Overwrite an existing config file.")
def config_init(force: bool) -> None:
    """Create a starter config file with owner-only permissions."""
    path = write_config(overwrite=force)
    click.secho(f"Wrote {path}", fg="green")
    click.echo("Add your access token, then try: canvasgrade courses")


@config.command("show")
@click.option("-p", "--profile", "profile_name", help="Profile to display.")
def config_show(profile_name: str | None) -> None:
    """Show the resolved settings, with the token redacted."""
    profile = load_profile(profile_name)
    click.echo(f"config file:   {CONFIG_PATH} ({'found' if CONFIG_PATH.exists() else 'missing'})")
    click.echo(f"profile:       {profile.name}")
    click.echo(f"api url:       {profile.api_url}")
    click.echo(f"api key:       {profile.redacted_key}")
    click.echo(f"course id:     {profile.course_id or '-'}")
    click.echo(f"assignment id: {profile.assignment_id or '-'}")
    warning = check_permissions()
    if warning:
        click.secho(f"warning: {warning}", fg="yellow")


# --------------------------------------------------------------------------- gui


@main.command()
@connection_options
@click.option("--host", default="127.0.0.1", show_default=True, help="Interface to bind.")
@click.option("--port", default=8765, show_default=True, help="Port to listen on.")
@click.option("--no-browser", is_flag=True, help="Do not open a browser window.")
def gui(
    profile_name: str | None,
    api_url: str | None,
    api_key: str | None,
    host: str,
    port: int,
    no_browser: bool,
    **ids: Any,
) -> None:
    """Open the point-and-click interface in your browser."""
    try:
        from canvasgrade.web.server import serve
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise click.ClickException(
            "The GUI needs the web extra. Install it with: pip install 'canvasgrade[web]'"
        ) from exc
    serve(
        profile_name=profile_name,
        api_url=api_url,
        api_key=api_key,
        host=host,
        port=port,
        open_browser=not no_browser,
    )


# --------------------------------------------------------------------------- plot


@main.command()
@click.argument("input_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "-o",
    "--output",
    required=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="PNG/PDF/SVG to write.",
)
@click.option("--sheet", default="0", show_default=True, help="Worksheet name or index for Excel files.")
@click.option("-I", "--include", multiple=True, help="Only plot criteria matching this glob.")
@click.option("--title", default="Grades Plot", show_default=True, help="Plot title.")
@click.option("--xmin", type=float, default=0.0, show_default=True, help="Lower bound of the score axis.")
@click.option("--xmax", type=float, help="Upper bound of the score axis. Defaults to the rubric total.")
@click.option("--bins", default=20, show_default=True, help="Histogram bins.")
@click.option("--by-criterion", is_flag=True, help="Add a per-criterion panel below the totals.")
@click.option("--dpi", default=200, show_default=True, help="Output resolution.")
def plot(
    input_file: Path,
    output: Path,
    sheet: str,
    include: tuple[str, ...],
    title: str,
    xmin: float,
    xmax: float | None,
    bins: int,
    by_criterion: bool,
    dpi: int,
) -> None:
    """Plot the grade distribution for a spreadsheet."""
    try:
        from canvasgrade.plotting import plot_sheet
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise click.ClickException(
            "Plotting needs the plot extra. Install it with: pip install 'canvasgrade[plot]'"
        ) from exc

    prepared = load_sheet(SheetRequest(path=input_file, sheet=_parse_sheet(sheet), include=include))
    plot_sheet(
        prepared,
        output=output,
        title=title,
        xmin=xmin,
        xmax=xmax,
        bins=bins,
        by_criterion=by_criterion,
        dpi=dpi,
    )
    click.secho(f"Wrote {output}", fg="green")


# --------------------------------------------------------------------------- helpers


def _parse_sheet(value: str) -> str | int:
    """Excel worksheets can be addressed by index or by name."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


def _rubric_mode(opts: dict[str, Any]) -> str:
    if opts["no_rubric"]:
        return "none"
    if opts["create_rubric"]:
        return "create"
    if opts["rubric_id"]:
        return "existing"
    return "attached"


def run() -> None:
    """Entry point that turns expected failures into clean messages."""
    try:
        main(standalone_mode=False)
    except click.Abort:
        click.echo("Cancelled.", err=True)
        sys.exit(130)
    except click.ClickException as exc:
        exc.show()
        sys.exit(exc.exit_code)
    except CanvasGradeError as exc:
        click.secho(f"error: {exc}", fg="red", err=True)
        sys.exit(1)


if __name__ == "__main__":
    run()
