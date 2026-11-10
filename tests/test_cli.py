from pathlib import Path

from typer.testing import CliRunner

from radar.cli import app

runner = CliRunner()
REPO_CONFIG = Path(__file__).resolve().parents[1] / "config.yaml"


def test_help_lists_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for cmd in ["check-config", "ingest", "score", "compact", "retrain", "monitor"]:
        assert cmd in result.output


def test_check_config_ok():
    result = runner.invoke(app, ["check-config", "--config", str(REPO_CONFIG)])
    assert result.exit_code == 0
    assert result.output.startswith("OK:")


def test_check_config_invalid(tmp_path):
    bad = tmp_path / "config.yaml"
    bad.write_text("categories: []\nseed_papers: []\n")
    result = runner.invoke(app, ["check-config", "--config", str(bad)])
    assert result.exit_code == 1


def test_stub_commands_exit_nonzero():
    result = runner.invoke(app, ["ingest", "--config", str(REPO_CONFIG)])
    assert result.exit_code == 1
