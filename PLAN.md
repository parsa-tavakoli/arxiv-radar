# arXiv Paper Radar — Implementation Plan

Companion to [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md). Each phase ends in something that runs. Work top to bottom; do not start a phase until the previous one's exit check passes.

## Things only you can do

- **Phase 0:** create the GitHub repo. Public is better for the portfolio; ratings and labels will be visible on the `data` branch.
- **Phase 0:** pick 8–15 seed papers (arXiv IDs) across your interests and 10–20 keywords; confirm the categories (cs.CV, cs.LG, cs.AI).
- **Phase 2:** sign in to Streamlit Community Cloud with GitHub, deploy the app, and restrict viewers to yourself.
- **Phase 4:** create a fine-grained GitHub token with Contents read/write on this repo only, and add it to the app's Streamlit secrets with a dashboard password.

## Phase 0 — Setup (2–3 h)

1. `git init`, `uv init`, Python 3.12, `src/radar` package layout, `dashboard/` folder.
2. `ruff`, `pytest`, pre-commit; `ci.yml` running lint and tests on push.
3. `config.yaml` plus `config.py` (pydantic model: categories, seed IDs, keywords, list size, exploration count, thresholds).
4. `cli.py` skeleton with empty subcommands.

**Exit check:** CI green; `uv run radar --help` lists the subcommands.

## Phase 1 — Ingestion (10–14 h)

1. `arxiv_client.py`: query by category and `lastUpdatedDate` window, paging, 3 s delay, retry with backoff, treat an empty page mid-result as a retryable error. Parse to a typed `Paper` (id without version, version, title, abstract, authors, categories, published, updated).
2. Tests against saved Atom fixtures: paging, version suffix, cross-lists, malformed entry, empty page.
3. `store.py`: Parquet files partitioned by month, DuckDB views over them, upsert by arXiv ID, `first_seen` date kept on version updates, watermark read/write.
4. `radar ingest`: watermark → fetch → upsert → advance watermark only on success. Run twice in a row and confirm the second run changes nothing.
5. `daily.yml`: check out the `data` branch into a worktree, run ingest, commit and push; concurrency group; cron after arXiv's daily announcement; manual `workflow_dispatch` trigger. A failed run fails the workflow so GitHub emails you.

**Exit check:** seven consecutive days of commits on `data` with no manual runs; weekend runs succeed with zero new papers.

## Phase 2 — Ranking v0 and dashboard v0 (10–14 h)

1. `embed.py`: one `Embedder` interface (`name`, `encode(texts)`), first implementation MiniLM or a small general model; input is `title [SEP] abstract`. Embedding cache keyed by (model, arXiv ID), float16, rolling 90 days plus all seeds, labeled and rated papers.
2. Fetch seed papers by ID, embed, cache.
3. `rank.py`: max-similarity and centroid scoring against the seeds; write daily scores and the nearest seed per paper to the store.
4. Add embed + score to `daily.yml`; cache model weights with `actions/cache`; persist the embedding cache as a release asset.
5. Dashboard data layer: read Parquet from the `data` branch (local clone when run locally, raw GitHub URLs or a shallow clone when hosted), cached with `st.cache_data` and a short TTL.
6. **This week** page: ranked cards for papers first seen in the last 7 days, abstract on expand, nearest seed as the reason, arXiv link; a "today only" toggle.
7. **Archive** page: date, category and score filters, text search.
8. Deploy to Streamlit Community Cloud from the main branch, viewers restricted to you.

**Exit check:** you open the hosted dashboard on a weekday morning and see that day's papers ranked, and the top of the list is not obviously worse than skimming the listing yourself. This is the minimum viable tool.

## Phase 3 — Evaluation (12–16 h)

