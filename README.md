# arXiv Paper Radar

A personal recommender that ingests new arXiv papers in my fields every day, ranks them against my research interests with scientific-text embeddings and a feedback-trained re-ranker, and shows the ones worth reading on a dashboard.

Status: **Phase 0 — setup.** See [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md) for the design and [PLAN.md](PLAN.md) for the build plan.

## Quickstart

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run radar check-config
uv run pytest
```

Enable the git hooks once:

```bash
uv run pre-commit install
```

## Configuration

Edit [config.yaml](config.yaml): arXiv categories, seed papers (by arXiv ID) that define the interest profile, and keywords. `uv run radar check-config` validates it.
