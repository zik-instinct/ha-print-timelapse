"""Archive logic for Print Timelapse Archive.

Pure filesystem code with no Home Assistant imports so it can run in an
executor and be unit-tested outside Home Assistant.

The archive never deletes archived media. Completed recordings are retained
with hard links when possible and verified copies across filesystems, keeping
a configurable free-space reserve.
"""

from __future__ import annotations

import datetime
import errno
import hashlib
import json
import os
from pathlib import Path
import shutil
from typing import Any

from .const import (
    ASSEMBLED_MARKER,
    COVERAGE_NOTE,
    DETAILS_FILE,
    INDEX_FILE,
    NAMES_FILE,
    RESOLUTIONS,
    RETENTION_NOTE,
    SCHEMA_VERSION,
)

GAP_THRESHOLD_SECONDS = 120


class ArchiveError(Exception):
    """Raised when a file cannot be safely archived."""


def _iso(ts: float, tz: datetime.tzinfo) -> str:
    return datetime.datetime.fromtimestamp(ts, tz).isoformat(timespec="seconds")


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    """Write JSON atomically so readers never see a partial file."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    os.replace(tmp, path)


def retain_file(src: Path, dst: Path, reserve_bytes: int) -> None:
    """Retain src at dst without deleting anything.

    Hard link when possible; across filesystems copy while the source is
    unchanged and verify SHA-256 before swapping the copy into place.
    """
    if dst.exists():
        if dst.stat().st_size != src.stat().st_size:
            raise ArchiveError(f"Existing archive file differs in size: {dst}")
        return
    try:
        os.link(src, dst)
        return
    except OSError as err:
        if err.errno != errno.EXDEV:
            raise ArchiveError(f"Could not link {src} -> {dst}: {err}") from err
    if shutil.disk_usage(dst.parent).free < src.stat().st_size + reserve_bytes:
        raise ArchiveError("Archive free-space reserve reached")
    before = src.stat()
    tmp = dst.with_suffix(dst.suffix + ".part")
    try:
        shutil.copy2(src, tmp)
        after = src.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ArchiveError("Source changed during archive copy")
        if _sha256(src) != _sha256(tmp):
            raise ArchiveError("Archive checksum mismatch")
        os.replace(tmp, dst)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _sha256(path: Path) -> bytes:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.digest()


def load_names(dest_root: Path) -> dict[str, str]:
    """Load the job-id -> file name mapping."""
    names_path = dest_root / NAMES_FILE
    if names_path.is_file():
        try:
            return json.loads(names_path.read_text())
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


def save_names(dest_root: Path, names: dict[str, str]) -> None:
    atomic_write_json(dest_root / NAMES_FILE, names)


def build_job_metadata(
    job_dir: Path,
    file_name: str | None,
    tz: datetime.tzinfo,
) -> dict[str, Any] | None:
    """Build metadata for one finished job directory, or None if not ready.

    The job directory must contain the assembled marker plus at least one
    finished video. Frames are interval JPEGs named f_*.jpg.
    """
    marker_path = job_dir / ASSEMBLED_MARKER
    if not marker_path.is_file():
        return None
    marker = json.loads(marker_path.read_text())

    videos: dict[str, dict[str, Any]] = {}
    for res in RESOLUTIONS:
        video = job_dir / f"timelapse_{res}.mp4"
        if video.is_file() and video.stat().st_size > 0:
            videos[res] = {
                "path": f"{job_dir.name}/{video.name}",
                "bytes": video.stat().st_size,
            }
    if not videos:
        return None

    frames = sorted(job_dir.glob("f_*.jpg"))
    times = sorted(f.stat().st_mtime for f in frames)
    gaps = [round(b - a, 1) for a, b in zip(times, times[1:]) if b - a > GAP_THRESHOLD_SECONDS]

    return {
        "id": job_dir.name,
        "job_id": int(job_dir.name.removeprefix("job_")),
        "file_name": file_name,
        "frames": len(frames),
        "assembled_frames": marker.get("frames"),
        "first_capture": _iso(times[0], tz) if times else None,
        "last_capture": _iso(times[-1], tz) if times else None,
        "span_seconds": round(times[-1] - times[0]) if times else 0,
        "gaps_over_2min": len(gaps),
        "largest_gap_seconds": max(gaps, default=0),
        "assembled_at": _iso(marker["ts"], tz),
        "videos": videos,
        "poster": f"{job_dir.name}/preview.jpg" if frames else None,
        "coverage_note": COVERAGE_NOTE,
    }


def archive_job(
    job_dir: Path,
    dest_root: Path,
    file_name: str | None,
    tz: datetime.tzinfo,
    reserve_bytes: int,
) -> dict[str, Any] | None:
    """Retain a finished job's videos and preview in the archive.

    Returns the job metadata, or None when the job is not ready. Only files
    whose close precedes the assembled marker are archived, so a video that
    is still being written is never published.
    """
    marker_path = job_dir / ASSEMBLED_MARKER
    if not marker_path.is_file():
        return None
    marker_mtime = marker_path.stat().st_mtime

    out = dest_root / job_dir.name
    out.mkdir(parents=True, exist_ok=True)

    for res in RESOLUTIONS:
        src = job_dir / f"timelapse_{res}.mp4"
        if not src.is_file() or src.stat().st_size == 0:
            continue
        if src.stat().st_mtime > marker_mtime:
            continue
        retain_file(src, out / src.name, reserve_bytes)

    frames = sorted(job_dir.glob("f_*.jpg"))
    if frames:
        retain_file(frames[-1], out / "preview.jpg", reserve_bytes)

    # The marker documents when assembly finished; keep it with the archive.
    retain_file(marker_path, out / ASSEMBLED_MARKER, reserve_bytes)

    # Metadata counts the source job's frames; the archive keeps only the
    # videos and one preview frame. Paths inside the metadata are relative
    # to the job name, which is identical in the archive layout.
    metadata = build_job_metadata(job_dir, file_name, tz)
    if metadata is None:
        return None
    atomic_write_json(out / DETAILS_FILE, metadata)
    return metadata


def build_index(dest_root: Path, tz: datetime.tzinfo) -> dict[str, Any]:
    """Rebuild the archive-level index from per-job metadata files."""
    jobs = []
    for details_path in dest_root.glob(f"job_*/{DETAILS_FILE}"):
        try:
            jobs.append(json.loads(details_path.read_text()))
        except (OSError, json.JSONDecodeError):
            continue
    jobs.sort(key=lambda job: job["job_id"], reverse=True)
    disk = os.statvfs(dest_root)
    manifest: dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "updated_at": _iso(datetime.datetime.now(tz).timestamp(), tz),
        "jobs": jobs,
        "job_count": len(jobs),
        "free_bytes": disk.f_bavail * disk.f_frsize,
        "retention": RETENTION_NOTE,
    }
    atomic_write_json(dest_root / INDEX_FILE, manifest)
    return manifest


def load_index(dest_root: Path) -> dict[str, Any] | None:
    """Load the archive index, or None if not built yet."""
    index_path = dest_root / INDEX_FILE
    if not index_path.is_file():
        return None
    try:
        return json.loads(index_path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
