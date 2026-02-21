from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .config import settings
from .db import get_session
from .models import DuplicateFile, Page


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


def _fetch_pages_by_hash(session: Session) -> dict[str, Page]:
    rows = session.execute(select(Page)).scalars().all()
    return {str(row.file_hash): row for row in rows}


def _fetch_pages_by_rel_path(session: Session) -> dict[str, Page]:
    rows = session.execute(select(Page)).scalars().all()
    return {str(row.rel_path): row for row in rows}


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

    with get_session() as session:
        session.execute(update(DuplicateFile).values(active=False))

        pages_by_hash = _fetch_pages_by_hash(session)
        pages_by_rel_path = _fetch_pages_by_rel_path(session)

        seen_page_ids: set[int] = set()

        for file_hash in sorted(grouped_paths.keys()):
            rel_paths = sorted(grouped_paths[file_hash])
            canonical_rel_path = rel_paths[0]

            page_row = pages_by_hash.get(file_hash)
            if page_row is not None:
                old_rel_path = str(page_row.rel_path)
                page_row.rel_path = canonical_rel_path
                page_row.updated_at = now
                page_row.last_seen_at = now
                page_row.is_missing = False
                page_id = int(page_row.id)
                updated_pages += 1

                if old_rel_path != canonical_rel_path:
                    pages_by_rel_path.pop(old_rel_path, None)
                pages_by_rel_path[canonical_rel_path] = page_row
            else:
                existing_path_row = pages_by_rel_path.get(canonical_rel_path)
                if existing_path_row is not None:
                    old_hash = str(existing_path_row.file_hash)
                    existing_path_row.file_hash = file_hash
                    existing_path_row.updated_at = now
                    existing_path_row.last_seen_at = now
                    existing_path_row.is_missing = False
                    page_id = int(existing_path_row.id)
                    updated_pages += 1

                    if old_hash != file_hash:
                        pages_by_hash.pop(old_hash, None)
                    pages_by_hash[file_hash] = existing_path_row
                else:
                    page_row = Page(
                        rel_path=canonical_rel_path,
                        file_hash=file_hash,
                        status="new",
                        created_at=now,
                        updated_at=now,
                        last_seen_at=now,
                        is_missing=False,
                    )
                    session.add(page_row)
                    session.flush()
                    page_id = int(page_row.id)
                    new_pages += 1
                    pages_by_hash[file_hash] = page_row
                    pages_by_rel_path[canonical_rel_path] = page_row

            seen_page_ids.add(page_id)

            for duplicate_rel_path in rel_paths[1:]:
                duplicate_files += 1
                existing_duplicate = session.execute(
                    select(DuplicateFile).where(DuplicateFile.rel_path == duplicate_rel_path).limit(1)
                ).scalar_one_or_none()

                if existing_duplicate is None:
                    session.add(
                        DuplicateFile(
                            rel_path=duplicate_rel_path,
                            file_hash=file_hash,
                            canonical_page_id=page_id,
                            active=True,
                            first_seen_at=now,
                            last_seen_at=now,
                        )
                    )
                else:
                    existing_duplicate.file_hash = file_hash
                    existing_duplicate.canonical_page_id = page_id
                    existing_duplicate.active = True
                    existing_duplicate.last_seen_at = now

        if seen_page_ids:
            stale_pages = session.execute(
                select(Page)
                .where(Page.id.not_in(seen_page_ids))
                .where(Page.is_missing.is_(False))
            ).scalars().all()
        else:
            stale_pages = session.execute(select(Page).where(Page.is_missing.is_(False))).scalars().all()

        for stale_page in stale_pages:
            stale_page.is_missing = True
            stale_page.updated_at = now

        missing_marked = len(stale_pages)

    return ScanSummary(
        source_dir=str(settings.source_dir),
        scanned_files=scanned_count,
        new_pages=new_pages,
        updated_pages=updated_pages,
        missing_marked=missing_marked,
        duplicate_files=duplicate_files,
    )
