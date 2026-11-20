from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from radar.models import Paper

FIXTURES = Path(__file__).parent / "fixtures"


def make_paper(
    pid: str = "2611.00001",
    version: int = 1,
    published: datetime = datetime(2026, 11, 10, 12, tzinfo=UTC),
    updated: datetime | None = None,
    title: str | None = None,
) -> Paper:
    return Paper(
        id=pid,
        version=version,
        title=title or f"Paper {pid} v{version}",
        abstract=f"Abstract of {pid}.",
        authors=("A. Author",),
        categories=("cs.CV", "cs.LG"),
        primary_category="cs.CV",
        published=published,
        updated=updated or published,
    )


def entry_xml(pid: str, version: int = 1, when: str = "2026-11-12T09:00:00Z") -> str:
    return f"""
  <entry>
    <id>http://arxiv.org/abs/{pid}v{version}</id>
    <updated>{when}</updated>
    <published>{when}</published>
    <title>Paper {pid}</title>
    <summary>Abstract {pid}.</summary>
    <author><name>A. Author</name></author>
    <arxiv:primary_category term="cs.CV" scheme="http://arxiv.org/schemas/atom"/>
    <category term="cs.CV" scheme="http://arxiv.org/schemas/atom"/>
  </entry>"""


def feed_xml(entries: list[str], total: int, start: int = 0) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <id>http://arxiv.org/api/test</id>
  <title>test</title>
  <updated>2026-11-16T00:00:00Z</updated>
  <opensearch:totalResults>{total}</opensearch:totalResults>
  <opensearch:startIndex>{start}</opensearch:startIndex>
  <opensearch:itemsPerPage>{len(entries)}</opensearch:itemsPerPage>
  {"".join(entries)}
</feed>"""


@pytest.fixture
def fixture_text():
    def _read(name: str) -> str:
        return (FIXTURES / name).read_text(encoding="utf-8")

    return _read
