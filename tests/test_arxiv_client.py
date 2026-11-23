from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

import pytest
import requests
import responses
from conftest import entry_xml, feed_xml

from radar.arxiv_client import API_URL, ArxivAPIError, ArxivClient, build_query, parse_feed

START = datetime(2026, 11, 9, 4, 17, tzinfo=UTC)
END = datetime(2026, 11, 16, 4, 17, tzinfo=UTC)


class FakeClock:
    """Deterministic replacement for time.sleep / time.monotonic."""

    def __init__(self):
        self.now = 0.0
        self.sleeps: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    def monotonic(self) -> float:
        return self.now


def make_client(clock: FakeClock, **kw) -> ArxivClient:
    kw.setdefault("page_size", 2)
    kw.setdefault("max_retries", 3)
    kw.setdefault("backoff_seconds", 5.0)
    return ArxivClient(sleep=clock.sleep, monotonic=clock.monotonic, **kw)


def start_param(request) -> int:
    return int(parse_qs(urlparse(request.url).query)["start"][0])


# ---- query + parsing --------------------------------------------------------------------


def test_build_query():
    q = build_query(["cs.CV", "cs.LG"], START, END)
    assert q == "(cat:cs.CV OR cat:cs.LG) AND submittedDate:[202611090417 TO 202611160417]"


def test_build_query_converts_to_utc():
    from datetime import timedelta, timezone

    rome = timezone(timedelta(hours=1))
    q = build_query(["cs.CV"], datetime(2026, 11, 9, 5, 17, tzinfo=rome), END)
    assert "[202611090417 TO" in q


def test_build_query_requires_categories():
    with pytest.raises(ValueError):
        build_query([], START, END)


def test_parse_sample_page(fixture_text):
    page = parse_feed(fixture_text("arxiv_page.xml"))
    assert page.total_results == 4
    assert page.skipped == 1  # entry without a published date
    assert [p.id for p in page.papers] == ["2304.07193", "2611.01234", "cs/0112017"]

    dino = page.papers[0]
    assert dino.version == 2
    assert dino.title == "DINOv2: Learning Robust Visual Features without Supervision"
    assert dino.abstract.startswith("The recent breakthroughs")
    assert "\n" not in dino.abstract
    assert dino.authors == ("Maxime Oquab", "Timothée Darcet")
    assert dino.primary_category == "cs.CV"
    assert dino.categories == ("cs.CV", "cs.LG", "cs.AI")
    assert dino.published == datetime(2023, 4, 14, 17, 58, 15, tzinfo=UTC)
    assert dino.updated == datetime(2024, 2, 2, 17, 15, 9, tzinfo=UTC)

    assert page.papers[1].categories == ("cs.LG", "stat.ML")
    assert page.papers[2].version == 1


def test_parse_error_feed_raises(fixture_text):
    with pytest.raises(ArxivAPIError, match="max_results"):
        parse_feed(fixture_text("arxiv_error.xml"))


def test_parse_empty_result():
    page = parse_feed(feed_xml([], total=0))
    assert page.papers == [] and page.total_results == 0


# ---- fetching ---------------------------------------------------------------------------


@responses.activate
def test_fetch_window_pages_through_all_results():
    ids = [f"2611.0000{i}" for i in range(5)]

    def callback(request):
        s = start_param(request)
        return 200, {}, feed_xml([entry_xml(i) for i in ids[s : s + 2]], total=5, start=s)

    responses.add_callback(responses.GET, API_URL, callback=callback)
    clock = FakeClock()
    result = make_client(clock).fetch_window(["cs.CV"], START, END)

    assert [p.id for p in result.papers] == ids
    assert result.pages == 3
    assert [start_param(c.request) for c in responses.calls] == [0, 2, 4]
    params = parse_qs(urlparse(responses.calls[0].request.url).query)
    assert params["sortBy"] == ["submittedDate"]
    assert params["sortOrder"] == ["ascending"]
    assert params["max_results"] == ["2"]


@responses.activate
def test_requests_are_rate_limited():
    def callback(request):
        s = start_param(request)
        return 200, {}, feed_xml([entry_xml(f"2611.1000{s}")], total=3, start=s)

    responses.add_callback(responses.GET, API_URL, callback=callback)
    clock = FakeClock()
    make_client(clock, page_size=1, delay_seconds=3.0).fetch_window(["cs.CV"], START, END)

    assert len(responses.calls) == 3
    assert clock.sleeps == [3.0, 3.0]  # a wait before every request after the first


