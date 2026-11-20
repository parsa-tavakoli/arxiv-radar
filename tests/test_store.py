from datetime import UTC, datetime, timedelta

from conftest import make_paper

from radar.store import Store, partition_key

NOW = datetime(2026, 11, 16, 4, 17, tzinfo=UTC)
LATER = NOW + timedelta(days=7)


def snapshot(store: Store) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(store.papers_dir.glob("*.parquet"))}


def test_partition_key_uses_iso_week():
    assert partition_key(datetime(2026, 11, 10, tzinfo=UTC)) == "2026-W46"
    # 1 Jan 2027 is a Friday, so it belongs to ISO week 53 of 2026.
    assert partition_key(datetime(2027, 1, 1, tzinfo=UTC)) == "2026-W53"


def test_insert_new_papers(tmp_path):
    store = Store(tmp_path)
    result = store.upsert([make_paper("2611.00001"), make_paper("2611.00002")], now=NOW)

    assert (result.new, result.updated, result.unchanged) == (2, 0, 0)
    rows = store.read_partition("2026-W46")
    assert set(rows) == {"2611.00001", "2611.00002"}
    assert rows["2611.00001"]["first_seen"] == NOW
    assert rows["2611.00001"]["authors"] == ["A. Author"]


def test_reupsert_is_idempotent_and_leaves_files_untouched(tmp_path):
    store = Store(tmp_path)
    papers = [make_paper("2611.00001"), make_paper("2611.00002")]
    store.upsert(papers, now=NOW)
    before = snapshot(store)

    result = store.upsert(papers, now=LATER)

    assert (result.new, result.updated, result.unchanged) == (0, 0, 2)
    assert snapshot(store) == before


def test_new_version_replaces_and_keeps_first_seen(tmp_path):
    store = Store(tmp_path)
    store.upsert([make_paper("2611.00001", version=1)], now=NOW)

    v2 = make_paper("2611.00001", version=2, updated=datetime(2026, 11, 20, tzinfo=UTC))
    result = store.upsert([v2], now=LATER)

    assert result.updated == 1
    row = store.read_partition("2026-W46")["2611.00001"]
    assert row["version"] == 2
    assert row["title"] == "Paper 2611.00001 v2"
    assert row["first_seen"] == NOW
    assert row["last_changed"] == LATER


def test_older_version_does_not_overwrite(tmp_path):
    store = Store(tmp_path)
    v2 = make_paper("2611.00001", version=2, updated=datetime(2026, 11, 20, tzinfo=UTC))
    store.upsert([v2], now=NOW)

    result = store.upsert([make_paper("2611.00001", version=1)], now=LATER)

    assert result.unchanged == 1
    assert store.read_partition("2026-W46")["2611.00001"]["version"] == 2


def test_batch_duplicates_keep_newest_version(tmp_path):
    store = Store(tmp_path)
    v1 = make_paper("2611.00001", version=1)
    v3 = make_paper("2611.00001", version=3, updated=datetime(2026, 11, 21, tzinfo=UTC))
    result = store.upsert([v3, v1, v1], now=NOW)

    assert result.new == 1
    assert store.read_partition("2026-W46")["2611.00001"]["version"] == 3


def test_papers_are_split_by_publication_week(tmp_path):
    store = Store(tmp_path)
    store.upsert(
        [
            make_paper("2611.00001", published=datetime(2026, 11, 10, tzinfo=UTC)),
            make_paper("2611.00002", published=datetime(2026, 11, 17, tzinfo=UTC)),
        ],
        now=NOW,
    )
    assert sorted(snapshot(store)) == ["2026-W46.parquet", "2026-W47.parquet"]


def test_update_rewrites_only_the_affected_partition(tmp_path):
    store = Store(tmp_path)
    old = make_paper("2611.00001", published=datetime(2026, 11, 10, tzinfo=UTC))
    new = make_paper("2611.00002", published=datetime(2026, 11, 17, tzinfo=UTC))
    store.upsert([old, new], now=NOW)
    before = snapshot(store)

    store.upsert([make_paper("2611.00003", published=datetime(2026, 11, 18, tzinfo=UTC))], LATER)

    after = snapshot(store)
    assert after["2026-W46.parquet"] == before["2026-W46.parquet"]
    assert after["2026-W47.parquet"] != before["2026-W47.parquet"]


def test_duckdb_view(tmp_path):
    store = Store(tmp_path)
    assert store.connect().execute("SELECT count(*) FROM papers").fetchone() == (0,)

    store.upsert(
        [
            make_paper("2611.00001", published=datetime(2026, 11, 10, tzinfo=UTC)),
            make_paper("2611.00002", published=datetime(2026, 11, 17, tzinfo=UTC)),
        ],
        now=NOW,
    )
    con = store.connect()
    assert con.execute("SELECT count(*) FROM papers").fetchone() == (2,)
    assert con.execute("SELECT max(version) FROM papers").fetchone() == (1,)


def test_watermark_roundtrip(tmp_path):
    store = Store(tmp_path)
    assert store.read_watermark() is None
    store.write_watermark(NOW)
    assert store.read_watermark() == NOW


def test_run_log_appends(tmp_path):
    store = Store(tmp_path)
    store.append_run({"step": "ingest", "run_at": NOW, "new": 3})
    store.append_run({"step": "ingest", "run_at": LATER, "new": 5})
    runs = store.read_runs()
    assert [r["new"] for r in runs] == [3, 5]
    assert runs[0]["run_at"].startswith("2026-11-16")