1. `eval/backfill.py`: load 8–10 past weeks for your categories from the arXiv metadata snapshot (or the API), into a separate eval store.
2. Add remaining rankers: BM25 on keywords, second general embedder, SPECTER2 via `adapters`, RRF fusion.
3. Build the pool (each ranker's top 20 per week + 15 random per week), shuffled, source hidden.
4. **Label** page: one paper at a time, keyboard shortcuts for 0/1/2, progress bar, resumable. Labels saved locally to `eval/labels.csv` when run locally (labeling is a local, sit-down task; no GitHub writer needed yet).
5. Label the pool. Budget 2–3 h in sittings of about 100.
6. `eval/benchmark.py`: per-week nDCG@10, P@10, recall@50; mean and bootstrap 95% interval across weeks; tuning weeks vs. the last 3 test weeks; log to local MLflow; write `results.json` to the repo.
7. Pick the production embedder and scoring rule from the tuning weeks, then run the test weeks once. Switch the daily pipeline to the winner.
8. **Model & metrics** page v0: results table with intervals, from `results.json`.

**Exit check:** results table on the dashboard and in the README; the choice of production ranker is justified by it.

## Phase 4 — Feedback loop (10–14 h)

1. `dashboard/github_writer.py`: commit one JSON file per rating (`ratings/<timestamp>_<arxiv_id>.json`) to the `data` branch via `PyGithub`; retry on failure; show a toast on success and keep the button state optimistic.
2. 👍/👎 buttons on This week and Archive cards; your latest rating per paper wins; rated papers show their state.
3. Password gate on app start (Streamlit secrets), on top of the private viewer list.
4. `selection.py`: weekly list = top papers + 2–3 exploration papers sampled from ranks 20–100, fixed per week (seeded) so the list does not reshuffle on reload; exploration flag stored, not shown.
5. `radar compact` in `daily.yml`: merge rating files into `ratings.parquet` and delete the merged files in the same commit.
6. Re-ranker features: max and mean similarity to seeds, max similarity to liked and to disliked papers, BM25 score, primary category. Logistic regression with class weighting.
7. Walk-forward feedback simulation on the Phase 3 labels; learning curve added to the Metrics page.
8. `reranker.py`: train on labels + ratings, evaluate on the most recent held-out weeks, gate, write `registry.json`. `weekly.yml` runs it.
9. Scoring uses the production re-ranker if one exists and the rating count is above the threshold; otherwise similarity-only.

**Exit check:** a click on the hosted dashboard appears as a file on the `data` branch within seconds and in `ratings.parquet` after the next daily run; on the test weeks the re-ranker's interval sits above similarity-only (or the README says honestly that it does not yet).

## Phase 5 — ML engineering (10–14 h)

1. `api.py`: `/rank`, `/feedback`, `/health`; request/response models; tests with FastAPI's test client.
2. `Dockerfile` (multi-stage, CPU-only torch, model weights baked in); build in CI.
3. Registry hardening: data hash, training size, metrics per version; rollback command; test that a deliberately bad model is rejected.
4. `monitor.py`: ingest count vs. same-weekday trailing mean, PSI on scores vs. trailing 4 weeks, job duration; thresholds in config; results written to the store; hard failures exit non-zero.
5. **Health** page: last successful run per job, papers per day, score distribution over time, drift warnings, current production model.
6. Metrics page: weekly 👍 rate of the top 10 vs. exploration papers; model version history with promoted and rejected runs.
7. Optional: a "score any abstract" box on the dashboard that calls the ranker (in-process, or `/rank` when the API is running).

**Exit check:** `docker run` serves `/rank` locally; a forced zero-paper weekday fails the job and shows red on Health; a forced bad model is not promoted.

## Phase 6 — Polish (4–8 h)

1. README: problem, architecture diagram, results table, learning curve, online 👍-rate chart, dashboard screenshots, quickstart for running with your own profile (`uv run streamlit run dashboard/app.py`).
2. Demo GIF: open This week, expand a paper, rate it, see it on Metrics.
3. Final CV bullet with real numbers.

**Exit check:** someone else clones it, edits `config.yaml`, and sees a ranked dashboard in 10 minutes.

## Optional

- BERTopic weekly clusters over cached embeddings, as a Trends page.
- Read-only public demo of the dashboard with ratings disabled.

## Suggested order of sessions

| Week | Work |
|---|---|
| 1 | Phase 0, start Phase 1 (client + tests) |
| 2 | Finish Phase 1; let it run |
| 3–4 | Phase 2 |
| 5–6 | Phase 3 (labeling in the middle) |
| 7–8 | Phase 4 |
| 9–10 | Phase 5 |
| 11 | Phase 6 |

Starting ingestion in week 2 matters: by the time the feedback loop is built there are weeks of real data behind it.
