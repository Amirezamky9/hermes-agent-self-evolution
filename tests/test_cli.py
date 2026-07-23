"""Tests for CLI help output (no LLM calls, just argument parsing)."""

import pytest
from click.testing import CliRunner
from evolution.cli import cli


@pytest.fixture
def runner():
    return CliRunner()


class TestCLI:
    def test_main_help(self, runner):
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "Hermes Agent Self-Evolution" in result.output
        assert "evolve" in result.output
        assert "versions" in result.output
        assert "rollback" in result.output
        assert "benchmark" in result.output
        assert "supervisor" in result.output

    def test_evolve_help(self, runner):
        result = runner.invoke(cli, ["evolve", "--help"])
        assert result.exit_code == 0
        assert "--skill" in result.output
        assert "--iterations" in result.output

    def test_versions_help(self, runner):
        result = runner.invoke(cli, ["versions", "--help"])
        assert result.exit_code == 0
        assert "SKILL_NAME" in result.output

    def test_rollback_help(self, runner):
        result = runner.invoke(cli, ["rollback", "--help"])
        assert result.exit_code == 0
        assert "--to" in result.output

    def test_benchmark_help(self, runner):
        result = runner.invoke(cli, ["benchmark", "--help"])
        assert result.exit_code == 0
        assert "--skill-file" in result.output
        assert "--dataset" in result.output

    def test_supervisor_help(self, runner):
        result = runner.invoke(cli, ["supervisor", "--help"])
        assert result.exit_code == 0
        assert "--auto-rollback" in result.output
        assert "--min-improvement" in result.output
