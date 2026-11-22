"""End-to-end recorder test with a mocked Home Assistant runtime.

Run from the repo root:  python3 -m unittest discover tests -v
Exercises: job start on state change, interval captures, ffmpeg assembly,
archival, index rebuild and frame cleanup.
"""

import asyncio
import datetime
import importlib.util
import json
import os
import stat
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

_PKG = Path(__file__).resolve().parent.parent / "custom_components" / "print_timelapse"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# ---- Stub the homeassistant modules recorder.py imports ------------------

ha = types.ModuleType("homeassistant")
ha.__path__ = []
components = types.ModuleType("homeassistant.components")
components.__path__ = []
helpers = types.ModuleType("homeassistant.helpers")
helpers.__path__ = []
util = types.ModuleType("homeassistant.util")
util.__path__ = []


class HomeAssistantError(Exception):
    pass


class _State:
    def __init__(self, state, attributes=None):
        self.state = state
        self.attributes = attributes or {}
        self.name = "Test"


class _Event:
    def __init__(self, new_state):
        self.data = {"new_state": new_state}


class _Store:
    saved = {}

    def __init__(self, hass, version, key):
        self.key = key

    async def async_load(self):
        return _Store.saved.get(self.key)

    async def async_save(self, data):
        _Store.saved[self.key] = data


class _Config:
    def __init__(self, base):
        self._base = Path(base)
        self.media_dirs = {"local": str(self._base / "media")}
        self.time_zone = "UTC"

    def path(self, *parts):
        return str(self._base.joinpath(*parts))


class FakeHass:
    def __init__(self, base):
        self.config = _Config(base)
        self.states = mock.Mock()
        self._states = {}
        self.states.get = self._states.get
        self._state_callbacks = []
        self._tick = None

    def set_state(self, entity_id, value, attributes=None):
        self._states[entity_id] = _State(value, attributes)

    async def async_add_executor_job(self, fn, *args):
        return fn(*args)

    def async_create_task(self, coro):
        return asyncio.get_event_loop().create_task(coro)


def _callback(fn):
    return fn


def _track_state(hass, entity_ids, cb):
    hass._state_callbacks.append(cb)

    def _unsub():
        hass._state_callbacks.remove(cb)

    return _unsub


def _track_interval(hass, cb, interval):
    hass._tick = cb

    def _unsub():
        hass._tick = None

    return _unsub


async def _fake_image(hass, entity_id, timeout=10, width=None, height=None):
    return types.SimpleNamespace(content=b"\xff\xd8fake-jpeg")


camera_mod = types.ModuleType("homeassistant.components.camera")
camera_mod.async_get_image = _fake_image
config_entries_mod = types.ModuleType("homeassistant.config_entries")
config_entries_mod.ConfigEntry = object
core_mod = types.ModuleType("homeassistant.core")
core_mod.HomeAssistant = FakeHass
core_mod.Event = _Event
core_mod.EventStateChangedData = dict
core_mod.callback = _callback
exceptions_mod = types.ModuleType("homeassistant.exceptions")
exceptions_mod.HomeAssistantError = HomeAssistantError
dispatcher_mod = types.ModuleType("homeassistant.helpers.dispatcher")
dispatcher_mod.async_dispatcher_send = lambda *a, **k: None
dispatcher_mod.async_dispatcher_connect = lambda *a, **k: (lambda: None)
event_mod = types.ModuleType("homeassistant.helpers.event")
event_mod.async_track_state_change_event = _track_state
event_mod.async_track_time_interval = _track_interval
storage_mod = types.ModuleType("homeassistant.helpers.storage")
storage_mod.Store = _Store
dt_mod = types.ModuleType("homeassistant.util.dt")
dt_mod.get_time_zone = lambda name: datetime.timezone.utc

sys.modules.update(
    {
        "homeassistant": ha,
        "homeassistant.components": components,
        "homeassistant.components.camera": camera_mod,
        "homeassistant.config_entries": config_entries_mod,
        "homeassistant.core": core_mod,
        "homeassistant.exceptions": exceptions_mod,
        "homeassistant.helpers": helpers,
        "homeassistant.helpers.dispatcher": dispatcher_mod,
        "homeassistant.helpers.event": event_mod,
        "homeassistant.helpers.storage": storage_mod,
        "homeassistant.util": util,
        "homeassistant.util.dt": dt_mod,
    }
)

