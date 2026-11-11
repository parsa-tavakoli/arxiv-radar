# arXiv Paper Radar — Project Overview (v3)

Nov 11, 2026 · Parsa Tavakoli · revised from the v1 overview; changes are listed at the end.

## Summary

arXiv Paper Radar is a recommender that ingests every new arXiv paper in my fields each week, ranks them against a research-interest profile, and shows the results on a public dashboard.

Thousands of new ML papers appear on arXiv every week. Keyword alerts miss relevant work and flood you with noise. The radar uses scientific-text embeddings and a re-ranker trained on my own relevance labels, and proves with a benchmark that it beats a keyword baseline.

It is a portfolio project, built as a small production system rather than a notebook: an automated weekly pipeline, a benchmarked ranking model, gated retraining with a model registry, a served API, monitoring and a live dashboard anyone can open.

## Goals and non-goals

**Goals**

- Collect new papers from chosen arXiv categories every week, reliably and politely (rate-limited, idempotent, version-aware), with no manual runs.
- Rank papers by relevance to an interest profile, and prove the ranking works with a labeled benchmark that reports confidence intervals.
- Learn from labels: a re-ranker that measurably improves as labels are added, retrained automatically behind an evaluation gate.
- Show it: a public read-only dashboard and a README that let a recruiter understand the system and its results in five minutes.
- Engineering quality: tests, CI, Docker, typed config, monitoring.

**Non-goals**

- Daily personal use. The system runs on its own; nobody has to read or rate it each week.
- Downloading or parsing full PDFs (titles and abstracts only).
- A multi-user product with accounts.
- Training a large model from scratch.
- Paid infrastructure. Everything runs on free tiers.

## System architecture

```
          weekly — Mondays 04:17 UTC (GitHub Actions)
arXiv API ─► ingest ─► store ─► embed ─► score ─► retrain if labels changed ─► gate ─► registry
                         │                  ▲                                            │
                         │                  └──────────── production model ◄─────────────┘
                         ▼
        Public dashboard (Streamlit, read-only)          Local only: Label page ─► labels.csv ─► git push
        This week · Archive · Model & metrics · Health
```

- **Schedule:** one workflow, every Monday at 04:17 UTC (05:17 / 06:17 in Rome). arXiv's last announcement of the week goes out Sunday 20:00 US Eastern, so a Monday-morning run always collects the full previous week. A "Run workflow" button allows manual runs.
- **Ingest:** queries the arXiv API for papers updated since the last successful run (a stored watermark), parses the Atom feed and upserts by arXiv ID. Re-running is harmless; a failed week is caught up on the next run. A new version updates the stored record but is never ranked twice. Cross-listed papers are stored once.
- **State:** lives on a `data` branch so the ephemeral CI runner has something to come back to. Papers, scores and the model registry are Parquet/JSON files queried with DuckDB. Embeddings are a cache, kept as a release asset and recomputable if lost.
- **Interest profile:** `config.yaml` lists seed papers by arXiv ID (e.g. DINOv2, SAM, Concept Bottleneck Models) plus keywords. Seed embeddings are cached per model, never stored in the YAML.
- **Score:** each new abstract is embedded and scored against the profile. Because the interests span several distinct topics, the score is the maximum (or top-k mean) similarity to the seeds, not similarity to one blurred centroid. The production re-ranker, if one has passed the gate, adjusts the final order.
- **Labels:** I label papers in the dashboard's Label page, run locally, and commit `eval/labels.csv`. Labels feed both the benchmark and the re-ranker. Adding labels later is optional; the system works without it.
- **Retrain:** the weekly job hashes the labels file. If it changed since the production model was trained, it retrains, evaluates on the most recent held-out weeks, and promotes only if the new model beats both the current one and the similarity baseline. If nothing changed, it skips and records why.
- **Monitor:** papers ingested and score distribution compared with the trailing four weeks; results stored and shown on the Health page. Zero papers or a crash fails the workflow, and GitHub emails me.
- **Dashboard:** a Streamlit app reading the `data` branch. Hosted publicly and read-only:
  - *This week:* the week's papers in ranked order, with title, authors, abstract on expand, the nearest seed paper as the reason, and a link.
  - *Archive:* every stored paper, filterable by week, category and score; text search.
  - *Model & metrics:* benchmark table with intervals, learning curve, model versions with promoted and rejected runs.
  - *Health:* last run, papers per week, score distribution over time, drift warnings.
  - *Label:* only enabled when run locally.
- **Topic clusters (optional, last):** weekly BERTopic over the cached embeddings, as a Trends page.

## Tech stack

