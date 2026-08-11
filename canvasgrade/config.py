"""Credential and profile handling.

Precedence, highest first: explicit CLI arguments -> environment variables ->
``~/.canvasgrade.toml``. Keys are kept out of shell history by default; ``--api-key``
still exists but the config file and ``CANVAS_API_KEY`` are the recommended paths.
"""

from __future__ import annotations

import os
import stat
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path

from canvasgrade.errors import ConfigError

DEFAULT_API_URL = "https://jicanvas.com/"
CONFIG_PATH = Path.home() / ".canvasgrade.toml"
ENV_API_URL = "CANVAS_API_URL"
ENV_API_KEY = "CANVAS_API_KEY"
ENV_PROFILE = "CANVASGRADE_PROFILE"

CONFIG_TEMPLATE = """\
# canvasgrade configuration
# Keep this file private: chmod 600 ~/.canvasgrade.toml

api_url = "https://jicanvas.com/"
api_key = "paste-your-canvas-access-token-here"

# Optional named profiles, selected with --profile <name>.
# [profiles.vv186]
# course_id = 786
# assignment_id = 7081
"""


@dataclass(frozen=True)
class Profile:
    """Resolved connection settings for one Canvas instance / course."""

    api_url: str = DEFAULT_API_URL
    api_key: str | None = None
    course_id: int | None = None
    assignment_id: int | None = None
    name: str = "default"

    def merged_with(self, **overrides: object) -> Profile:
        """Return a copy where non-None overrides win."""
        clean = {key: value for key, value in overrides.items() if value is not None}
        return replace(self, **clean)  # type: ignore[arg-type]

    def require_key(self) -> str:
        if not self.api_key:
            raise ConfigError(
                f"No Canvas access token found. Set ${ENV_API_KEY}, run "
                f"'canvasgrade config init' to create {CONFIG_PATH}, or pass --api-key."
            )
        return self.api_key

    def require_course(self) -> int:
        if self.course_id is None:
            raise ConfigError("No course id. Pass --course-id or set it in your profile.")
        return self.course_id

    def require_assignment(self) -> int:
        if self.assignment_id is None:
            raise ConfigError("No assignment id. Pass --assignment-id or set it in your profile.")
        return self.assignment_id

    @property
    def redacted_key(self) -> str:
        if not self.api_key:
            return "<unset>"
        if len(self.api_key) <= 12:
            return "***"
        return f"{self.api_key[:4]}...{self.api_key[-4:]}"


def _read_config_file(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path} is not valid TOML: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"Could not read {path}: {exc}") from exc


def _coerce_int(value: object, field: str) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise ConfigError(f"Config value for '{field}' must be an integer, got {value!r}") from None


def load_profile(
    name: str | None = None,
    *,
    path: Path | None = None,
    env: dict[str, str] | None = None,
) -> Profile:
    """Build a :class:`Profile` from the config file and the environment."""
    env = os.environ if env is None else env
    path = CONFIG_PATH if path is None else path
    data = _read_config_file(path)

    profile_name = name or env.get(ENV_PROFILE) or "default"
    profiles = data.get("profiles", {})
    if not isinstance(profiles, dict):
        raise ConfigError(f"'profiles' in {path} must be a table")

    section: dict[str, object] = {}
    if profile_name != "default":
        found = profiles.get(profile_name)
        if found is None:
            known = ", ".join(sorted(profiles)) or "none defined"
            raise ConfigError(f"Profile '{profile_name}' not found in {path} (available: {known})")
        if not isinstance(found, dict):
            raise ConfigError(f"Profile '{profile_name}' in {path} must be a table")
        section = found

    def pick(key: str) -> object:
        value = section.get(key)
        return data.get(key) if value is None else value

    api_key_raw = pick("api_key")
    return Profile(
        api_url=_normalise_url(str(env.get(ENV_API_URL) or pick("api_url") or DEFAULT_API_URL)),
        api_key=env.get(ENV_API_KEY) or (str(api_key_raw) if api_key_raw else None),
        course_id=_coerce_int(pick("course_id"), "course_id"),
        assignment_id=_coerce_int(pick("assignment_id"), "assignment_id"),
        name=profile_name,
    )


def _normalise_url(url: str) -> str:
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"
    return url.rstrip("/") + "/"


def write_template(path: Path | None = None, *, overwrite: bool = False) -> Path:
    """Create a starter config file with owner-only permissions."""
    path = CONFIG_PATH if path is None else path
    if path.exists() and not overwrite:
        raise ConfigError(f"{path} already exists. Pass --force to overwrite it.")
    path.write_text(CONFIG_TEMPLATE, encoding="utf-8")
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return path


def check_permissions(path: Path | None = None) -> str | None:
    """Return a warning when the config file is readable by other users."""
    path = CONFIG_PATH if path is None else path
    if not path.exists():
        return None
    mode = path.stat().st_mode
    if mode & (stat.S_IRGRP | stat.S_IROTH):
        return f"{path} is readable by other users. Run: chmod 600 {path}"
    return None
