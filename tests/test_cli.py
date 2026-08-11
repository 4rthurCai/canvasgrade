"""The command line, driven through click's test runner."""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from canvasgrade import cli
from tests.conftest import FakeSession

pytestmark = pytest.mark.integration


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def offline(monkeypatch, fake_course):
    """Point the CLI at fakes instead of Canvas, with credentials already resolved."""
    from canvasgrade.config import Profile

    profile = Profile(api_url="https://canvas.example.invalid/", api_key="token")
    monkeypatch.setattr(cli, "load_profile", lambda *a, **k: profile)
    monkeypatch.setattr(cli, "check_permissions", lambda *a, **k: None)
    monkeypatch.setattr(cli, "CanvasSession", lambda p: FakeSession(p, fake_course))
    return fake_course


class TestInspect:
    def test_reports_the_mapping_and_the_totals(self, runner, gradebook_path) -> None:
        result = runner.invoke(cli.main, ["inspect", str(gradebook_path)])
        assert result.exit_code == 0
        assert "criterion" in result.output
        assert "4 students" in result.output

    def test_include_narrows_the_criteria(self, runner, gradebook_path) -> None:
        result = runner.invoke(cli.main, ["inspect", str(gradebook_path), "-I", "M1 *"])
        assert result.exit_code == 0
        assert "2 criteria" in result.output
        assert "30" in result.output

    def test_a_filter_that_matches_nothing_fails_cleanly(self, runner, gradebook_path) -> None:
        result = runner.invoke(cli.main, ["inspect", str(gradebook_path), "-I", "M9 *"])
        assert result.exit_code != 0
        assert not isinstance(result.exception, AttributeError)


class TestPush:
    def _args(self, path, *extra: str) -> list[str]:
        return [
            "push",
            str(path),
            "-c",
            "786",
            "-a",
            "7081",
            "-I",
            "M1 *",
            *extra,
        ]

    def test_a_dry_run_changes_nothing(self, runner, gradebook_path, offline) -> None:
        result = runner.invoke(cli.main, self._args(gradebook_path, "--create-rubric", "--dry-run"))
        assert result.exit_code == 0, result.output
        assert "Dry run" in result.output
        assert not offline.created

    def test_the_preview_names_the_students(self, runner, gradebook_path, offline) -> None:
        result = runner.invoke(cli.main, self._args(gradebook_path, "--create-rubric", "-n"))
        assert "Ada Lovelace" in result.output
        assert "3 students ready" in result.output

    def test_confirmation_is_required_before_writing(self, runner, gradebook_path, offline) -> None:
        result = runner.invoke(cli.main, self._args(gradebook_path, "--create-rubric"), input="n\n")
        assert "Cancelled" in result.output

    def test_declining_leaves_no_rubric_behind(self, runner, gradebook_path, offline) -> None:
        # The rubric must not be created until after the user says yes, or answering
        # "no" would still leave one attached to the assignment.
        result = runner.invoke(cli.main, self._args(gradebook_path, "--create-rubric"), input="n\n")
        assert not offline.created, "a rubric was created despite the push being declined"
        assert "nothing was created or changed" in result.output

    def test_the_prompt_says_a_rubric_will_be_created(self, runner, gradebook_path, offline) -> None:
        result = runner.invoke(cli.main, self._args(gradebook_path, "--create-rubric"), input="n\n")
        assert "create a 2-criterion rubric" in result.output

    def test_yes_skips_the_prompt_and_pushes(self, runner, gradebook_path, offline) -> None:
        result = runner.invoke(cli.main, self._args(gradebook_path, "--create-rubric", "-y"))
        assert result.exit_code == 0, result.output
        assert "Pushed 3 grades" in result.output
        assert offline.created  # the rubric really was created this time

    def test_the_prompt_repeats_the_warning_count(self, runner, gradebook_path, offline) -> None:
        # Warnings scroll past above the prompt; the decision point must restate them.
        result = runner.invoke(cli.main, self._args(gradebook_path, "--create-rubric"), input="n\n")
        assert "despite" in result.output and "warning(s)" in result.output

    def test_strict_turns_warnings_into_a_refusal(self, runner, gradebook_path, offline) -> None:
        result = runner.invoke(cli.main, self._args(gradebook_path, "--create-rubric", "--strict", "-y"))
        assert result.exit_code == 1
        assert "--strict" in result.output
        assert not offline.created

    def test_without_strict_the_same_run_goes_through(self, runner, gradebook_path, offline) -> None:
        result = runner.invoke(cli.main, self._args(gradebook_path, "--create-rubric", "-y"))
        assert result.exit_code == 0, result.output
        assert "Pushed 3 grades" in result.output

    def test_yes_says_out_loud_that_it_is_ignoring_warnings(self, runner, gradebook_path, offline) -> None:
        result = runner.invoke(cli.main, self._args(gradebook_path, "--create-rubric", "-y"))
        assert "because --yes was given" in result.output

    def test_total_column_is_accepted(self, runner, gradebook_path, offline) -> None:
        result = runner.invoke(
            cli.main, self._args(gradebook_path, "--create-rubric", "-n", "--total-column", "M1 Total (30)")
        )
        assert result.exit_code == 0, result.output

    def test_an_unknown_total_column_fails_cleanly(self, runner, gradebook_path, offline) -> None:
        result = runner.invoke(cli.main, self._args(gradebook_path, "--create-rubric", "-n", "--total-column", "Nope"))
        assert result.exit_code != 0
        assert not isinstance(result.exception, AttributeError)

    def test_missing_ids_are_reported_not_traced(self, runner, gradebook_path, offline) -> None:
        result = runner.invoke(cli.main, ["push", str(gradebook_path), "-I", "M1 *", "-n"])
        assert result.exit_code != 0


class TestConfig:
    def test_show_redacts_the_token(self, runner, monkeypatch, tmp_path) -> None:
        from canvasgrade.config import Profile

        monkeypatch.setattr(cli, "load_profile", lambda *a, **k: Profile(api_key="abcdefghijklmnop"))
        monkeypatch.setattr(cli, "check_permissions", lambda *a, **k: None)
        result = runner.invoke(cli.main, ["config", "show"])
        assert "abcd...mnop" in result.output
        assert "abcdefghijklmnop" not in result.output


class TestPlot:
    def test_writes_an_image(self, runner, gradebook_path, tmp_path) -> None:
        output = tmp_path / "dist.png"
        result = runner.invoke(cli.main, ["plot", str(gradebook_path), "-I", "M1 *", "-o", str(output)])
        assert result.exit_code == 0, result.output
        assert output.exists() and output.stat().st_size > 1000

    def test_the_criterion_panel_is_optional(self, runner, gradebook_path, tmp_path) -> None:
        plain = tmp_path / "plain.png"
        detailed = tmp_path / "detailed.png"
        runner.invoke(cli.main, ["plot", str(gradebook_path), "-I", "M1 *", "-o", str(plain)])
        runner.invoke(cli.main, ["plot", str(gradebook_path), "-I", "M1 *", "-o", str(detailed), "--by-criterion"])
        assert detailed.stat().st_size > plain.stat().st_size


def test_version_and_help_work(runner) -> None:
    assert runner.invoke(cli.main, ["--version"]).exit_code == 0
    assert "push" in runner.invoke(cli.main, ["--help"]).output
