"""Standalone tests for the archive logic (no Home Assistant needed).

Run from the repo root:  python3 -m unittest discover tests
"""

import datetime
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

import importlib.util  # noqa: E402
import types  # noqa: E402

_PKG = Path(__file__).resolve().parent.parent / "custom_components" / "print_timelapse"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# Load const.py and archive.py directly so the package __init__ (which needs
# Home Assistant) is never imported.
_package = types.ModuleType("print_timelapse")
_package.__path__ = [str(_PKG)]
sys.modules["print_timelapse"] = _package
_load("print_timelapse.const", _PKG / "const.py")
archive = _load("print_timelapse.archive", _PKG / "archive.py")

TZ = datetime.timezone.utc


def make_job(root: Path, name: str, frames: int = 3, videos=("720p", "1080p")) -> Path:
    job = root / name
    job.mkdir(parents=True)
    for i in range(frames):
        frame = job / f"f_{i:06d}.jpg"
        frame.write_bytes(b"\xff\xd8frame%d" % i)
        ts = time.time() - (frames - i) * 60
        import os

        os.utime(frame, (ts, ts))
    for res in videos:
        video = job / f"timelapse_{res}.mp4"
        video.write_bytes(b"video-" + res.encode())
        old = time.time() - 60
        os.utime(video, (old, old))
    (job / "assembled.json").write_text(json.dumps({"frames": frames, "ts": time.time()}))
    return job


class ArchiveTest(unittest.TestCase):
    def test_archive_job_and_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "capture"
            dest = Path(tmp) / "archive"
            dest.mkdir()
            make_job(source, "job_1")
            make_job(source, "job_2", videos=("720p",))

            meta = archive.archive_job(source / "job_1", dest, "benchy.gcode", TZ, 0)
            self.assertIsNotNone(meta)
            self.assertEqual(meta["file_name"], "benchy.gcode")
            self.assertEqual(meta["frames"], 3)
            self.assertIn("720p", meta["videos"])
            self.assertTrue((dest / "job_1" / "timelapse_720p.mp4").exists())
            self.assertTrue((dest / "job_1" / "preview.jpg").exists())
            self.assertTrue((dest / "job_1" / "details.json").exists())

            archive.archive_job(source / "job_2", dest, None, TZ, 0)
            index = archive.build_index(dest, TZ)
            self.assertEqual(index["job_count"], 2)
            self.assertEqual(index["jobs"][0]["job_id"], 2)  # newest first
            self.assertEqual(index["schema"], 1)
            self.assertIn("retention", index)

            # Source videos must never be removed by archiving.
            self.assertTrue((source / "job_1" / "timelapse_720p.mp4").exists())

    def test_unfinished_job_not_archived(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "capture"
            dest = Path(tmp) / "archive"
            dest.mkdir()
            job = source / "job_1"
            job.mkdir(parents=True)
            (job / "f_000000.jpg").write_bytes(b"frame")
            # No assembled marker yet.
            self.assertIsNone(archive.archive_job(job, dest, None, TZ, 0))

    def test_existing_archive_size_conflict_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "capture"
            dest = Path(tmp) / "archive"
            (dest / "job_1").mkdir(parents=True)
            (dest / "job_1" / "timelapse_720p.mp4").write_bytes(b"different-bytes")
            make_job(source, "job_1")
            with self.assertRaises(archive.ArchiveError):
                archive.archive_job(source / "job_1", dest, None, TZ, 0)

    def test_names_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            archive.save_names(dest, {"job_1": "flower.gcode"})
            self.assertEqual(archive.load_names(dest), {"job_1": "flower.gcode"})
            (dest / "names.json").write_text("not json")
            self.assertEqual(archive.load_names(dest), {})

    def test_metadata_is_honest_about_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "capture"
            dest = Path(tmp) / "archive"
            dest.mkdir()
            make_job(source, "job_1")
            meta = archive.archive_job(source / "job_1", dest, None, TZ, 0)
            self.assertIn("not verified print start/end", meta["coverage_note"])


if __name__ == "__main__":
    unittest.main()
