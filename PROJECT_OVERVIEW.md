# arXiv Paper Radar — Project Overview (v2)

Nov 11, 2026 · Parsa Tavakoli · revised from the v1 overview; changes are listed at the end.

## Summary

arXiv Paper Radar is a personal recommender that ingests every new arXiv paper in my fields each day, ranks them against my research interests, and shows the ones worth reading on a personal dashboard.

Thousands of new ML papers appear on arXiv every week. Keyword alerts miss relevant work and flood you with noise. The radar uses scientific-text embeddings and a re-ranker trained on my own ratings, so it improves the more I use it.

It is built as a small production system, not a notebook: daily automated ingestion, a benchmarked ranking model, a dashboard and a served API, model versioning and monitoring.

## Goals and non-goals

**Goals**

- Collect new papers from chosen arXiv categories every day, reliably and politely (rate-limited, idempotent, version-aware).
- Rank papers by relevance to a personal interest profile, and prove the ranking works with a labeled benchmark that reports confidence intervals.
- Learn from feedback: a re-ranker that improves as I rate papers, with rating taking one click on the dashboard.
- Run unattended: scheduled pipeline, gated retraining, pipeline health visible on the dashboard, failing jobs alerting by email.
- Be a portfolio piece for ML engineer roles: clean repo, tests, Docker, a live dashboard and a README with results.

**Non-goals**

- Downloading or parsing full PDFs (titles and abstracts only).
- A multi-user product with accounts. The dashboard has one user: me.
- Training a large model from scratch.
- Always-on paid infrastructure. Everything runs on free scheduled compute and free hosting.

## System architecture

```
                    daily (GitHub Actions)                         weekly (GitHub Actions)
arXiv API ─► ingest ─► store ─► embed ─► score ─► monitor          retrain ─► gate ─► model registry
                         │  ▲                                          ▲                   │
                         │  │ ratings (commit via GitHub API)          │ ratings           │ production model
                         ▼  │                                          │                   ▼
                    ┌──────────── Dashboard (Streamlit) ────────────┐                    score
                    │ This week · Archive & search · Label          │
                    │ Model & metrics · Pipeline health             │
                    └───────────────────────────────────────────────┘
                                         ▲ me: read, 👍 / 👎
```

- **Ingest (daily):** queries the arXiv API for papers updated since the last successful run (a stored watermark, not "today"), parses the Atom feed and upserts by arXiv ID. Re-running a day is harmless. A new version updates the stored record but is never recommended twice. Cross-listed papers are stored once.
- **State:** lives outside the code branch so the ephemeral CI runner has something to come back to. Papers, scores and ratings are Parquet files on a `data` branch, queried with DuckDB. Embeddings are a cache, not data: a rolling 90-day file kept as a release asset, recomputable if lost.
- **Interest profile:** `config.yaml` lists seed papers by arXiv ID (e.g. DINOv2, SAM, Concept Bottleneck Models) plus keywords. Their embeddings are computed and cached per model, never stored in the YAML.
- **Score (daily):** each new abstract is embedded and scored against the profile. Because my interests are several distinct topics, the score is the maximum (or top-k mean) similarity to the seeds, not similarity to one blurred centroid. Once a re-ranker has passed the gate, it adjusts the final order.
- **Dashboard:** a Streamlit app that reads the `data` branch. Its pages:
  - *This week:* papers first seen in the last 7 days, ranked, with title, authors, abstract on expand, the nearest seed paper as the reason, a link, and 👍/👎 buttons. 2–3 exploration papers from lower ranks are mixed in, unmarked.
  - *Archive & search:* every stored paper, filterable by date, category and score; full-text search; my rating history.
  - *Label:* blind labeling mode for the benchmark (0 skip, 1 skim, 2 must-read), so labeling and rating use one tool.
  - *Model & metrics:* benchmark results table, learning curve, weekly 👍 rate of the top 10 vs. the exploration papers, model versions and which one is in production.
  - *Pipeline health:* last successful run of each job, papers ingested per day, score distribution over time, drift warnings.
