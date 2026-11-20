"""Core data types and arXiv identifier handling."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

# New-style IDs (2304.07193) and old-style IDs (hep-th/9901001, math.GT/0309136).
_ID_PATTERN = r"\d{4}\.\d{4,5}|[a-z\-]+(?:\.[A-Z]{2})?/\d{7}"

ARXIV_ID_RE = re.compile(rf"^(?:{_ID_PATTERN})$")
_VERSIONED_ID_RE = re.compile(rf"^(?P<id>{_ID_PATTERN})(?:v(?P<version>\d+))?$")
_URL_PREFIX_RE = re.compile(r"^https?://(?:export\.)?arxiv\.org/abs/")


def split_arxiv_id(raw: str) -> tuple[str, int]:
    """Split an arXiv identifier into (id without version, version).

    Accepts bare IDs (``2304.07193v2``), abs URLs (``http://arxiv.org/abs/2304.07193v2``)
    and the ``arXiv:`` prefix. A missing version means version 1.
    """
    s = _URL_PREFIX_RE.sub("", raw.strip()).removeprefix("arXiv:")
    m = _VERSIONED_ID_RE.match(s)
    if not m:
        raise ValueError(f"not an arXiv identifier: {raw!r}")
    return m["id"], int(m["version"] or 1)


@dataclass(frozen=True, slots=True)
class Paper:
    """One arXiv paper at a specific version, as returned by the API."""

    id: str  # without version, e.g. "2304.07193"
    version: int
    title: str
    abstract: str
    authors: tuple[str, ...]
    categories: tuple[str, ...]  # primary category first
    primary_category: str
    published: datetime  # v1 submission time (UTC)
    updated: datetime  # this version's submission time (UTC)

    @property
    def abs_url(self) -> str:
        return f"https://arxiv.org/abs/{self.id}"
