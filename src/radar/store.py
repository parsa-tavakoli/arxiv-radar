"""File-based storage on the `data` branch.

Layout under the data directory:

    papers/<ISO year>-W<week>.parquet   one file per week of first publication (v1 date)
    state/watermark.json                time of the last successful ingest
    state/runs.jsonl                    one line per successful pipeline run

Partitioning by publication week means a paper always lives in the same file, new papers
land in the newest files, and old files are rewritten only when an old paper gets a new
version. That keeps each weekly git commit small.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from radar.models import Paper

_TS = pa.timestamp("us", tz="UTC")
PAPER_SCHEMA = pa.schema(
    [
        ("id", pa.string()),
        ("version", pa.int32()),
        ("title", pa.string()),
        ("abstract", pa.string()),
        ("authors", pa.list_(pa.string())),
        ("categories", pa.list_(pa.string())),
        ("primary_category", pa.string()),
        ("published", _TS),
        ("updated", _TS),
        ("first_seen", _TS),  # when the radar first stored this paper
        ("last_changed", _TS),  # when the stored record last changed (new version)
    ]
)


@dataclass
class UpsertResult:
    new: int = 0
    updated: int = 0
    unchanged: int = 0

    def __iadd__(self, other: UpsertResult) -> UpsertResult:
        self.new += other.new
        self.updated += other.updated
        self.unchanged += other.unchanged
        return self


def partition_key(published: datetime) -> str:
    year, week, _ = published.astimezone(UTC).isocalendar()
    return f"{year}-W{week:02d}"


def _paper_row(p: Paper, first_seen: datetime, now: datetime) -> dict[str, Any]:
    return {
        "id": p.id,
        "version": p.version,
        "title": p.title,
        "abstract": p.abstract,
        "authors": list(p.authors),
        "categories": list(p.categories),
        "primary_category": p.primary_category,
        "published": p.published,
        "updated": p.updated,
        "first_seen": first_seen,
        "last_changed": now,
    }


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


class Store:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.papers_dir = self.root / "papers"
        self.state_dir = self.root / "state"
        self.watermark_path = self.state_dir / "watermark.json"
        self.runs_path = self.state_dir / "runs.jsonl"

    # ---- papers -------------------------------------------------------------------------

    def _partition_path(self, key: str) -> Path:
        return self.papers_dir / f"{key}.parquet"

    def read_partition(self, key: str) -> dict[str, dict[str, Any]]:
        path = self._partition_path(key)
        if not path.exists():
            return {}
        return {row["id"]: row for row in pq.read_table(path).to_pylist()}

    def _write_partition(self, key: str, rows: dict[str, dict[str, Any]]) -> None:
        self.papers_dir.mkdir(parents=True, exist_ok=True)
        table = pa.Table.from_pylist([rows[k] for k in sorted(rows)], schema=PAPER_SCHEMA)
        path = self._partition_path(key)
        tmp = path.with_suffix(".parquet.tmp")
        pq.write_table(table, tmp, compression="zstd")
        os.replace(tmp, path)

    def upsert(self, papers: Iterable[Paper], now: datetime) -> UpsertResult:
        """Insert new papers and replace stored ones that have a newer version.

        `first_seen` is kept from the original record, so a paper that gets a v2 is never
        treated as new again. Partitions with no changes are not rewritten, so re-running
        an ingest leaves the files byte-for-byte identical.
        """
        # Deduplicate the batch, keeping the newest version of each paper.
        latest: dict[str, Paper] = {}
        for p in papers:
            cur = latest.get(p.id)
            if cur is None or (p.version, p.updated) > (cur.version, cur.updated):
                latest[p.id] = p

        by_partition: dict[str, list[Paper]] = {}
        for p in latest.values():
            by_partition.setdefault(partition_key(p.published), []).append(p)

        result = UpsertResult()
        for key, batch in sorted(by_partition.items()):
            rows = self.read_partition(key)
            changed = False
            for p in batch:
                stored = rows.get(p.id)
                if stored is None:
                    rows[p.id] = _paper_row(p, first_seen=now, now=now)
                    result.new += 1
                    changed = True
                elif (p.version, p.updated) > (stored["version"], stored["updated"]):
                    rows[p.id] = _paper_row(p, first_seen=stored["first_seen"], now=now)
                    result.updated += 1
                    changed = True
                else:
                    result.unchanged += 1
            if changed:
                self._write_partition(key, rows)
        return result

    def connect(self) -> duckdb.DuckDBPyConnection:
        """In-memory DuckDB connection with a `papers` view over all partitions."""
        con = duckdb.connect()
        con.execute("SET TimeZone = 'UTC'")  # same results on any machine
        if any(self.papers_dir.glob("*.parquet")):
            pattern = (self.papers_dir / "*.parquet").as_posix().replace("'", "''")
            con.execute(f"CREATE VIEW papers AS SELECT * FROM read_parquet('{pattern}')")
        else:
            con.register("_empty_papers", PAPER_SCHEMA.empty_table())
            con.execute("CREATE VIEW papers AS SELECT * FROM _empty_papers")
        return con

    # ---- state --------------------------------------------------------------------------

    def read_watermark(self) -> datetime | None:
        if not self.watermark_path.exists():
            return None
        data = json.loads(self.watermark_path.read_text(encoding="utf-8"))
        return datetime.fromisoformat(data["last_success"]).astimezone(UTC)

    def write_watermark(self, when: datetime) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        payload = {"last_success": when.astimezone(UTC).isoformat(timespec="seconds")}
        _atomic_write_bytes(self.watermark_path, (json.dumps(payload) + "\n").encode())

    def append_run(self, record: dict[str, Any]) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        with self.runs_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str, sort_keys=True) + "\n")

    def read_runs(self) -> list[dict[str, Any]]:
        if not self.runs_path.exists():
            return []
        lines = self.runs_path.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines if line.strip()]
