"""arXiv API client: query building, paging, rate limiting, retries and Atom parsing.

API reference: https://info.arxiv.org/help/api/user-manual.html
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import feedparser
import requests

from radar import __version__
from radar.models import Paper, split_arxiv_id

log = logging.getLogger(__name__)

API_URL = "https://export.arxiv.org/api/query"
USER_AGENT = f"arxiv-radar/{__version__}"
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class ArxivAPIError(RuntimeError):
    """The API returned an error, or a page could not be fetched after all retries."""


class _RetryableError(Exception):
    def __init__(
        self, message: str, *, rate_limited: bool = False, retry_after: float | None = None
    ):
        super().__init__(message)
        self.rate_limited = rate_limited
        self.retry_after = retry_after


def _retry_after_seconds(value: str | None) -> float | None:
    """Parse a numeric Retry-After header; HTTP-date values are ignored."""
    try:
        return max(0.0, float(value)) if value else None
    except ValueError:
        return None


@dataclass(frozen=True)
class ParsedPage:
    papers: list[Paper]
    total_results: int
    skipped: int  # entries that could not be parsed

    @property
    def entry_count(self) -> int:
        return len(self.papers) + self.skipped


@dataclass(frozen=True)
class FetchResult:
    papers: list[Paper]
    skipped: int
    pages: int


def build_query(categories: Sequence[str], start: datetime, end: datetime) -> str:
    """Search query for papers in any of `categories` first submitted in [start, end].

    The API also accepts `lastUpdatedDate`, but in practice it filters on the v1
    submission date just like `submittedDate` (verified: identical result sets), so
    revisions of older papers cannot be found by date. New papers are what the radar
    ranks; a revision is still picked up when it falls inside a fetched window.
    """
    if not categories:
        raise ValueError("at least one category is required")
    cats = " OR ".join(f"cat:{c}" for c in categories)
    fmt = "%Y%m%d%H%M"
    s, e = start.astimezone(UTC).strftime(fmt), end.astimezone(UTC).strftime(fmt)
    return f"({cats}) AND submittedDate:[{s} TO {e}]"


def _clean(text: str) -> str:
    return " ".join(text.split())


def _parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _parse_entry(entry: Any) -> Paper:
    pid, version = split_arxiv_id(entry["id"])
    title = _clean(entry["title"])
    abstract = _clean(entry["summary"])
    if not title or not abstract:
        raise ValueError("empty title or abstract")
    authors = tuple(_clean(a["name"]) for a in entry.get("authors", []) if a.get("name"))
    categories = tuple(dict.fromkeys(t["term"] for t in entry.get("tags", []) if t.get("term")))
    primary = (entry.get("arxiv_primary_category") or {}).get("term") or (
        categories[0] if categories else ""
    )
    if not primary:
        raise ValueError("no category")
    categories = (primary, *(c for c in categories if c != primary))
    return Paper(
        id=pid,
        version=version,
        title=title,
        abstract=abstract,
        authors=authors,
        categories=categories,
        primary_category=primary,
        published=_parse_dt(entry["published"]),
        updated=_parse_dt(entry["updated"]),
    )


def parse_feed(text: str) -> ParsedPage:
    """Parse one Atom page from the arXiv API. Malformed entries are skipped and counted."""
    feed = feedparser.parse(text)
    if feed.bozo and not feed.entries and "opensearch_totalresults" not in feed.feed:
        raise _RetryableError(f"unparseable response: {feed.get('bozo_exception')!r}")

    for entry in feed.entries:
        if "/api/errors" in entry.get("id", ""):
            raise ArxivAPIError(f"arXiv API error: {_clean(entry.get('summary', 'unknown'))}")

    total = int(feed.feed.get("opensearch_totalresults", len(feed.entries)))
    papers: list[Paper] = []
    skipped = 0
    for entry in feed.entries:
        try:
            papers.append(_parse_entry(entry))
        except (KeyError, ValueError, TypeError, AttributeError) as e:
            skipped += 1
            log.warning("skipping malformed entry %s: %s", entry.get("id", "<no id>"), e)
    return ParsedPage(papers=papers, total_results=total, skipped=skipped)


class ArxivClient:
    """Fetches papers politely: one request at a time, at least `delay_seconds` apart."""

    def __init__(
        self,
        *,
        delay_seconds: float = 3.0,
        page_size: int = 200,
        max_retries: int = 5,
        backoff_seconds: float = 5.0,
        rate_limit_backoff_seconds: float = 60.0,
        max_backoff_seconds: float = 600.0,
        timeout_seconds: float = 60.0,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.delay_seconds = delay_seconds
        self.page_size = page_size
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self.rate_limit_backoff_seconds = rate_limit_backoff_seconds
        self.max_backoff_seconds = max_backoff_seconds
        self.timeout_seconds = timeout_seconds
        self.session = session or requests.Session()
        # requests sets a generic "python-requests/x" agent; identify the client instead.
        if self.session.headers.get("User-Agent", "").startswith("python-requests"):
            self.session.headers["User-Agent"] = USER_AGENT
        self._sleep = sleep
        self._monotonic = monotonic
        self._last_request: float | None = None

    def _wait_for_slot(self) -> None:
        if self._last_request is not None:
            wait = self.delay_seconds - (self._monotonic() - self._last_request)
            if wait > 0:
                self._sleep(wait)
        self._last_request = self._monotonic()

    def _get(self, query: str, start: int) -> str:
        self._wait_for_slot()
        params = {
            "search_query": query,
            "start": start,
            "max_results": self.page_size,
            "sortBy": "submittedDate",
            "sortOrder": "ascending",
        }
        try:
            resp = self.session.get(API_URL, params=params, timeout=self.timeout_seconds)
        except (requests.ConnectionError, requests.Timeout) as e:
            raise _RetryableError(f"network error: {e}") from e
        if resp.status_code in _RETRYABLE_STATUS:
            raise _RetryableError(
                f"HTTP {resp.status_code}",
                rate_limited=resp.status_code == 429,
                retry_after=_retry_after_seconds(resp.headers.get("Retry-After")),
            )
        if resp.status_code != 200:
            raise ArxivAPIError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        return resp.text

    def _backoff(self, attempt: int, error: _RetryableError) -> float:
        """Exponential backoff; rate limits start much higher and Retry-After is honored."""
        base = self.rate_limit_backoff_seconds if error.rate_limited else self.backoff_seconds
        wait = max(base * 2 ** (attempt - 1), error.retry_after or 0.0)
        return min(wait, self.max_backoff_seconds)

    def fetch_page(self, query: str, start: int) -> ParsedPage:
        """Fetch one page, retrying transient failures with exponential backoff.

        An empty page before `total_results` is reached is treated as transient: the arXiv
        API occasionally returns one mid-result, and accepting it would silently drop papers.
        HTTP 429 ("Rate exceeded") gets a longer backoff: arXiv's front end throttles in
        bursts that can last a few minutes.
        """
        last_error: _RetryableError | None = None
        for attempt in range(self.max_retries + 1):
            if attempt:
                assert last_error is not None
                backoff = self._backoff(attempt, last_error)
                log.warning(
                    "retry %d/%d at start=%d in %.0fs: %s",
                    attempt,
                    self.max_retries,
                    start,
                    backoff,
                    last_error,
                )
                self._sleep(backoff)
            try:
                page = parse_feed(self._get(query, start))
                if page.entry_count == 0 and start < page.total_results:
                    raise _RetryableError(
                        f"empty page at start={start} of {page.total_results} results"
                    )
                return page
            except _RetryableError as e:
                last_error = e
        raise ArxivAPIError(
            f"page at start={start} failed after {self.max_retries + 1} attempts: {last_error}"
        )

    def fetch_window(
        self, categories: Sequence[str], start: datetime, end: datetime
    ) -> FetchResult:
        """Fetch every paper in `categories` first submitted between `start` and `end`."""
        query = build_query(categories, start, end)
        papers: list[Paper] = []
        skipped = pages = offset = 0
        while True:
            page = self.fetch_page(query, offset)
            pages += 1
            papers.extend(page.papers)
            skipped += page.skipped
            offset += page.entry_count
            log.info("page %d: %d/%d entries", pages, offset, page.total_results)
            if page.entry_count == 0 or offset >= page.total_results:
                break
        return FetchResult(papers=papers, skipped=skipped, pages=pages)
