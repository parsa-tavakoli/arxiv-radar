# arXiv Paper Radar

A recommender that ingests new arXiv papers in my fields every week, ranks them against a research-interest profile with scientific-text embeddings and a label-trained re-ranker, and shows the results on a public dashboard.

## Roadmap

**Current phase: 1 — Ingestion.** The pipeline is live and ran for the first time on 20 Nov 2026 (2,446 papers). GitHub dropped the first scheduled run on 23 Nov, so a backup Monday schedule was added; Phase 1 is complete once the scheduled runs on 30 Nov and 7 Dec succeed on their own.

| Phase | Overview | Status |
|---|---|---|
| 0. Setup | Repo, `uv`, lint, tests, CI, config schema | ✅ Done |
| 1. Ingestion | arXiv API client, store, watermark, idempotent upserts, weekly GitHub Action (Mondays) | 🟢 Live, awaiting two scheduled runs |
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

## How ingestion works

The [weekly workflow](.github/workflows/weekly.yml) runs every Monday at 04:17 UTC, after arXiv's last announcement of the week (Sunday 20:00 US Eastern), with a backup run at 10:17 UTC in case GitHub drops the first (it runs schedules best-effort). If the early run happened, the backup finds nothing new and commits nothing. Each run:

1. Reads the watermark: the time of the last successful run.
2. Queries the arXiv API for papers in the configured categories submitted since then, 200 per page, 3 seconds between requests.
3. Merges them into the store by arXiv ID. New papers are added; a newer version replaces the stored one but keeps its original `first_seen` date, so it is never treated as new twice.
4. Moves the watermark forward, only if every step succeeded.
5. Commits the changes to the `data` branch.

Design choices:

- **Idempotent.** Repeating a run changes nothing, so a failed week is safely caught up by the next run.
- **7-day overlap.** Each run re-fetches the week before the watermark, because a paper only appears in the API once announced, which can be days after its submission time (weekends, holidays).
- **Fails loudly.** API errors and empty pages mid-result are retried with exponential backoff. If retries run out, the job fails, the watermark stays put and GitHub sends an email.
- **Known limitation.** The API's `lastUpdatedDate` filter behaves exactly like `submittedDate` (verified: identical result sets), so revisions of older papers cannot be found by date. New papers, which are what the radar ranks, are all captured.

The workflow can also be started by hand from the Actions tab (**Weekly pipeline → Run workflow**), optionally with a start date.

### The `data` branch

Data lives on its own branch, separate from the code, so the stateless CI runner has somewhere to persist it:

```
papers/2026-W47.parquet   one file per ISO week of first publication
state/watermark.json      time of the last successful run
state/runs.jsonl          one line per run: window, pages, new/updated counts, duration
```

Partitioning by publication week means each weekly commit mostly touches the newest file, which keeps the git history small.

To inspect it locally:

```bash
git fetch origin data && git worktree add data origin/data
```

```bash
uv run radar stats --data-dir data
```

### Running ingestion locally

```bash
uv run radar ingest --data-dir data                                     # since the watermark
uv run radar ingest --data-dir data --since 2026-11-01 --until 2026-11-08  # a specific range
```

## Configuration

Edit [config.yaml](config.yaml): arXiv categories, seed papers (by arXiv ID) that define the interest profile, keywords, and ingestion settings (rate limit, retries, lookback and overlap). `uv run radar check-config` validates it.

## Project layout

```
src/radar/
├── config.py         typed config loading and validation
├── models.py         Paper record, arXiv ID parsing
├── arxiv_client.py   API client: paging, rate limiting, retries, Atom parsing
├── store.py          Parquet store, watermark, run log, DuckDB view
├── ingest.py         the ingestion run
└── cli.py            `radar` command
tests/                unit and end-to-end tests (no network)
.github/workflows/    ci.yml (lint + tests), weekly.yml (pipeline)
```
