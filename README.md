# arXiv Paper Radar

A personal recommender that ingests new arXiv papers in my fields every day, ranks them against my research interests with scientific-text embeddings and a feedback-trained re-ranker, and shows the ones worth reading on a dashboard.

See [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md) for the design and [PLAN.md](PLAN.md) for the build plan.

## Roadmap

**Current phase: 1 — Ingestion.** Phase 0 is complete.

| Phase | Overview | Status |
|---|---|---|
| 0. Setup | Repo, `uv`, lint, tests, CI, config schema | ✅ Done |
| 1. Ingestion | arXiv API client, store, watermark, idempotent upserts, daily GitHub Action | 🔄 In progress |
| 2. Ranking + dashboard v0 | Embedding cache, max-similarity scoring, This week and Archive pages, deployed | ⏳ Planned |
| 3. Evaluation | Backfill, Label page, pooled labels, benchmark, Metrics page | ⏳ Planned |
| 4. Feedback loop | Rating buttons, GitHub writer, compaction, exploration papers, re-ranker, gated retraining | ⏳ Planned |
| 5. ML engineering | FastAPI, Docker, model registry, monitoring, Health page | ⏳ Planned |
| 6. Polish | README, architecture diagram, screenshots, demo GIF | ⏳ Planned |
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

## Configuration

Edit [config.yaml](config.yaml): arXiv categories, seed papers (by arXiv ID) that define the interest profile, and keywords. `uv run radar check-config` validates it.
