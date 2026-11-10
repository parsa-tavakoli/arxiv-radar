"""Typed loading and validation of config.yaml."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DEFAULT_CONFIG_PATH = Path("config.yaml")

# New-style IDs (2304.07193) and old-style IDs (hep-th/9901001), without a version suffix.
ARXIV_ID_RE = re.compile(r"^(\d{4}\.\d{4,5}|[a-z\-]+(\.[A-Z]{2})?/\d{7})$")
CATEGORY_RE = re.compile(r"^[a-z\-]+(\.[A-Za-z\-]+)?$")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SeedPaper(_Strict):
    id: str
    note: str = ""

    @field_validator("id")
    @classmethod
    def _valid_id(cls, v: str) -> str:
        v = v.strip()
        if not ARXIV_ID_RE.match(v):
            raise ValueError(f"not an arXiv ID without version: {v!r}")
        return v


class RankingConfig(_Strict):
    list_size: int = Field(10, ge=1, le=100)
    exploration_count: int = Field(3, ge=0)
    exploration_rank_range: tuple[int, int] = (20, 100)
    min_ratings_for_reranker: int = Field(50, ge=0)

    @model_validator(mode="after")
    def _check_ranges(self) -> Self:
        lo, hi = self.exploration_rank_range
        if not 0 < lo < hi:
            raise ValueError("exploration_rank_range must be [low, high] with 0 < low < high")
        if lo <= self.list_size:
            raise ValueError("exploration_rank_range must start below the top list_size papers")
        if self.exploration_count > hi - lo:
            raise ValueError("exploration_count is larger than the exploration rank range")
        return self


class IngestConfig(_Strict):
    request_delay_seconds: float = Field(3.0, ge=3.0)  # arXiv asks for at least 3 s
    page_size: int = Field(200, ge=1, le=2000)
    max_retries: int = Field(5, ge=0, le=20)


class Config(_Strict):
    categories: list[str] = Field(min_length=1)
    seed_papers: list[SeedPaper] = Field(min_length=1)
    keywords: list[str] = Field(default_factory=list)
    ranking: RankingConfig = RankingConfig()
    ingest: IngestConfig = IngestConfig()

    @field_validator("categories")
    @classmethod
    def _valid_categories(cls, v: list[str]) -> list[str]:
        bad = [c for c in v if not CATEGORY_RE.match(c)]
        if bad:
            raise ValueError(f"invalid arXiv categories: {bad}")
        if len(set(v)) != len(v):
            raise ValueError("duplicate categories")
        return v

    @field_validator("seed_papers")
    @classmethod
    def _unique_seeds(cls, v: list[SeedPaper]) -> list[SeedPaper]:
        ids = [s.id for s in v]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate seed paper IDs")
        return v

    @field_validator("keywords")
    @classmethod
    def _clean_keywords(cls, v: list[str]) -> list[str]:
        cleaned = [k.strip() for k in v if k.strip()]
        if len({k.lower() for k in cleaned}) != len(cleaned):
            raise ValueError("duplicate keywords")
        return cleaned


def load_config(path: Path | str = DEFAULT_CONFIG_PATH) -> Config:
    """Read and validate a YAML config file."""
    path = Path(path)
    with path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return Config.model_validate(raw)
