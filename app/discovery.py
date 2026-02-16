from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import sqlite3

from .config import settings
from .db import get_connection


@dataclass
class ScanSummary:
    source_dir: str
    scanned_files: int
    new_pages: int
    updated_pages: int
    missing_marked: int
    duplicate_files: int


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        while chunk := file_handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _relative_path(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _scan_file_hashes() -> list[tuple[str, str]]:
    source_dir = settings.source_dir
    source_dir.mkdir(parents=True, exist_ok=True)

    scanned: list[tuple[str, str]] = []
    for path in sorted(source_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in settings.allowed_extensions:
            continue

        rel_path = _relative_path(path, source_dir)
        scanned.append((rel_path, _hash_file(path)))

    return scanned


def _fetch_pages_by_hash(conn: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    rows = conn.execute("SELECT * FROM pages").fetchall()
    return {row["file_hash"]: row for row in rows}


def _fetch_pages_by_rel_path(conn: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    rows = conn.execute("SELECT * FROM pages").fetchall()
    return {row["rel_path"]: row for row in rows}


def discover_images() -> ScanSummary:
    scanned = _scan_file_hashes()
    grouped_paths: dict[str, list[str]] = defaultdict(list)

    for rel_path, file_hash in scanned:
        grouped_paths[file_hash].append(rel_path)

    now = _utc_now()
    scanned_count = len(scanned)
    new_pages = 0
    updated_pages = 0
    duplicate_files = 0

    with get_connection() as conn:
        conn.execute("UPDATE duplicate_files SET active = 0")

        pages_by_hash = _fetch_pages_by_hash(conn)
        pages_by_rel_path = _fetch_pages_by_rel_path(conn)

        seen_page_ids: set[int] = set()

        for file_hash in sorted(grouped_paths.keys()):
            rel_paths = sorted(grouped_paths[file_hash])
            canonical_rel_path = rel_paths[0]

            page_row = pages_by_hash.get(file_hash)
            if page_row is not None:
                conn.execute(
                    """
                    UPDATE pages
                    SET rel_path = ?, updated_at = ?, last_seen_at = ?, is_missing = 0
                    WHERE id = ?
                    """,
                    (canonical_rel_path, now, now, page_row["id"]),
                )
                page_id = int(page_row["id"])
                updated_pages += 1
            else:
                existing_path_row = pages_by_rel_path.get(canonical_rel_path)
                if existing_path_row is not None:
                    conn.execute(
                        """
                        UPDATE pages
                        SET file_hash = ?, updated_at = ?, last_seen_at = ?, is_missing = 0
                        WHERE id = ?
                        """,
                        (file_hash, now, now, existing_path_row["id"]),
                    )
                    page_id = int(existing_path_row["id"])
                    updated_pages += 1
                else:
                    cursor = conn.execute(
                        """
                        INSERT INTO pages(rel_path, file_hash, status, created_at, updated_at, last_seen_at, is_missing)
                        VALUES (?, ?, 'new', ?, ?, ?, 0)
                        """,
                        (canonical_rel_path, file_hash, now, now, now),
                    )
                    page_id = int(cursor.lastrowid)
                    new_pages += 1

            seen_page_ids.add(page_id)

            for duplicate_rel_path in rel_paths[1:]:
                duplicate_files += 1
                existing_duplicate = conn.execute(
                    "SELECT id, first_seen_at FROM duplicate_files WHERE rel_path = ?",
                    (duplicate_rel_path,),
                ).fetchone()

                if existing_duplicate is None:
                    conn.execute(
                        """
                        INSERT INTO duplicate_files(
                            rel_path,
                            file_hash,
                            canonical_page_id,
                            active,
                            first_seen_at,
                            last_seen_at
                        )
                        VALUES (?, ?, ?, 1, ?, ?)
                        """,
                        (duplicate_rel_path, file_hash, page_id, now, now),
                    )
                else:
                    conn.execute(
                        """
                        UPDATE duplicate_files
                        SET file_hash = ?,
                            canonical_page_id = ?,
                            active = 1,
                            last_seen_at = ?
                        WHERE id = ?
                        """,
                        (file_hash, page_id, now, existing_duplicate["id"]),
                    )

        if seen_page_ids:
            placeholders = ",".join("?" for _ in seen_page_ids)
            result = conn.execute(
                f"""
                UPDATE pages
                SET is_missing = 1,
                    updated_at = ?
                WHERE id NOT IN ({placeholders}) AND is_missing = 0
                """,
                (now, *seen_page_ids),
            )
        else:
            result = conn.execute(
                """
                UPDATE pages
                SET is_missing = 1,
                    updated_at = ?
                WHERE is_missing = 0
                """,
                (now,),
            )

        missing_marked = result.rowcount

    return ScanSummary(
        source_dir=str(settings.source_dir),
        scanned_files=scanned_count,
        new_pages=new_pages,
        updated_pages=updated_pages,
        missing_marked=missing_marked,
        duplicate_files=duplicate_files,
    )