- **Feedback:** each click writes one small JSON file (`ratings/<timestamp>_<arxiv_id>.json`) to the `data` branch through the GitHub API. One file per rating means the dashboard and the daily job never conflict; the daily job compacts them into Parquet. Exploration papers give ratings that are not biased toward what the current model already likes.
- **Retrain (weekly):** refits the re-ranker on all labels and ratings, evaluates it on the most recent held-out weeks, and promotes it only if it beats both the current model and the similarity-only baseline.
- **Monitor (daily):** ingestion counts and score distribution compared with the trailing four weeks. Results go to the dashboard's health page; a hard failure (zero papers on a weekday, job error) fails the workflow, and GitHub emails me. Checks know that arXiv publishes nothing on weekends and holidays.
- **Topic clusters (optional, last):** weekly BERTopic over the cached embeddings, shown as a Trends page.

## Tech stack

| Layer | Tools | Why |
|---|---|---|
| Ingestion | arXiv API, `requests`, `feedparser`; arXiv metadata snapshot for backfill | Official API for daily runs; bulk snapshot for the historical weeks the benchmark needs |
| Storage | DuckDB over Parquet on a `data` branch; embeddings cache as a release asset | No server, survives ephemeral runners, history is inspectable |
| Embeddings | MiniLM, a current general model (e.g. BGE or GTE small), SPECTER2 | General vs. science-specific. SPECTER2 loads through the `adapters` library, not plain `sentence-transformers` |
| Baselines | `rank_bm25`; BM25 + dense fusion (RRF) | Keyword baseline the embeddings must beat, plus a cheap hybrid |
| Re-ranker | scikit-learn logistic regression on a few score features | Tens of ratings cannot support 768 raw dimensions |
| Dashboard | Streamlit, Plotly; `PyGithub` to commit ratings; hosted on Streamlit Community Cloud, also runs locally | Python only, fast to build, free hosting that wakes on visit |
| Serving | FastAPI, Docker | `/rank` and `/feedback` as a standalone API; the dashboard's "score any abstract" box can call it |
| Tracking | MLflow with a local file store for benchmarks; a JSON model registry in the data branch for CI and the dashboard | No tracking server exists in CI, so the registry must be a file |
| Automation | GitHub Actions (cron), `uv` | Free scheduling and CI, fast reproducible installs |
| Quality | `pytest`, `ruff`, pre-commit | Tests and linting in CI |

## Evaluation plan

The profile is a single query, so one ranked list gives one noisy number. The benchmark therefore replays history as many weekly lists.

1. **Backfill:** 8–10 past weeks of papers from my categories.
2. **Pooled labeling:** for each week, label the union of every ranker's top 20 plus a random sample of 15 papers, in the dashboard's Label page. Grades: 0 skip, 1 skim, 2 must-read. Expect 300–400 labels, about 2–3 hours. Papers are shuffled and their source hidden. The random sample estimates the base rate and catches what every ranker missed.
3. **Temporal split:** earlier weeks for choosing models and settings, the last 3 weeks untouched until final reporting.
4. **Rankers compared:** BM25 on keywords; MiniLM; a current general embedder; SPECTER2; centroid vs. max-similarity profile scoring; BM25 + dense fusion; best of these + feedback re-ranker.
5. **Metrics:** nDCG@10 and precision@10 per week, averaged across weeks with bootstrap 95% intervals; recall@50 as a sanity check. If two rankers' intervals overlap, the README says so.
6. **Feedback simulation:** walk forward through the weeks, training the re-ranker only on labels from earlier weeks, and plot nDCG@10 against number of labels seen.
7. **Online metric:** once live, the weekly 👍 rate of the top 10 is the number that matters, charted on the dashboard with the exploration papers' 👍 rate as the reference line.
8. **Reporting:** one results table, one learning curve, one online chart, shown on the dashboard and in the README.

Open question: a second labeler would check label consistency, but the target is my own taste, so this is low priority.