@responses.activate
def test_empty_page_mid_result_is_retried():
    calls = {"n": 0}

    def callback(request):
        s = start_param(request)
        if s == 2 and calls["n"] == 0:
            calls["n"] += 1
            return 200, {}, feed_xml([], total=4, start=s)  # arXiv glitch
        ids = ["2611.00001", "2611.00002", "2611.00003", "2611.00004"]
        return 200, {}, feed_xml([entry_xml(i) for i in ids[s : s + 2]], total=4, start=s)

    responses.add_callback(responses.GET, API_URL, callback=callback)
    clock = FakeClock()
    result = make_client(clock).fetch_window(["cs.CV"], START, END)

    assert len(result.papers) == 4
    assert 5.0 in clock.sleeps  # first backoff


@responses.activate
def test_server_errors_are_retried_with_backoff():
    responses.add(responses.GET, API_URL, status=503)
    responses.add(responses.GET, API_URL, status=503)
    responses.add(responses.GET, API_URL, body=feed_xml([entry_xml("2611.00001")], total=1))
    clock = FakeClock()
    result = make_client(clock).fetch_window(["cs.CV"], START, END)

    assert len(result.papers) == 1
    backoffs = [s for s in clock.sleeps if s >= 5.0]
    assert backoffs == [5.0, 10.0]


@responses.activate
def test_network_errors_are_retried():
    responses.add(responses.GET, API_URL, body=requests.ConnectionError("boom"))
    responses.add(responses.GET, API_URL, body=feed_xml([entry_xml("2611.00001")], total=1))
    result = make_client(FakeClock()).fetch_window(["cs.CV"], START, END)
    assert len(result.papers) == 1


@responses.activate
def test_gives_up_after_max_retries():
    responses.add(responses.GET, API_URL, status=503)
    clock = FakeClock()
    with pytest.raises(ArxivAPIError, match="after 4 attempts"):
        make_client(clock, max_retries=3).fetch_window(["cs.CV"], START, END)
    assert len(responses.calls) == 4


@responses.activate
def test_client_errors_are_not_retried():
    responses.add(responses.GET, API_URL, status=400, body="bad query")
    with pytest.raises(ArxivAPIError, match="HTTP 400"):
        make_client(FakeClock()).fetch_window(["cs.CV"], START, END)
    assert len(responses.calls) == 1


@responses.activate
def test_api_error_feed_is_not_retried(fixture_text):
    responses.add(responses.GET, API_URL, body=fixture_text("arxiv_error.xml"))
    with pytest.raises(ArxivAPIError):
        make_client(FakeClock()).fetch_window(["cs.CV"], START, END)
    assert len(responses.calls) == 1


@responses.activate
def test_sends_user_agent():
    responses.add(responses.GET, API_URL, body=feed_xml([], total=0))
    make_client(FakeClock()).fetch_window(["cs.CV"], START, END)
    assert responses.calls[0].request.headers["User-Agent"].startswith("paper-radar/")


@responses.activate
def test_rate_limit_uses_longer_backoff():
    responses.add(responses.GET, API_URL, status=429, body="Rate exceeded.")
    responses.add(responses.GET, API_URL, status=429, body="Rate exceeded.")
    responses.add(responses.GET, API_URL, body=feed_xml([entry_xml("2611.00001")], total=1))
    clock = FakeClock()
    client = make_client(clock, rate_limit_backoff_seconds=60.0, max_backoff_seconds=600.0)

    result = client.fetch_window(["cs.CV"], START, END)

    assert len(result.papers) == 1
    assert [s for s in clock.sleeps if s >= 60] == [60.0, 120.0]


@responses.activate
def test_retry_after_header_is_honored_and_capped():
    responses.add(responses.GET, API_URL, status=503, headers={"Retry-After": "90"})
    responses.add(responses.GET, API_URL, status=429, headers={"Retry-After": "5000"})
    responses.add(responses.GET, API_URL, body=feed_xml([], total=0))
    clock = FakeClock()
    client = make_client(clock, backoff_seconds=5.0, max_backoff_seconds=600.0)

    client.fetch_window(["cs.CV"], START, END)

    assert [s for s in clock.sleeps if s > 3.0] == [90.0, 600.0]