| Layer | Tools | Why |
|---|---|---|
| Ingestion | arXiv API, `requests`, `feedparser`; arXiv metadata snapshot for backfill | Official API for weekly runs; bulk snapshot for the historical weeks the benchmark needs |
| Storage | DuckDB over Parquet on a `data` branch; embeddings cache as a release asset | No server, survives ephemeral runners, history is inspectable |
| Embeddings | MiniLM, a current general model (e.g. BGE or GTE small), SPECTER2 | General vs. science-specific. SPECTER2 loads through the `adapters` library, not plain `sentence-transformers` |
| Baselines | `rank_bm25`; BM25 + dense fusion (RRF) | Keyword baseline the embeddings must beat, plus a cheap hybrid |
| Re-ranker | scikit-learn logistic regression on a few score features | A few hundred labels cannot support 768 raw dimensions |
| Dashboard | Streamlit, Plotly; hosted on Streamlit Community Cloud | Python only, free public hosting, a live link for the CV |
| Serving | FastAPI, Docker | `/rank` and `/health` as a standalone API |
| Tracking | MLflow (local file store) for benchmarks; JSON model registry on the data branch | No tracking server exists in CI, so the registry must be a file |
| Automation | GitHub Actions (weekly cron + CI), `uv` | Free scheduling, unlimited minutes once the repo is public |
| Quality | `pytest`, `ruff`, pre-commit | Tests and linting in CI |

## Evaluation plan

The benchmark is the centrepiece: every model choice is backed by a number with an interval. The profile is a single query, so one ranked list gives one noisy number; the benchmark therefore replays history as many weekly lists.

1. **Backfill:** 8–10 past weeks of papers from my categories.
2. **Pooled labeling:** for each week, label the union of every ranker's top 20 plus a random sample of 15 papers, in the Label page. Grades: 0 skip, 1 skim, 2 must-read. Expect 300–400 labels, about 2–3 hours. Papers are shuffled and their source hidden. The random sample estimates the base rate and catches what every ranker missed.
3. **Temporal split:** earlier weeks for choosing models and settings; the last 3 weeks untouched until final reporting.
4. **Rankers compared:** BM25 on keywords; MiniLM; a current general embedder; SPECTER2; centroid vs. max-similarity profile scoring; BM25 + dense fusion; best of these + re-ranker.
5. **Metrics:** nDCG@10 and precision@10 per week, averaged across weeks with bootstrap 95% intervals; recall@50 as a sanity check. If two rankers' intervals overlap, the README says so.
6. **Learning curve:** walk forward through the weeks, training the re-ranker only on labels from earlier weeks, and plot nDCG@10 against number of labels seen. This is the evidence that the system learns.
7. **Reporting:** one results table and one learning curve, on the dashboard and in the README; all runs logged in MLflow.

Open question: a second labeler would check label consistency. Low priority, since the profile is my own taste.

## ML engineering layer

- **Serving:** FastAPI with `/rank` (score a list of abstracts) and `/health`, packaged in Docker with the model baked in.
- **Model registry:** each trained re-ranker is saved as `reranker-<date>.joblib` with its metrics, training-set size and label hash in `registry.json`; a `production` pointer names the one in use. Rollback is editing one line. The dashboard shows the registry.
- **Gated retraining:** retrain only when labels change; promote only if the new model beats the current one and the similarity baseline on the most recent held-out weeks by more than noise. Rejected runs are recorded and shown.
- **Fallback:** if the registry is empty or unreadable, ranking is similarity-only.
- **Monitoring:** papers per week vs. trailing mean, population stability index on scores, job duration. Hard failures fail the job.
- **CI:** tests and lint on every push. The weekly job uses a concurrency group so two runs never write state at once; its commit to the `data` branch keeps GitHub from disabling the schedule for inactivity.
- **Public by design:** the repo goes public before the dashboard is deployed. Nothing in the data is sensitive (paper IDs, scores, labels), and no secrets are needed for the read-only dashboard.

## Repo structure

```
arxiv-radar/
├── src/radar/
│   ├── config.py         # typed config loading and validation
│   ├── arxiv_client.py   # API client, rate limiting, retries, Atom parsing
│   ├── store.py          # DuckDB/Parquet reads and writes, watermark
│   ├── embed.py          # embedding models behind one interface, cache
│   ├── rank.py           # BM25, similarity, fusion, re-ranker features
│   ├── reranker.py       # train, evaluate, registry, promotion gate
│   ├── monitor.py        # ingestion and score-drift checks
│   ├── cluster.py        # optional BERTopic trends
│   ├── api.py            # FastAPI service
│   └── cli.py            # `radar ingest | score | retrain | monitor | check-config`
├── dashboard/
│   ├── app.py            # Streamlit entry point
│   └── pages/            # this_week, archive, metrics, health, label (local only)
├── eval/
│   ├── backfill.py       # load historical weeks
│   ├── labels.csv        # graded labels
│   └── benchmark.py      # compares rankers, logs to MLflow, writes results
├── tests/
├── .github/workflows/
│   ├── weekly.yml        # ingest + embed + score + retrain + monitor
│   └── ci.yml            # tests + lint
├── config.yaml           # categories, seed paper IDs, keywords
├── Dockerfile
├── pyproject.toml
└── README.md             # diagram, results, dashboard link, demo GIF
```