## ML engineering layer

- **Serving:** FastAPI with `/rank` (score a list of abstracts), `/feedback` (record a rating) and `/health`, packaged in Docker with the model baked in.
- **Model registry:** each retrained re-ranker is saved as `reranker-<date>.joblib` with its metrics, training-set size and data hash in `registry.json`; a `production` pointer names the one in use. Rollback is editing one line. The dashboard shows the registry.
- **Gated retraining:** promotion requires beating the current model and the similarity baseline on the most recent held-out weeks by more than noise. Otherwise the old model stays and the dashboard shows the rejected run.
- **Fallback:** below about 50 ratings, or if the registry is empty or unreadable, ranking is similarity-only.
- **Monitoring:** ingest count vs. the same weekday's trailing mean; population stability index on scores; job duration. Written to the store, plotted on the health page; hard failures fail the job.
- **CI:** tests and lint on every push. Scheduled jobs fail loudly, use a concurrency group so two runs never write state at once, and the daily commit to the `data` branch keeps GitHub from disabling the schedule for inactivity.
- **Access and secrets:** the dashboard is restricted to me (private viewer list on Streamlit Community Cloud, plus a password check from Streamlit secrets as a backstop). It writes ratings with a fine-grained GitHub token limited to this repo's contents, stored in Streamlit secrets only.

## Repo structure

```
arxiv-radar/
├── src/radar/
│   ├── config.py         # typed config loading and validation
│   ├── arxiv_client.py   # API client, rate limiting, retries, Atom parsing
│   ├── store.py          # DuckDB/Parquet reads and writes, watermark, rating compaction
│   ├── embed.py          # embedding models behind one interface, cache
│   ├── rank.py           # BM25, similarity, fusion, re-ranker features
│   ├── reranker.py       # train, evaluate, registry, promotion gate
│   ├── selection.py      # weekly list: top papers + exploration papers
│   ├── monitor.py        # ingestion and score-drift checks
│   ├── cluster.py        # optional weekly BERTopic trends
│   ├── api.py            # FastAPI service
│   └── cli.py            # `radar ingest | score | retrain | monitor | compact`
├── dashboard/
│   ├── app.py            # Streamlit entry point
│   ├── pages/            # this_week, archive, label, metrics, health
│   └── github_writer.py  # commit rating/label files via the GitHub API
├── eval/
│   ├── backfill.py       # load historical weeks
│   ├── labels.csv        # graded labels (exported from the Label page)
│   └── benchmark.py      # compares rankers, logs to MLflow, writes results
├── tests/
├── .github/workflows/
│   ├── daily.yml         # ingest + embed + score + compact ratings + monitor
│   ├── weekly.yml        # retrain (+ clusters)
│   └── ci.yml            # tests + lint
├── config.yaml           # categories, seed paper IDs, keywords
├── Dockerfile
├── pyproject.toml
└── README.md             # diagram, results, dashboard screenshots, demo GIF
```

## Milestones and time estimate

About 60–85 hours; at 5–8 hours a week alongside the thesis, roughly 9–12 weeks.

| Phase | Scope | Est. hours | Done when |
|---|---|---|---|
| 0. Setup | Repo, `uv`, lint, tests, CI, config schema | 2–3 | CI is green on an empty package |
| 1. Ingestion | API client, store, watermark, idempotent upserts, daily Action | 10–14 | Papers land on the `data` branch daily for a week with no manual runs |
| 2. Ranking + dashboard v0 | Embedding cache, max-similarity scoring, This week and Archive pages, deployed | 10–14 | I open the hosted dashboard and see this week's ranked papers |
| 3. Evaluation | Backfill, Label page, pooled labels, benchmark, Metrics page | 12–16 | Results table with intervals on the dashboard and in the README |
| 4. Feedback loop | Rating buttons, GitHub writer, compaction, exploration, re-ranker, gated retrain | 10–14 | A click shows up on the `data` branch; a promoted re-ranker is ranking live |
| 5. ML engineering | FastAPI, Docker, registry, monitoring, Health page | 10–14 | `docker run` serves `/rank`; a forced bad model is rejected; a forced zero-paper day fails the job and shows on Health |
| 6. Polish | README, diagram, screenshots, demo GIF, CV bullet | 4–8 | A stranger can understand and run it in 10 minutes |
| Optional | BERTopic Trends page | 3–5 | Trends page shows this week's clusters |

