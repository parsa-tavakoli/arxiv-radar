from datetime import UTC, datetime, timedelta

import pytest
from conftest import make_paper

from radar.arxiv_client import ArxivAPIError, FetchResult
from radar.config import Config
from radar.ingest import plan_windows, run_ingest
from radar.store import Store

NOW = datetime(2026, 11, 16, 4, 17, tzinfo=UTC)


def cfg(**ingest) -> Config:
    return Config.model_validate(
        {"categories": ["cs.CV"], "seed_papers": [{"id": "2304.07193"}], "ingest": ingest}
    )


class FakeFetcher:
    """Returns the given papers whose `updated` time falls inside each requested window."""

    def __init__(self, papers=(), fail_on_call: int | None = None):
        self.papers = list(papers)
        self.fail_on_call = fail_on_call
        self.windows: list[tuple[datetime, datetime]] = []

    def fetch_window(self, categories, start, end):
        self.windows.append((start, end))
        if self.fail_on_call is not None and len(self.windows) == self.fail_on_call:
            raise ArxivAPIError("arXiv is down")
        hits = [p for p in self.papers if start <= p.updated <= end]
        return FetchResult(papers=hits, skipped=0, pages=1)


def snapshot(store: Store) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(store.papers_dir.glob("*.parquet"))}


def test_plan_windows_chunks_long_ranges():
    start = datetime(2026, 11, 1, tzinfo=UTC)
    windows = plan_windows(start, start + timedelta(days=17), timedelta(days=7))
    assert [(e - s).days for s, e in windows] == [7, 7, 3]
    assert windows[0][0] == start and windows[-1][1] == start + timedelta(days=17)
    assert all(a[1] == b[0] for a, b in zip(windows, windows[1:], strict=False))


def test_plan_windows_rejects_empty_range():
    with pytest.raises(ValueError):
        plan_windows(NOW, NOW, timedelta(days=7))


def test_first_run_uses_lookback_and_sets_watermark(tmp_path):
    store = Store(tmp_path)
    fetcher = FakeFetcher([make_paper("2611.00001", published=NOW - timedelta(days=2))])

    report = run_ingest(cfg(initial_lookback_days=7), store, fetcher, now=NOW)

    assert fetcher.windows == [(NOW - timedelta(days=7), NOW)]
    assert report.new == 1
    assert store.read_watermark() == NOW
    assert report.summary() == "Ingest 2026-W47: 1 new, 0 updated (1 fetched, 0 skipped)"


def test_next_run_starts_overlap_days_before_watermark(tmp_path):
    store = Store(tmp_path)
    store.write_watermark(NOW)
    fetcher = FakeFetcher()
    later = NOW + timedelta(days=7)

    run_ingest(cfg(overlap_days=7, chunk_days=7), store, fetcher, now=later)

    assert fetcher.windows[0][0] == NOW - timedelta(days=7)
    assert fetcher.windows[-1][1] == later
    assert len(fetcher.windows) == 2
    assert store.read_watermark() == later


def test_late_announced_paper_is_caught_by_overlap(tmp_path):
    """Submitted before last week's run, but only announced (visible) after it."""
    store = Store(tmp_path)
    store.write_watermark(NOW)
    late = make_paper("2611.00042", published=NOW - timedelta(days=2))
    fetcher = FakeFetcher([late])

    report = run_ingest(cfg(overlap_days=7), store, fetcher, now=NOW + timedelta(days=7))

    assert report.new == 1


def test_rerun_is_idempotent(tmp_path):
    store = Store(tmp_path)
    papers = [
        make_paper("2611.00001", published=NOW - timedelta(days=1)),
        make_paper("2611.00002", published=NOW - timedelta(days=3)),
    ]
    run_ingest(cfg(), store, FakeFetcher(papers), now=NOW)
    before = snapshot(store)

    report = run_ingest(cfg(), store, FakeFetcher(papers), now=NOW + timedelta(hours=1))

    assert (report.new, report.updated, report.unchanged) == (0, 0, 2)
    assert snapshot(store) == before


def test_failure_leaves_watermark_unchanged(tmp_path):
    store = Store(tmp_path)
    store.write_watermark(NOW - timedelta(days=20))
    fetcher = FakeFetcher(fail_on_call=2)

    with pytest.raises(ArxivAPIError):
        run_ingest(cfg(overlap_days=0, chunk_days=7), store, fetcher, now=NOW)

    assert store.read_watermark() == NOW - timedelta(days=20)
    assert store.read_runs() == []


def test_since_overrides_watermark_and_backfill_does_not_move_it_back(tmp_path):
    store = Store(tmp_path)
    store.write_watermark(NOW)
    fetcher = FakeFetcher()
    since = datetime(2026, 9, 1, tzinfo=UTC)
    until = datetime(2026, 9, 15, tzinfo=UTC)

    run_ingest(cfg(), store, fetcher, now=NOW, since=since, until=until)

    assert fetcher.windows[0][0] == since and fetcher.windows[-1][1] == until
    assert store.read_watermark() == NOW


def test_run_is_logged(tmp_path):
    store = Store(tmp_path)
    run_ingest(cfg(), store, FakeFetcher([make_paper("2611.00001")]), now=NOW)
    runs = store.read_runs()
    assert len(runs) == 1
    assert runs[0]["step"] == "ingest"
    assert runs[0]["fetched"] == 1
    assert runs[0]["new"] == 1
