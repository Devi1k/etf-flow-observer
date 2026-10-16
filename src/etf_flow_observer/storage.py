"""SQLite 里的原始响应、观察版本和明确的缺口。

同一基金、同一数据日、同一序列、同一来源只保留一条逻辑观察。
数字变了，或者晚间参考变成早间权威，就追加版本。相同内容重复抓取不追加。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from etf_flow_observer.labels import prepare_disclosure

SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_fetches (
    id INTEGER PRIMARY KEY,
    source_name TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    method TEXT NOT NULL,
    url TEXT NOT NULL,
    request_body TEXT,
    http_status INTEGER,
    body_path TEXT,
    content_sha256 TEXT,
    fetched_at TEXT NOT NULL,
    network_fetched_at TEXT,
    cache_accessed_at TEXT,
    request_started_at TEXT,
    attempt_no INTEGER NOT NULL DEFAULT 1,
    from_cache INTEGER NOT NULL,
    error TEXT
);

CREATE TABLE IF NOT EXISTS observations (
    id INTEGER PRIMARY KEY,
    fund_code TEXT NOT NULL,
    as_of_date TEXT NOT NULL,
    series TEXT NOT NULL,
    source_name TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    revised_at TEXT,
    authoritative INTEGER NOT NULL,
    lookahead_free INTEGER NOT NULL,
    latest_version_no INTEGER NOT NULL,
    UNIQUE (fund_code, as_of_date, series, source_name)
);

CREATE TABLE IF NOT EXISTS observation_versions (
    id INTEGER PRIMARY KEY,
    observation_id INTEGER NOT NULL REFERENCES observations(id),
    version_no INTEGER NOT NULL,
    fund_code TEXT NOT NULL,
    as_of_date TEXT NOT NULL,
    series TEXT NOT NULL,
    source_name TEXT NOT NULL,
    original_value TEXT NOT NULL,
    original_unit TEXT NOT NULL,
    standardized_value TEXT,
    standardized_unit TEXT,
    source_url TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    revised_at TEXT,
    snapshot_phase TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    quality_status TEXT NOT NULL,
    quality_flags TEXT NOT NULL,
    raw_fetch_id INTEGER,
    network_fetched_at TEXT,
    cache_accessed_at TEXT,
    observation_available_at TEXT,
    note TEXT NOT NULL DEFAULT '',
    UNIQUE (observation_id, version_no)
);

CREATE TABLE IF NOT EXISTS data_gaps (
    id INTEGER PRIMARY KEY,
    fund_code TEXT NOT NULL,
    as_of_date TEXT NOT NULL,
    series TEXT NOT NULL,
    source_name TEXT NOT NULL,
    reason TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    UNIQUE (fund_code, as_of_date, series, source_name, reason)
);

CREATE TABLE IF NOT EXISTS quality_events (
    id INTEGER PRIMARY KEY,
    fund_code TEXT,
    as_of_date TEXT,
    series TEXT,
    source_name TEXT,
    status TEXT NOT NULL,
    detail TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS disclosure_records (
    id INTEGER PRIMARY KEY,
    fund_code TEXT,
    as_of_date TEXT NOT NULL,
    kind TEXT NOT NULL,
    note TEXT NOT NULL,
    created_at TEXT NOT NULL,
    CHECK (kind IN ('etf_share_change', 'official_increase_holding'))
);

CREATE TABLE IF NOT EXISTS checkpoints (
    source_name TEXT NOT NULL,
    checkpoint_key TEXT NOT NULL,
    status TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (source_name, checkpoint_key)
);

CREATE TABLE IF NOT EXISTS rate_limit (
    host TEXT PRIMARY KEY,
    last_request_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sim_ledger (
    id INTEGER PRIMARY KEY,
    version_id TEXT NOT NULL,
    instrument TEXT NOT NULL,
    entry_at TEXT NOT NULL,
    exit_at TEXT,
    size TEXT NOT NULL,
    note TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class UpsertResult:
    action: str
    observation_id: int
    version_no: int
    first_seen_at: str
    revised_at: str | None
    quality_status: str


class Store:
    def __init__(self, db_path: Path, raw_dir: Path):
        self.db_path = Path(db_path)
        self.raw_dir = Path(raw_dir)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        self._ensure_column("raw_fetches", "request_started_at", "TEXT")
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def _ensure_column(self, table: str, column: str, decl: str) -> None:
        cols = {row[1] for row in self.conn.execute(f"PRAGMA table_info({table})")}
        if column not in cols:
            self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")

    def save_raw(
        self,
        *,
        source_name: str,
        fingerprint: str,
        method: str,
        url: str,
        request_body: str | None,
        http_status: int | None,
        body: bytes | None,
        fetched_at: datetime,
        from_cache: bool,
        error: str | None,
        existing_body_path: str | None = None,
        content_sha256: str | None = None,
        network_fetched_at: datetime | None = None,
        cache_accessed_at: datetime | None = None,
        request_started_at: datetime | None = None,
        attempt_no: int = 1,
    ) -> int:
        body_path = existing_body_path
        digest = content_sha256
        if body is not None:
            digest = hashlib.sha256(body).hexdigest()
            path = self.raw_dir / "by-hash" / digest
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_bytes(body)
            body_path = str(path)
        network_stamp = (network_fetched_at or fetched_at).isoformat(timespec="seconds")
        cache_stamp = (
            cache_accessed_at.isoformat(timespec="seconds") if cache_accessed_at is not None else None
        )
        request_stamp = (
            request_started_at.isoformat(timespec="seconds")
            if request_started_at is not None
            else None
        )
        cursor = self.conn.execute(
            """
            INSERT INTO raw_fetches (
                source_name, fingerprint, method, url, request_body, http_status,
                body_path, content_sha256, fetched_at, network_fetched_at, cache_accessed_at,
                request_started_at, attempt_no, from_cache, error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_name,
                fingerprint,
                method,
                url,
                request_body,
                http_status,
                body_path,
                digest,
                network_stamp,
                network_stamp,
                cache_stamp,
                request_stamp,
                attempt_no,
                1 if from_cache else 0,
                error,
            ),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def latest_success(self, fingerprint: str) -> sqlite3.Row | None:
        return self.conn.execute(
            """
            SELECT * FROM raw_fetches
            WHERE fingerprint = ? AND from_cache = 0 AND error IS NULL
              AND http_status = 200 AND body_path IS NOT NULL
            ORDER BY id DESC LIMIT 1
            """,
            (fingerprint,),
        ).fetchone()

    def reserve_host(self, host: str, min_interval: float, now: datetime) -> float:
        row = self.conn.execute(
            "SELECT last_request_at FROM rate_limit WHERE host = ?",
            (host,),
        ).fetchone()
        if row is None:
            return 0.0
        last = datetime.fromisoformat(row["last_request_at"])
        elapsed = (now - last).total_seconds()
        if elapsed >= min_interval:
            return 0.0
        return min_interval - elapsed

    def mark_host(self, host: str, now: datetime) -> None:
        stamp = now.isoformat(timespec="seconds")
        self.conn.execute(
            """
            INSERT INTO rate_limit (host, last_request_at) VALUES (?, ?)
            ON CONFLICT(host) DO UPDATE SET last_request_at = excluded.last_request_at
            """,
            (host, stamp),
        )
        self.conn.commit()

    def upsert_version(
        self,
        *,
        fund_code: str,
        as_of_date: str,
        series: str,
        source_name: str,
        original_value: str,
        original_unit: str,
        standardized_value: str | None,
        standardized_unit: str | None,
        source_url: str,
        fetched_at: datetime,
        snapshot_phase: str,
        content_hash: str,
        quality_status: str,
        quality_flags: list[str],
        authoritative: bool,
        lookahead_free: bool,
        raw_fetch_id: int | None,
        note: str,
        network_fetched_at: datetime | None = None,
        cache_accessed_at: datetime | None = None,
        observation_available_at: datetime | None = None,
        decided_at: datetime | None = None,
        cause: str | None = None,
    ) -> UpsertResult:
        fetched = fetched_at.isoformat(timespec="seconds")
        available = (observation_available_at or fetched_at).isoformat(timespec="seconds")
        decided = (decided_at or fetched_at).isoformat(timespec="seconds")
        network_stamp = network_fetched_at.isoformat(timespec="seconds") if network_fetched_at else None
        cache_stamp = cache_accessed_at.isoformat(timespec="seconds") if cache_accessed_at else None
        flags = json.dumps(quality_flags, ensure_ascii=False)
        existing = self.conn.execute(
            """
            SELECT * FROM observations
            WHERE fund_code = ? AND as_of_date = ? AND series = ? AND source_name = ?
            """,
            (fund_code, as_of_date, series, source_name),
        ).fetchone()
        if existing is None:
            cursor = self.conn.execute(
                """
                INSERT INTO observations (
                    fund_code, as_of_date, series, source_name, first_seen_at, revised_at,
                    authoritative, lookahead_free, latest_version_no
                ) VALUES (?, ?, ?, ?, ?, NULL, ?, ?, 1)
                """,
                (
                    fund_code,
                    as_of_date,
                    series,
                    source_name,
                    available,
                    1 if authoritative else 0,
                    1 if lookahead_free else 0,
                ),
            )
            observation_id = int(cursor.lastrowid)
            self._insert_version(
                observation_id=observation_id,
                version_no=1,
                fund_code=fund_code,
                as_of_date=as_of_date,
                series=series,
                source_name=source_name,
                original_value=original_value,
                original_unit=original_unit,
                standardized_value=standardized_value,
                standardized_unit=standardized_unit,
                source_url=source_url,
                fetched_at=fetched,
                first_seen_at=available,
                revised_at=None,
                snapshot_phase=snapshot_phase,
                content_hash=content_hash,
                quality_status=quality_status,
                quality_flags=flags,
                raw_fetch_id=raw_fetch_id,
                network_fetched_at=network_stamp,
                cache_accessed_at=cache_stamp,
                observation_available_at=available,
                note=note,
            )
            self._event(observation_id, "created", available, content_hash)
            self.conn.commit()
            return UpsertResult("created", observation_id, 1, available, None, quality_status)

        latest = self.latest_version_row(int(existing["id"]))
        same_number = latest["content_hash"] == content_hash
        same_phase = latest["snapshot_phase"] == snapshot_phase
        same_status = latest["quality_status"] == quality_status
        same_flags = json.loads(latest["quality_flags"]) == quality_flags
        if same_number and same_phase and same_status and same_flags:
            self._event(int(existing["id"]), "confirmed_same_hash", fetched, content_hash)
            self.conn.commit()
            return UpsertResult(
                "confirmed",
                int(existing["id"]),
                int(latest["version_no"]),
                existing["first_seen_at"],
                existing["revised_at"],
                latest["quality_status"],
            )

        version_no = int(existing["latest_version_no"]) + 1
        self._insert_version(
            observation_id=int(existing["id"]),
            version_no=version_no,
            fund_code=fund_code,
            as_of_date=as_of_date,
            series=series,
            source_name=source_name,
            original_value=original_value,
            original_unit=original_unit,
            standardized_value=standardized_value,
            standardized_unit=standardized_unit,
            source_url=source_url,
                fetched_at=fetched,
                first_seen_at=existing["first_seen_at"],
                revised_at=decided,
                snapshot_phase=snapshot_phase,
                content_hash=content_hash,
                quality_status=quality_status,
                quality_flags=flags,
                raw_fetch_id=raw_fetch_id,
                network_fetched_at=network_stamp,
                cache_accessed_at=cache_stamp,
                observation_available_at=available,
                note=note,
            )
        self.conn.execute(
            """
            UPDATE observations
            SET revised_at = ?, authoritative = ?, lookahead_free = ?, latest_version_no = ?
            WHERE id = ?
            """,
            (
                decided,
                1 if authoritative else 0,
                1 if lookahead_free else 0,
                version_no,
                int(existing["id"]),
            ),
        )
        if cause == "dependent":
            action = "dependent_revised"
        elif not same_number:
            action = "revised"
        else:
            action = "phase_revised"
        self._event(int(existing["id"]), action, decided, content_hash)
        self.conn.commit()
        return UpsertResult(
            action,
            int(existing["id"]),
            version_no,
            existing["first_seen_at"],
            decided,
            quality_status,
        )

    def _insert_version(self, **kwargs) -> None:
        self.conn.execute(
            """
            INSERT INTO observation_versions (
                observation_id, version_no, fund_code, as_of_date, series, source_name,
                original_value, original_unit, standardized_value, standardized_unit,
                source_url, fetched_at, first_seen_at, revised_at, snapshot_phase,
                content_hash, quality_status, quality_flags, raw_fetch_id,
                network_fetched_at, cache_accessed_at, observation_available_at, note
            ) VALUES (
                :observation_id, :version_no, :fund_code, :as_of_date, :series, :source_name,
                :original_value, :original_unit, :standardized_value, :standardized_unit,
                :source_url, :fetched_at, :first_seen_at, :revised_at, :snapshot_phase,
                :content_hash, :quality_status, :quality_flags, :raw_fetch_id,
                :network_fetched_at, :cache_accessed_at, :observation_available_at, :note
            )
            """,
            kwargs,
        )

    def _event(self, observation_id: int, status: str, created_at: str, detail: str) -> None:
        observation = self.conn.execute(
            "SELECT * FROM observations WHERE id = ?",
            (observation_id,),
        ).fetchone()
        self.conn.execute(
            """
            INSERT INTO quality_events (
                fund_code, as_of_date, series, source_name, status, detail, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                observation["fund_code"],
                observation["as_of_date"],
                observation["series"],
                observation["source_name"],
                status,
                detail,
                created_at,
            ),
        )

    def latest_version_row(self, observation_id: int) -> sqlite3.Row:
        row = self.conn.execute(
            """
            SELECT * FROM observation_versions
            WHERE observation_id = ?
            ORDER BY version_no DESC LIMIT 1
            """,
            (observation_id,),
        ).fetchone()
        if row is None:
            raise RuntimeError(f"观察 {observation_id} 没有版本")
        return row

    def count_versions(self, fund_code: str, as_of_date: str, series: str, source_name: str) -> int:
        row = self.conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM observation_versions
            WHERE fund_code = ? AND as_of_date = ? AND series = ? AND source_name = ?
            """,
            (fund_code, as_of_date, series, source_name),
        ).fetchone()
        return int(row["n"])

    def get_observation(self, fund_code: str, as_of_date: str, series: str, source_name: str):
        return self.conn.execute(
            """
            SELECT * FROM observations
            WHERE fund_code = ? AND as_of_date = ? AND series = ? AND source_name = ?
            """,
            (fund_code, as_of_date, series, source_name),
        ).fetchone()

    def add_gap(
        self,
        *,
        fund_code: str,
        as_of_date: str,
        series: str,
        source_name: str,
        reason: str,
        fetched_at: datetime,
    ) -> None:
        stamp = fetched_at.isoformat(timespec="seconds")
        self.conn.execute(
            """
            INSERT INTO data_gaps (
                fund_code, as_of_date, series, source_name, reason, fetched_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(fund_code, as_of_date, series, source_name, reason)
            DO UPDATE SET fetched_at = excluded.fetched_at
            """,
            (fund_code, as_of_date, series, source_name, reason, stamp),
        )
        self.conn.commit()

    def add_quality_event(
        self,
        *,
        fund_code: str | None,
        as_of_date: str | None,
        series: str | None,
        source_name: str | None,
        status: str,
        detail: str,
        created_at: datetime,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO quality_events (
                fund_code, as_of_date, series, source_name, status, detail, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fund_code,
                as_of_date,
                series,
                source_name,
                status,
                detail,
                created_at.isoformat(timespec="seconds"),
            ),
        )
        self.conn.commit()

    def add_disclosure(self, *, fund_code: str | None, as_of_date: str, kind: str, note: str, created_at: datetime) -> int:
        kind, note = prepare_disclosure(kind=kind, note=note)
        cursor = self.conn.execute(
            """
            INSERT INTO disclosure_records (fund_code, as_of_date, kind, note, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (fund_code, as_of_date, kind, note, created_at.isoformat(timespec="seconds")),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def checkpoint(self, source_name: str, key: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM checkpoints WHERE source_name = ? AND checkpoint_key = ?",
            (source_name, key),
        ).fetchone()

    def set_checkpoint(self, source_name: str, key: str, status: str, now: datetime, detail: str = "") -> None:
        self.conn.execute(
            """
            INSERT INTO checkpoints (source_name, checkpoint_key, status, updated_at, detail)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(source_name, checkpoint_key) DO UPDATE SET
                status = excluded.status,
                updated_at = excluded.updated_at,
                detail = excluded.detail
            """,
            (source_name, key, status, now.isoformat(timespec="seconds"), detail),
        )
        self.conn.commit()

    def version_count(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) AS n FROM observation_versions").fetchone()["n"])

    def gap_count(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) AS n FROM data_gaps").fetchone()["n"])

    def raw_count(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) AS n FROM raw_fetches").fetchone()["n"])

    def latest_join(self, fund_code: str, as_of_date: str, series: str, source_name: str):
        return self.conn.execute(
            """
            SELECT o.first_seen_at, o.revised_at, o.authoritative, o.lookahead_free,
                   v.original_value, v.original_unit, v.standardized_value, v.standardized_unit,
                   v.source_url, v.fetched_at, v.snapshot_phase, v.content_hash,
                   v.quality_status, v.quality_flags, v.note, v.version_no,
                   v.raw_fetch_id, v.network_fetched_at, v.cache_accessed_at,
                   v.observation_available_at
            FROM observations o
            JOIN observation_versions v
              ON v.observation_id = o.id AND v.version_no = o.latest_version_no
            WHERE o.fund_code = ? AND o.as_of_date = ? AND o.series = ? AND o.source_name = ?
            """,
            (fund_code, as_of_date, series, source_name),
        ).fetchone()

    def summary_lines(self) -> list[str]:
        lines = [
            f"原始响应 {self.raw_count()} 条，观察版本 {self.version_count()} 条，缺口 {self.gap_count()} 条。"
        ]
        rows = self.conn.execute(
            """
            SELECT v.source_name, v.series, v.quality_status, COUNT(*) AS n
            FROM observation_versions v
            JOIN observations o ON o.id = v.observation_id AND o.latest_version_no = v.version_no
            GROUP BY v.source_name, v.series, v.quality_status
            ORDER BY v.source_name, v.series, v.quality_status
            """
        ).fetchall()
        for row in rows:
            lines.append(
                f"{row['source_name']} {row['series']} {row['quality_status']}: {row['n']}"
            )
        gaps = self.conn.execute(
            """
            SELECT source_name, as_of_date, fund_code, series, reason
            FROM data_gaps
            ORDER BY as_of_date, fund_code, series
            LIMIT 40
            """
        ).fetchall()
        for row in gaps:
            lines.append(
                f"缺口 {row['as_of_date']} {row['fund_code']} {row['series']} "
                f"{row['source_name']} {row['reason']}"
            )
        return lines
