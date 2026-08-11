"""Run the GUI.

Binds to loopback by default. The Canvas token lives only in this process, so anyone
who can reach the port can grade as you - which is exactly why it is not exposed.
"""

from __future__ import annotations

import threading
import webbrowser

import click
import uvicorn

from canvasgrade.config import load_profile
from canvasgrade.web.app import create_app

BROWSER_DELAY_SECONDS = 1.0


def serve(
    *,
    profile_name: str | None = None,
    api_url: str | None = None,
    api_key: str | None = None,
    course_id: int | None = None,
    assignment_id: int | None = None,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
) -> None:
    """Start the local web GUI and, unless asked not to, open it."""
    profile = load_profile(profile_name).merged_with(
        api_url=api_url, api_key=api_key, course_id=course_id, assignment_id=assignment_id
    )
    profile.require_key()

    if host not in ("127.0.0.1", "localhost", "::1"):
        click.secho(
            f"warning: binding to {host} exposes your Canvas token to anyone who can reach "
            "this port. Use 127.0.0.1 unless you know you need otherwise.",
            fg="yellow",
        )

    url = f"http://{host}:{port}/"
    click.secho(f"canvasgrade GUI running at {url}", fg="green")
    click.echo("Press Ctrl+C to stop.")

    if open_browser:
        threading.Timer(BROWSER_DELAY_SECONDS, lambda: webbrowser.open(url)).start()

    uvicorn.run(create_app(profile), host=host, port=port, log_level="warning")
