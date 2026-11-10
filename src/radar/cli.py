"""Command-line entry point: `radar <command>`."""

from __future__ import annotations

from pathlib import Path

import typer
from pydantic import ValidationError

from radar.config import DEFAULT_CONFIG_PATH, load_config

app = typer.Typer(help="arXiv Paper Radar pipeline commands.", no_args_is_help=True)

ConfigOption = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="Path to config.yaml.")


def _not_implemented(name: str, phase: int) -> None:
    typer.secho(f"`radar {name}` is not implemented yet (Phase {phase}).", fg="yellow", err=True)
    raise typer.Exit(code=1)


@app.command("check-config")
def check_config(config: Path = ConfigOption) -> None:
    """Validate config.yaml and print a summary."""
    try:
        cfg = load_config(config)
    except (OSError, ValidationError) as e:
        typer.secho(f"Invalid config: {e}", fg="red", err=True)
        raise typer.Exit(code=1) from e
    typer.echo(
        f"OK: {len(cfg.categories)} categories, {len(cfg.seed_papers)} seed papers, "
        f"{len(cfg.keywords)} keywords"
    )


@app.command()
def ingest(config: Path = ConfigOption) -> None:
    """Fetch new papers from arXiv since the last successful run."""
    _not_implemented("ingest", 1)


@app.command()
def score(config: Path = ConfigOption) -> None:
    """Embed new papers and score them against the interest profile."""
    _not_implemented("score", 2)


@app.command()
def compact(config: Path = ConfigOption) -> None:
    """Merge rating files written by the dashboard into ratings.parquet."""
    _not_implemented("compact", 4)


@app.command()
def retrain(config: Path = ConfigOption) -> None:
    """Retrain the re-ranker and promote it only if it passes the gate."""
    _not_implemented("retrain", 4)


@app.command()
def monitor(config: Path = ConfigOption) -> None:
    """Check ingestion counts and score drift."""
    _not_implemented("monitor", 5)


if __name__ == "__main__":
    app()
