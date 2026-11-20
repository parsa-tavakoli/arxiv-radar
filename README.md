# arXiv Paper Radar

A recommender that ingests new arXiv papers in my fields every week, ranks them against a research-interest profile with scientific-text embeddings and a label-trained re-ranker, and shows the results on a public dashboard.

## Roadmap

**Current phase: 1 — Ingestion.** Phase 0 is complete.

| Phase | Overview | Status |
|---|---|---|
| 0. Setup | Repo, `uv`, lint, tests, CI, config schema | ✅ Done |
| 1. Ingestion | arXiv API client, store, watermark, idempotent upserts, weekly GitHub Action (Mondays) | 🔄 In progress |
| 2. Ranking + dashboard v0 | Embedding cache, max-similarity scoring, This week and Archive pages | ⏳ Planned |
| 3. Evaluation | Backfill, Label page, pooled labels, benchmark, Metrics page | ⏳ Planned |
| 4. Learning from labels | Re-ranker, learning curve, gated retraining, model registry | ⏳ Planned |
| 5. ML engineering | FastAPI, Docker, monitoring, Health page | ⏳ Planned |
| 6. Go public + polish | Public repo, deployed dashboard, README, architecture diagram, demo GIF | ⏳ Planned |
| Optional | BERTopic Trends page | ⏳ Planned |

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

## Ingesting papers

A GitHub Actions workflow ([weekly.yml](.github/workflows/weekly.yml)) runs every Monday at 04:17 UTC, fetches the past week's papers from the arXiv API and commits them to the `data` branch as weekly Parquet files. To run it locally:

```bash
uv run radar ingest --data-dir data      # fetch since the last successful run
uv run radar stats --data-dir data       # what is stored
```

`--since YYYY-MM-DD` / `--until YYYY-MM-DD` fetch a specific range. Runs are idempotent: repeating one changes nothing.

## Configuration

Edit [config.yaml](config.yaml): arXiv categories, seed papers (by arXiv ID) that define the interest profile, and keywords. `uv run radar check-config` validates it.
