from datetime import UTC, datetime
from pathlib import Path

import responses
from conftest import entry_xml, feed_xml
from typer.testing import CliRunner

from radar.arxiv_client import API_URL
from radar.cli import app
from radar.store import Store

runner = CliRunner()
REPO_CONFIG = Path(__file__).resolve().parents[1] / "config.yaml"


def test_help_lists_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for cmd in ["check-config", "ingest", "stats", "score", "retrain", "monitor"]:
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
    result = runner.invoke(app, ["score", "--config", str(REPO_CONFIG)])
    assert result.exit_code == 1


@responses.activate
def test_ingest_end_to_end(tmp_path):
    """Full CLI run against a mocked arXiv API, including the summary file."""
    responses.add(
        responses.GET,
        API_URL,
        body=feed_xml([entry_xml("2611.00001", when="2026-11-12T09:00:00Z")], total=1),
    )
    data_dir = tmp_path / "data"
    summary = tmp_path / "summary.txt"

    result = runner.invoke(
        app,
        [
            "ingest",
            "--config",
            str(REPO_CONFIG),
            "--data-dir",
            str(data_dir),
            "--since",
            "2026-11-10",
            "--until",
            "2026-11-14",
            "--summary-file",
            str(summary),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "1 new" in summary.read_text()
    store = Store(data_dir)
    assert store.connect().execute("SELECT count(*) FROM papers").fetchone() == (1,)
    # A backfill with --until in the past still records a watermark on the first run.
    assert store.read_watermark() == datetime(2026, 11, 14, tzinfo=UTC)

    stats = runner.invoke(app, ["stats", "--data-dir", str(data_dir)])
    assert stats.exit_code == 0
    assert "Papers stored: 1" in stats.output


@responses.activate
def test_ingest_failure_exits_nonzero(tmp_path):
    responses.add(responses.GET, API_URL, status=400, body="bad")
    result = runner.invoke(
        app,
        [
            "ingest",
            "--config",
            str(REPO_CONFIG),
            "--data-dir",
            str(tmp_path),
            "--since",
            "2026-11-10",
        ],
    )
    assert result.exit_code == 1
    assert Store(tmp_path).read_watermark() is None
