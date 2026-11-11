# arXiv Paper Radar — Implementation Plan

Companion to [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md). Each phase ends in something that runs. Work top to bottom; do not start a phase until the previous one's exit check passes.

## Things only you can do

- **Before Phase 2:** extend the seed papers in `config.yaml` to 8–15 arXiv IDs across your interests, and the keywords to 10–20.
- **Phase 3:** the labeling session, about 2–3 hours in sittings of ~100 papers.
- **Phase 6:** make the repo public (Settings → General → Danger Zone → Change visibility), then sign in to Streamlit Community Cloud with GitHub and deploy the dashboard.

## Phase 0 — Setup ✅ (2–3 h)

Repo, `uv`, Python 3.12, `ruff`, `pytest`, pre-commit, CI, `config.yaml` with a validated schema, `radar` CLI with stub commands.

## Phase 1 — Ingestion (8–12 h)

1. `arxiv_client.py`: query by category and date window, paging, 3 s delay, retry with backoff, treat an empty page mid-result as a retryable error. Parse to a typed `Paper` (id without version, version, title, abstract, authors, categories, published, updated).
2. Tests against saved Atom fixtures: paging, version suffix, cross-lists, malformed entry, empty page.
3. `store.py`: Parquet files partitioned by month, DuckDB views over them, upsert by arXiv ID, `first_seen` date kept on version updates, watermark read/write.
4. `radar ingest`: watermark → fetch → upsert → advance watermark only on success. Run twice in a row and confirm the second run changes nothing. Long gaps are fetched in week-sized chunks.
5. `weekly.yml`: cron `17 4 * * 1` (Mondays 04:17 UTC) plus `workflow_dispatch`; check out the `data` branch into a worktree, run ingest, commit and push; concurrency group. A failure fails the workflow so GitHub emails you.

**Exit check:** two consecutive Monday runs commit to `data` with no manual help. (Trigger the first one manually to test; then let the schedule take over.)

## Phase 2 — Ranking v0 and dashboard v0 (8–12 h)

1. `embed.py`: one `Embedder` interface (`name`, `encode(texts)`), first implementation MiniLM or a small general model; input is `title [SEP] abstract`. Embedding cache keyed by (model, arXiv ID), float16, persisted as a release asset.
2. Fetch seed papers by ID, embed, cache.
3. `rank.py`: max-similarity and centroid scoring against the seeds; write scores and the nearest seed per paper to the store.
4. Add embed + score to `weekly.yml`; cache model weights with `actions/cache`.
5. Dashboard data layer: read Parquet from a local checkout of the `data` branch (later: a shallow clone at app start when hosted), cached with `st.cache_data`.
6. **This week** page: ranked cards for the latest week, abstract on expand, nearest seed as the reason, arXiv link.
7. **Archive** page: week, category and score filters, text search.

**Exit check:** `uv run streamlit run dashboard/app.py` shows last week's papers, and the top of the list looks sensible to you.

## Phase 3 — Evaluation (12–16 h)

1. `eval/backfill.py`: load 8–10 past weeks for your categories from the arXiv metadata snapshot (or the API), into a separate eval store.
2. Add remaining rankers: BM25 on keywords, second general embedder, SPECTER2 via `adapters`, RRF fusion.
3. Build the pool (each ranker's top 20 per week + 15 random per week), shuffled, source hidden.
4. **Label** page (local only): one paper at a time, keys 0/1/2, progress bar, resumable; writes `eval/labels.csv`.
5. Label the pool.
6. `eval/benchmark.py`: per-week nDCG@10, P@10, recall@50; mean and bootstrap 95% interval across weeks; tuning weeks vs. the last 3 test weeks; log to local MLflow; write `results.json`.
7. Pick the production embedder and scoring rule from the tuning weeks, then run the test weeks once. Switch the weekly pipeline to the winner.
8. **Model & metrics** page v0: results table with intervals.

**Exit check:** results table with intervals on the dashboard and in the README; the production ranker is justified by it. *Minimum credible portfolio piece reached.*

## Phase 4 — Learning from labels (7–10 h)

1. Re-ranker features: max and mean similarity to seeds, max similarity to papers labeled relevant and to those labeled not relevant, BM25 score, primary category. Logistic regression with class weighting.
2. Walk-forward learning curve on the labels; add it to the Metrics page.
3. `reranker.py`: train, evaluate on the most recent held-out weeks, gate (beats current model and similarity baseline beyond noise), write the model and `registry.json` (metrics, training size, label hash, promoted/rejected).
4. `radar retrain` in `weekly.yml`: skip with a recorded reason if the label hash matches the production model.
5. Scoring uses the production re-ranker if one exists; otherwise similarity-only.
6. Tests: a deliberately bad model is rejected; an empty or corrupt registry falls back to similarity.
7. Metrics page: model version history.

**Exit check:** the re-ranker's held-out result is in the results table (above similarity, or honestly not); the gate demonstrably rejects a bad model.

## Phase 5 — ML engineering (8–12 h)

1. `api.py`: `/rank` and `/health`; request/response models; tests with FastAPI's test client.
2. `Dockerfile` (multi-stage, CPU-only torch, model weights baked in); build in CI.
3. `monitor.py`: papers per week vs. trailing mean, PSI on scores vs. trailing 4 weeks, job duration; thresholds in config; results written to the store; hard failures exit non-zero. Add to `weekly.yml`.
4. **Health** page: last run, papers per week, score distribution over time, drift warnings, production model.

**Exit check:** `docker run` serves `/rank` locally; a forced zero-paper run fails the job and shows red on Health.

## Phase 6 — Go public and polish (5–8 h)

1. Check the repo for anything you would not want public (there should be nothing: no secrets are used).
2. Make the repo public; deploy the dashboard on Streamlit Community Cloud with the Label page disabled.
3. README: problem, architecture diagram, results table, learning curve, dashboard link and screenshots, quickstart.
4. Demo GIF: This week → expand a paper → Metrics → Health.
5. Final CV bullet with real numbers and the dashboard link.

**Exit check:** someone who has never seen the project opens the README and dashboard and can explain what it does and how well it works in five minutes.

## Optional

- BERTopic weekly clusters over cached embeddings, as a Trends page.

## Suggested order of sessions

| Week | Work |
|---|---|
| 1 | Phase 1: client, store, tests |
| 2 | Phase 1: weekly workflow; first manual run. Start Phase 2 while the schedule proves itself |
| 3 | Phase 2 |
| 4–5 | Phase 3 (labeling in the middle) |
| 6 | Phase 4 |
| 7–8 | Phase 5 |
| 9 | Phase 6 |

Starting the weekly schedule early matters: by Phase 6 there are two months of automated runs to show on the Health page.