Phases 0–2 alone are a usable tool. Stop there if the thesis gets busy.

## Risks

| Risk | Mitigation |
|---|---|
| arXiv API returns empty or partial pages | Delay between requests, retries with backoff, watermark only advances on success |
| State lost or corrupted on a CI runner | Data on a versioned branch; embeddings recomputable; concurrency group on writers |
| Dashboard and pipeline writing at the same time | One file per rating, never edited; only the daily job compacts |
| Hosted dashboard sleeps or the free tier changes | It also runs locally with one command against a clone of the `data` branch |
| Someone else finds the dashboard and rates papers | Private viewer list plus password; token can only touch this repo |
| Ratings biased toward what the model already shows | Exploration papers mixed into every week's list |
| Benchmark too small to separate models | Many weekly lists, bootstrap intervals, report ties honestly |
| Too few ratings for the re-ranker | Benchmark labels seed the training set; similarity fallback below the threshold |
| Scope creep eats thesis time | Phases 0–2 are the minimum; dashboard pages beyond This week are added phase by phase |

## Stretch goals

- One-line paper summaries from a small LLM, shown on each card.
- Citation counts from the Semantic Scholar API to boost papers gaining traction.
- A thesis mode seeded with EEG papers (a second profile in `config.yaml`, a profile switcher on the dashboard).
- A read-only public demo of the dashboard with ratings disabled, for the portfolio.

## CV value

Shows end-to-end ML engineering: data pipelines, embeddings and ranking, honest evaluation, a product surface, serving, gated retraining and monitoring. It complements my research-style vision projects.

Draft CV bullet: *Built an automated arXiv recommender (scientific-text embeddings + feedback-trained re-ranker) with a Streamlit dashboard and FastAPI service, retrained weekly behind an evaluation gate on GitHub Actions; improved nDCG@10 from X to Y over a BM25 baseline across N weekly test sets.*

## Changes from v1

1. **State persistence defined.** v1 wrote to DuckDB from GitHub Actions, where the disk is wiped after every run.
2. **Dashboard replaces email/Telegram.** One interface for reading, rating, labeling, metrics and pipeline health.
3. **Feedback path defined.** v1 had a `/feedback` endpoint but nothing hosting it. Now: dashboard clicks commit one rating file each to the `data` branch.
4. **Labeling moved into the dashboard** instead of a separate tool.
5. **Evaluation redesigned.** 150–200 binary labels with a held-out split would leave a handful of relevant papers in the test set, so precision@10 would be mostly noise. Now: many weekly lists, pooled graded labels, temporal split, intervals.
6. **Exploration papers added** to counter the bias of only rating what the model already ranked high.
7. **Promotion gate tightened.** "Does not drop on a fixed held-out set" goes stale and passes on noise. Now: recent held-out weeks, must beat current model and baseline.
8. **Profile scoring.** Max-similarity over seeds instead of a single centroid; embeddings moved out of `config.yaml`.
9. **Model notes.** MiniLM truncates at 256 tokens, shorter than many abstracts; a current general embedder added to the comparison; SPECTER2 needs the `adapters` library.
10. **Re-ranker features specified** so it can learn from tens of ratings.
11. **Monitoring made weekend-aware**, shown on the dashboard, with hard failures failing the job so GitHub emails me.
12. **MLflow scoped** to local benchmarks; CI and the dashboard use a file registry because no tracking server exists there.
13. **BERTopic moved to optional.** It is the piece least connected to the core loop.
14. **Estimate raised** from 50–75 to 60–85 hours for persistence, feedback and the dashboard.
