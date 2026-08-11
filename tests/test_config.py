"""Credential resolution and the safety rails around it."""

from __future__ import annotations

import stat

import pytest

from canvasgrade.config import Profile, check_permissions, load_profile, write_template
from canvasgrade.errors import ConfigError

pytestmark = pytest.mark.unit

CONFIG = """
api_url = "canvas.example.edu"
api_key = "file-token"

[profiles.vv186]
course_id = 786
assignment_id = 7081

[profiles.other]
api_key = "other-token"
"""


@pytest.fixture
def config_file(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(CONFIG)
    return path


def test_defaults_come_from_the_top_level_table(config_file) -> None:
    profile = load_profile(path=config_file, env={})
    assert profile.api_key == "file-token"
    assert profile.api_url == "https://canvas.example.edu/"


def test_a_named_profile_adds_its_own_ids(config_file) -> None:
    profile = load_profile("vv186", path=config_file, env={})
    assert (profile.course_id, profile.assignment_id) == (786, 7081)
    assert profile.api_key == "file-token"  # inherited from the top level


def test_a_profile_can_override_the_key(config_file) -> None:
    assert load_profile("other", path=config_file, env={}).api_key == "other-token"


def test_the_environment_beats_the_file(config_file) -> None:
    profile = load_profile(path=config_file, env={"CANVAS_API_KEY": "env-token"})
    assert profile.api_key == "env-token"


def test_cli_arguments_beat_everything(config_file) -> None:
    profile = load_profile(path=config_file, env={"CANVAS_API_KEY": "env-token"})
    assert profile.merged_with(api_key="cli-token").api_key == "cli-token"


def test_none_overrides_do_not_erase_a_resolved_value(config_file) -> None:
    profile = load_profile(path=config_file, env={})
    assert profile.merged_with(api_key=None).api_key == "file-token"


def test_an_unknown_profile_lists_the_ones_that_exist(config_file) -> None:
    with pytest.raises(ConfigError, match="available: other, vv186"):
        load_profile("nope", path=config_file, env={})


def test_a_broken_config_file_says_so(tmp_path) -> None:
    path = tmp_path / "bad.toml"
    path.write_text("this is not = = toml")
    with pytest.raises(ConfigError, match="not valid TOML"):
        load_profile(path=path, env={})


def test_a_missing_file_is_not_an_error(tmp_path) -> None:
    profile = load_profile(path=tmp_path / "absent.toml", env={})
    assert profile.api_key is None


def test_a_missing_key_explains_the_three_ways_to_set_one() -> None:
    with pytest.raises(ConfigError, match="CANVAS_API_KEY"):
        Profile().require_key()


def test_missing_ids_are_reported_separately() -> None:
    with pytest.raises(ConfigError, match="course id"):
        Profile(api_key="k").require_course()
    with pytest.raises(ConfigError, match="assignment id"):
        Profile(api_key="k").require_assignment()


def test_the_key_is_redacted_for_display() -> None:
    redacted = Profile(api_key="abcdefghijklmnop").redacted_key
    assert redacted == "abcd...mnop"
    assert Profile(api_key="short").redacted_key == "***"
    assert Profile().redacted_key == "<unset>"


def test_a_written_template_is_owner_only(tmp_path) -> None:
    path = write_template(tmp_path / "cfg.toml")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert check_permissions(path) is None


def test_a_world_readable_config_is_flagged(tmp_path) -> None:
    path = write_template(tmp_path / "cfg.toml")
    path.chmod(0o644)
    assert "chmod 600" in check_permissions(path)


def test_writing_over_an_existing_config_needs_force(tmp_path) -> None:
    path = write_template(tmp_path / "cfg.toml")
    with pytest.raises(ConfigError, match="--force"):
        write_template(path)
    assert write_template(path, overwrite=True) == path