package = types.ModuleType("print_timelapse")
package.__path__ = [str(_PKG)]
sys.modules["print_timelapse"] = package
_load("print_timelapse.const", _PKG / "const.py")
_load("print_timelapse.archive", _PKG / "archive.py")
recorder_mod = _load("print_timelapse.recorder", _PKG / "recorder.py")


class _Entry:
    def __init__(self, tmp):
        self.entry_id = "testentry"
        self.data = {
            "camera_entity": "camera.test",
            "status_entity": "sensor.status",
            "printing_states": "printing",
            "capture_interval": 60,
            "job_name_attribute": "filename",
            "keep_frames": False,
        }
        self.options = {}
        self.title = "Test printer"


def _fake_ffmpeg(directory: Path) -> Path:
    script = directory / "ffmpeg"
    script.write_text('#!/bin/sh\nfor last; do :; done\nprintf "fake-video" > "$last"\n')
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


class RecorderTest(unittest.TestCase):
    def test_full_print_cycle(self):
        async def run():
            with tempfile.TemporaryDirectory() as tmp:
                _Store.saved = {}
                hass = FakeHass(tmp)
                hass.set_state("sensor.status", "idle", {"filename": "benchy.gcode"})
                entry = _Entry(tmp)
                recorder = recorder_mod.TimelapseRecorder(hass, entry)

                with tempfile.TemporaryDirectory() as bindir:
                    _fake_ffmpeg(Path(bindir))
                    with mock.patch.dict(os.environ, {"PATH": f"{bindir}:{os.environ['PATH']}"}):
                        await recorder.async_start()

                        # Print starts: state change begins the job and takes
                        # the first frame.
                        hass.set_state("sensor.status", "printing", {"filename": "benchy.gcode"})
                        for cb in list(hass._state_callbacks):
                            await cb(_Event(hass._states["sensor.status"]))
                        self.assertEqual(recorder.active_job, "job_1")
                        self.assertEqual(recorder.capture_state, "capturing")

                        # Two interval ticks -> 3 frames total.
                        await hass._tick(None)
                        await hass._tick(None)
                        job_dir = Path(tmp) / "print_timelapse" / "testentry" / "job_1"
                        self.assertEqual(len(list(job_dir.glob("f_*.jpg"))), 3)

                        # Print ends: assemble, archive, clean up frames.
                        hass.set_state("sensor.status", "idle")
                        for cb in list(hass._state_callbacks):
                            await cb(_Event(hass._states["sensor.status"]))
                        await asyncio.sleep(0)  # let finalize task run
                        self.assertIsNone(recorder.last_error, recorder.last_error)

                        archive = Path(tmp) / "media" / "print_timelapse_archive" / "job_1"
                        self.assertTrue((archive / "timelapse_720p.mp4").is_file())
                        self.assertTrue((archive / "timelapse_1080p.mp4").is_file())
                        self.assertTrue((archive / "preview.jpg").is_file())
                        details = json.loads((archive / "details.json").read_text())
                        self.assertEqual(details["frames"], 3)
                        self.assertEqual(details["file_name"], "benchy.gcode")

                        index = json.loads(
                            (archive.parent / "index.json").read_text()
                        )
                        self.assertEqual(index["job_count"], 1)
                        self.assertEqual(index["jobs"][0]["job_id"], 1)

                        # Frames removed after archiving; job state cleared.
                        self.assertFalse(job_dir.exists())
                        self.assertIsNone(recorder.active_job)
                        self.assertEqual(recorder.capture_state, "idle")

                        manifest = recorder.archive_manifest()
                        self.assertEqual(manifest["job_count"], 1)
                        page = recorder.list_jobs("benchy", 0, 50)
                        self.assertEqual(page["total"], 1)

                        await recorder.async_stop()

        asyncio.new_event_loop().run_until_complete(run())


if __name__ == "__main__":
    unittest.main()
