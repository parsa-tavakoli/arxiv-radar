"""Command-line entry point: `radar <command>`."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

import typer
from pydantic import ValidationError

from radar.config import DEFAULT_CONFIG_PATH, Config, load_config

app = typer.Typer(help="arXiv Paper Radar pipeline commands.", no_args_is_help=True)

ConfigOption = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="Path to config.yaml.")
DataDirOption = typer.Option(
    Path("data"), "--data-dir", "-d", help="Checkout of the `data` branch."
)


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _load(config: Path) -> Config:
    try:
        return load_config(config)
    except (OSError, ValidationError) as e:
        typer.secho(f"Invalid config: {e}", fg="red", err=True)
        raise typer.Exit(code=1) from e


def _utc(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=UTC) if dt is not None and dt.tzinfo is None else dt


def _not_implemented(name: str, phase: int) -> None:
    typer.secho(f"`radar {name}` is not implemented yet (Phase {phase}).", fg="yellow", err=True)
    raise typer.Exit(code=1)


@app.command("check-config")
def check_config(config: Path = ConfigOption) -> None:
    """Validate config.yaml and print a summary."""
    cfg = _load(config)
    typer.echo(
        f"OK: {len(cfg.categories)} categories, {len(cfg.seed_papers)} seed papers, "
        f"{len(cfg.keywords)} keywords"
    )


@app.command()
def ingest(
    config: Path = ConfigOption,
    data_dir: Path = DataDirOption,
    since: datetime | None = typer.Option(
        None, formats=["%Y-%m-%d"], help="Fetch from this UTC date instead of the watermark."
    ),
    until: datetime | None = typer.Option(
        None, formats=["%Y-%m-%d"], help="Fetch up to this UTC date instead of now."
    ),
    summary_file: Path | None = typer.Option(
        None, help="Write a one-line summary here (used as the data commit message)."
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Fetch new and updated papers from arXiv since the last successful run."""
    from radar.arxiv_client import ArxivAPIError, ArxivClient
    from radar.ingest import run_ingest
    from radar.store import Store

    _setup_logging(verbose)
    cfg = _load(config)
    ic = cfg.ingest
    client = ArxivClient(
        delay_seconds=ic.request_delay_seconds,
        page_size=ic.page_size,
        max_retries=ic.max_retries,
        backoff_seconds=ic.retry_backoff_seconds,
        rate_limit_backoff_seconds=ic.rate_limit_backoff_seconds,
        max_backoff_seconds=ic.max_backoff_seconds,
    )
    try:
        report = run_ingest(cfg, Store(data_dir), client, since=_utc(since), until=_utc(until))
    except (ArxivAPIError, ValueError) as e:
        typer.secho(f"Ingest failed: {e}", fg="red", err=True)
        raise typer.Exit(code=1) from e

    summary = report.summary()
    if summary_file is not None:
        summary_file.write_text(summary + "\n", encoding="utf-8")
    typer.echo(summary)


@app.command()
def stats(data_dir: Path = DataDirOption, weeks: int = typer.Option(8, min=1)) -> None:
    """Show what is stored: totals, papers per publication week, last run."""
    from radar.store import Store

    store = Store(data_dir)
    con = store.connect()
    total, latest = con.execute("SELECT count(*), max(first_seen) FROM papers").fetchone()
    watermark = store.read_watermark()
    typer.echo(f"Papers stored: {total}")
    typer.echo(f"Watermark:     {watermark.isoformat() if watermark else 'none'}")
    typer.echo(f"Last stored:   {latest or 'never'}")
    rows = con.execute(
        """
        SELECT strftime(published, '%G-W%V') AS week, count(*) AS n
        FROM papers GROUP BY week ORDER BY week DESC LIMIT ?
        """,
        [weeks],
    ).fetchall()
    if rows:
        typer.echo("\nPapers by publication week:")
        for week, n in rows:
            typer.echo(f"  {week}  {n:>6}")
    runs = store.read_runs()
    if runs:
        last = runs[-1]
        typer.echo(
            f"\nLast run: {last['run_at']}  {last['new']} new, {last['updated']} updated, "
            f"{last['pages']} pages, {last['duration_seconds']}s"
        )


@app.command()
def score(config: Path = ConfigOption) -> None:
    """Embed new papers and score them against the interest profile."""
    _not_implemented("score", 2)


@app.command()
def retrain(config: Path = ConfigOption) -> None:
    """Retrain the re-ranker if labels changed; promote only if it passes the gate."""
    _not_implemented("retrain", 4)


@app.command()
def monitor(config: Path = ConfigOption) -> None:
    """Check ingestion counts and score drift."""
    _not_implemented("monitor", 5)


if __name__ == "__main__":
    app()