## Milestones and time estimate

About 50–70 hours; at 5–8 hours a week alongside the thesis, roughly 8–11 weeks.

| Phase | Scope | Est. hours | Done when |
|---|---|---|---|
| 0. Setup | Repo, `uv`, lint, tests, CI, config schema | 2–3 | ✅ CI green |
| 1. Ingestion | API client, store, watermark, idempotent upserts, weekly Action | 8–12 | Two consecutive Monday runs land papers on the `data` branch with no manual help |
| 2. Ranking + dashboard v0 | Embedding cache, max-similarity scoring, This week and Archive pages (local) | 8–12 | The local dashboard shows last week's papers ranked sensibly |
| 3. Evaluation | Backfill, Label page, pooled labels, benchmark, Metrics page | 12–16 | Results table with intervals; production ranker chosen from it |
| 4. Learning from labels | Re-ranker, learning curve, gated retraining, model registry | 7–10 | Re-ranker evaluated on held-out weeks; a forced bad model is rejected |
| 5. ML engineering | FastAPI, Docker, monitoring, Health page | 8–12 | `docker run` serves `/rank`; a forced failure fails the job and shows on Health |
| 6. Go public + polish | Make repo public, deploy dashboard, README, diagram, demo GIF, CV bullet | 5–8 | A recruiter opens the dashboard link and understands the project in five minutes |
| Optional | BERTopic Trends page | 3–5 | Trends page shows the week's clusters |

Phases 0–3 alone make a credible portfolio piece (pipeline + benchmark). Stop there if the thesis gets busy.

## Risks

| Risk | Mitigation |
|---|---|
| arXiv API returns empty or partial pages | Delay between requests, retries with backoff, watermark only advances on success |
| State lost or corrupted on a CI runner | Data on a versioned branch; embeddings recomputable; concurrency group on writers |
| Weekly run fails and nobody notices | Job fails loudly and GitHub emails me; next run catches up automatically |
| Embedding a full week is slow on CI | Cache model weights; small models; minutes are unlimited once public |
| Benchmark too small to separate models | Many weekly lists, bootstrap intervals, report ties honestly |
| Re-ranker does not beat similarity | Report it honestly; similarity stays in production; the gate is the story |
| Hosted dashboard sleeps or the free tier changes | Wakes on visit; also runs locally with one command; README has screenshots |
| Scope creep eats thesis time | Phases 0–3 are the minimum; the rest is incremental |

## Stretch goals

- One-line paper summaries from a small LLM, shown on each card.
- Citation counts from the Semantic Scholar API to boost papers gaining traction.
- A second profile seeded with EEG papers, with a profile switcher on the dashboard.

## CV value

Shows end-to-end ML engineering: data pipelines, embeddings and ranking, honest evaluation, gated retraining, serving, monitoring and a live product surface. It complements my research-style vision projects.

Draft CV bullet: *Built an automated arXiv recommender (scientific-text embeddings + label-trained re-ranker) with a weekly GitHub Actions pipeline, gated retraining and a public Streamlit dashboard; improved nDCG@10 from X to Y over a BM25 baseline across N weekly test sets.*

## Changes from v1

1. **Portfolio-first.** The project is built to be shown, not used daily; anything that only mattered for daily personal use is gone.
2. **Weekly instead of daily.** One Monday-morning workflow replaces daily and weekly jobs; monitoring no longer needs weekend logic.
3. **Public dashboard replaces email/Telegram.** Read-only and hosted, with a link for the CV. No accounts, passwords or tokens.
4. **Repo goes public** before the dashboard is deployed.
5. **State persistence defined.** v1 wrote to DuckDB from GitHub Actions, where the disk is wiped after every run.
6. **Learning from labels instead of live ratings.** The re-ranker trains on benchmark labels; the learning curve is the proof. Retraining runs only when labels change.
7. **Evaluation redesigned.** 150–200 binary labels with a held-out split would leave a handful of relevant papers in the test set. Now: many weekly lists, pooled graded labels, temporal split, intervals.
8. **Promotion gate tightened.** Must beat the current model and the baseline on recent held-out weeks, not merely "not drop" on a fixed set.
9. **Profile scoring.** Max-similarity over seeds instead of a single centroid; embeddings moved out of `config.yaml`.
10. **Model notes.** MiniLM truncates at 256 tokens, shorter than many abstracts; a current general embedder added to the comparison; SPECTER2 needs the `adapters` library.
11. **MLflow scoped** to local benchmarks; CI and the dashboard use a file registry.
12. **BERTopic moved to optional.**
13. **Estimate:** 50–70 hours.
