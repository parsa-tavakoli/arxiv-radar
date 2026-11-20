"""Weekly ingestion: watermark → fetch → upsert → advance watermark."""

from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from radar.arxiv_client import FetchResult
from radar.config import Config
from radar.store import Store, UpsertResult

log = logging.getLogger(__name__)


class WindowFetcher(Protocol):
    def fetch_window(
        self, categories: list[str], start: datetime, end: datetime
    ) -> FetchResult: ...


@dataclass(frozen=True)
class IngestReport:
    window_start: datetime
    window_end: datetime
    windows: int
    pages: int
    fetched: int
    skipped: int
    new: int
    updated: int
    unchanged: int
    duration_seconds: float

    def summary(self) -> str:
        week = self.window_end.strftime("%G-W%V")
        return (
            f"Ingest {week}: {self.new} new, {self.updated} updated "
            f"({self.fetched} fetched, {self.skipped} skipped)"
        )


def plan_windows(
    start: datetime, end: datetime, chunk: timedelta
) -> list[tuple[datetime, datetime]]:
    """Split [start, end] into consecutive windows of at most `chunk`."""
    if start >= end:
        raise ValueError(f"window start {start} is not before end {end}")
    windows = []
    cur = start
    while cur < end:
        nxt = min(cur + chunk, end)
        windows.append((cur, nxt))
        cur = nxt
    return windows


def resolve_start(
    store: Store, cfg: Config, now: datetime, since: datetime | None = None
) -> datetime:
    if since is not None:
        return since
    watermark = store.read_watermark()
    if watermark is None:
        return now - timedelta(days=cfg.ingest.initial_lookback_days)
    return watermark - timedelta(days=cfg.ingest.overlap_days)


def run_ingest(
    cfg: Config,
    store: Store,
    client: WindowFetcher,
    *,
    now: datetime | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> IngestReport:
    """Fetch and store everything updated since the last successful run.

    The watermark only moves forward after every window has been fetched and stored, so a
    failed run is fully retried next time. Re-fetching overlapping windows is harmless.
    """
    t0 = time.monotonic()
    now = (now or datetime.now(UTC)).astimezone(UTC)
    end = (until or now).astimezone(UTC)
    start = resolve_start(store, cfg, now, since).astimezone(UTC)
    windows = plan_windows(start, end, timedelta(days=cfg.ingest.chunk_days))
    log.info("ingesting %s → %s in %d window(s)", start, end, len(windows))

    totals = UpsertResult()
    fetched = skipped = pages = 0
    for i, (ws, we) in enumerate(windows, 1):
        log.info("window %d/%d: %s → %s", i, len(windows), ws, we)
        result = client.fetch_window(cfg.categories, ws, we)
        totals += store.upsert(result.papers, now=now)
        fetched += len(result.papers)
        skipped += result.skipped
        pages += result.pages

    previous = store.read_watermark()
    if previous is None or end > previous:
        store.write_watermark(end)

    report = IngestReport(
        window_start=start,
        window_end=end,
        windows=len(windows),
        pages=pages,
        fetched=fetched,
        skipped=skipped,
        new=totals.new,
        updated=totals.updated,
        unchanged=totals.unchanged,
        duration_seconds=round(time.monotonic() - t0, 1),
    )
    store.append_run({"step": "ingest", "run_at": now, **asdict(report)})
    log.info(report.summary())
    return report
