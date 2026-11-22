"""Recording engine for Print Timelapse Archive.

Watches a printer status entity, captures interval frames from a camera
entity while the printer reports a printing state, assembles videos with
ffmpeg when the print ends, and archives the finished job.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import time
from pathlib import Path
import shutil
from typing import Any

from homeassistant.components.camera import async_get_image
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .archive import archive_job, atomic_write_json, build_index, load_index, load_names, save_names
from .const import (
    ASSEMBLED_MARKER,
    CONF_CAMERA_ENTITY,
    CONF_CAPTURE_INTERVAL,
    CONF_FPS,
    CONF_JOB_NAME_ATTRIBUTE,
    CONF_KEEP_FRAMES,
    CONF_PRINTING_STATES,
    CONF_RESERVE_GB,
    CONF_STATUS_ENTITY,
    DEFAULT_CAPTURE_INTERVAL,
    DEFAULT_FPS,
    DEFAULT_KEEP_FRAMES,
    DEFAULT_PRINTING_STATES,
    DEFAULT_RESERVE_GB,
    DOMAIN,
    MEDIA_DIR_NAME,
    RESOLUTION_HEIGHT,
    RESOLUTIONS,
    SIGNAL_ARCHIVE_UPDATED,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)

MIN_FRAMES_FOR_VIDEO = 2


class TimelapseRecorder:
    """Capture, assemble and archive timelapses for one config entry."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        config = {**entry.data, **entry.options}
        self.camera_entity: str = config[CONF_CAMERA_ENTITY]
        self.status_entity: str = config[CONF_STATUS_ENTITY]
        self.printing_states: set[str] = {
            s.strip().lower()
            for s in str(config.get(CONF_PRINTING_STATES, DEFAULT_PRINTING_STATES)).split(",")
            if s.strip()
        }
        self.capture_interval: int = int(config.get(CONF_CAPTURE_INTERVAL, DEFAULT_CAPTURE_INTERVAL))
        self.job_name_attribute: str = str(config.get(CONF_JOB_NAME_ATTRIBUTE) or "")
        self.keep_frames: bool = bool(config.get(CONF_KEEP_FRAMES, DEFAULT_KEEP_FRAMES))
        self.fps: int = int(config.get(CONF_FPS, DEFAULT_FPS))
        self.reserve_bytes: int = int(config.get(CONF_RESERVE_GB, DEFAULT_RESERVE_GB)) * 1024**3

        self.capture_root = Path(hass.config.path(DOMAIN)) / entry.entry_id
        media_dirs: dict[str, str] = getattr(hass.config, "media_dirs", {}) or {}
        self.archive_root = Path(
            media_dirs.get("local") or hass.config.path("media")
        ) / MEDIA_DIR_NAME

        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self._data: dict[str, Any] = {"next_job_id": 1, "active_job": None}
        self._unsubscribers = []
        self._assemble_lock = asyncio.Lock()
        self._capture_lock = asyncio.Lock()
        self._shutting_down = False
        self.last_error: str | None = None
        self._manifest: dict[str, Any] = {}
        self._active_frames: int = 0

    # -- lifecycle ---------------------------------------------------------

    async def async_start(self) -> None:
        """Load state, recover from restarts and start watching the printer."""
        await self.hass.async_add_executor_job(self._make_dirs)
        self._data = {**self._data, **(await self._store.async_load() or {})}

        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is None:
            self.last_error = (
                "ffmpeg was not found; videos cannot be assembled on this "
                "installation. Frames are still captured."
            )
            _LOGGER.error(self.last_error)

        active = self.active_job
        if active:
            self._active_frames = await self.hass.async_add_executor_job(
                self._count_frames, active
            )
        state = self.hass.states.get(self.status_entity)
        status_ready = state is not None and state.state not in (
            "unknown",
            "unavailable",
        )
        if active and status_ready and self._is_printing():
            _LOGGER.info("Resuming capture for %s after restart", active)
        elif active and status_ready:
            _LOGGER.info("Finalizing %s interrupted by a restart", active)
            self.hass.async_create_task(self._async_finalize_job())
        elif active:
            # The status entity has not reported yet after the restart; the
            # state listener finalizes or resumes once a real state arrives.
            _LOGGER.info(
                "Status of %s not available yet; keeping %s open",
                self.status_entity,
                active,
            )

        self._unsubscribers.append(
            async_track_state_change_event(
                self.hass, [self.status_entity], self._async_status_changed
            )
        )
        self._unsubscribers.append(
            async_track_time_interval(
                self.hass,
                self._async_capture_tick,
                datetime.timedelta(seconds=self.capture_interval),
            )
        )
        self._manifest = await self.hass.async_add_executor_job(
            load_index, self.archive_root
        ) or {}
        await self.hass.async_add_executor_job(self._rebuild_index_safe)
        _LOGGER.debug(
            "Recorder started: watching %s for %s, interval %ss",
            self.status_entity, self.printing_states, self.capture_interval,
        )
        self._notify()

    async def async_stop(self) -> None:
        """Stop watching and capturing."""
        self._shutting_down = True
        for unsub in self._unsubscribers:
            unsub()
        self._unsubscribers.clear()

    # -- job state ---------------------------------------------------------

    @property
    def active_job(self) -> str | None:
        """Directory name of the job currently being captured."""
        return self._data.get("active_job")

    @property
    def capture_state(self) -> str:
        """Human-facing capture state."""
        if self._assemble_lock.locked():
            return "assembling"
        if self.active_job:
            return "capturing"
        return "idle"

    def active_job_frames(self) -> int:
        """Number of frames captured for the active job (cached)."""
        if not self.active_job:
            return 0
        return self._active_frames

    def _is_printing(self) -> bool:
        state = self.hass.states.get(self.status_entity)
        if state is None:
            return False
        return state.state.lower() in self.printing_states

    def _job_file_name(self) -> str | None:
        if not self.job_name_attribute:
            return None
        state = self.hass.states.get(self.status_entity)
        if state is None:
            return None
        value = state.attributes.get(self.job_name_attribute)
        return str(value) if value else None

    async def _async_status_changed(
        self, event: Event[EventStateChangedData]
    ) -> None:
        new_state = event.data.get("new_state")
        printing = new_state is not None and new_state.state.lower() in self.printing_states
        _LOGGER.debug(
            "Status event: %s -> printing=%s, active_job=%s",
            new_state.state if new_state else None, printing, self.active_job,
        )
        if printing and not self.active_job:
            await self._async_begin_job()
        elif not printing and self.active_job:
            await self._async_finalize_job()
        self._notify()

    async def _async_begin_job(self) -> None:
        job_id = int(self._data.get("next_job_id", 1))
        name = f"job_{job_id}"
        (self.capture_root / name).mkdir(parents=True, exist_ok=True)
        self._data["next_job_id"] = job_id + 1
        self._data["active_job"] = name
        self._active_frames = 0
        file_name = self._job_file_name()
        if file_name:
            names = await self.hass.async_add_executor_job(load_names, self.archive_root)
            names[name] = file_name
            await self.hass.async_add_executor_job(
                save_names, self.archive_root, names
            )
        await self._store.async_save(self._data)
        _LOGGER.info("Started timelapse capture for %s", name)
        await self._async_capture_frame()

    async def _async_capture_tick(self, _now: datetime.datetime) -> None:
        if self.active_job and self._is_printing():
            await self._async_capture_frame()

    def _make_dirs(self) -> None:
        self.capture_root.mkdir(parents=True, exist_ok=True)
        self.archive_root.mkdir(parents=True, exist_ok=True)

    def _count_frames(self, job: str) -> int:
        return len(list((self.capture_root / job).glob("f_*.jpg")))

    def _save_frame(self, job_dir: Path, content: bytes) -> int:
        index = self._count_frames(job_dir.name)
        (job_dir / f"f_{index:06d}.jpg").write_bytes(content)
        return index

    async def _async_capture_frame(self) -> None:
        if self._capture_lock.locked() or self._shutting_down or not self.active_job:
            return
        async with self._capture_lock:
            job_dir = self.capture_root / self.active_job
            try:
                image = await async_get_image(self.hass, self.camera_entity, timeout=15)
            except (HomeAssistantError, asyncio.TimeoutError) as err:
                _LOGGER.debug("Frame capture failed: %s", err)
                return
            try:
                index = await self.hass.async_add_executor_job(
                    self._save_frame, job_dir, image.content
                )
            except OSError as err:
                self.last_error = f"Could not save a frame: {err}"
                _LOGGER.error(self.last_error)
                return
            self._active_frames = index + 1
            self._notify()

    # -- assembly and archival ---------------------------------------------

    async def _async_finalize_job(self) -> None:
        job = self.active_job
        if not job:
            return
        self._data["active_job"] = None
        await self._store.async_save(self._data)
        self._notify()
        async with self._assemble_lock:
            try:
                await self._async_assemble_and_archive(job)
            except Exception:  # noqa: BLE001 - a failed job must not kill capture
                _LOGGER.exception("Could not assemble/archive %s", job)
                self.last_error = f"Assembly or archival of {job} failed; see logs."
        self._notify()

    async def _async_assemble_and_archive(self, job: str) -> None:
        job_dir = self.capture_root / job
        frames = await self.hass.async_add_executor_job(
            lambda: sorted(job_dir.glob("f_*.jpg"))
        )
        if len(frames) < MIN_FRAMES_FOR_VIDEO:
            _LOGGER.info("Discarding %s: only %d frame(s)", job, len(frames))
            await self.hass.async_add_executor_job(shutil.rmtree, job_dir, True)
            return

        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is None:
            self.last_error = "ffmpeg not found; captured frames kept but not assembled."
            _LOGGER.error("%s kept on disk at %s", self.last_error, job_dir)
            return

        for res in RESOLUTIONS:
            height = RESOLUTION_HEIGHT[res]
            out = job_dir / f"timelapse_{res}.mp4"
            command = [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-framerate",
                str(self.fps),
                "-i",
                str(job_dir / "f_%06d.jpg"),
                "-vf",
                f"scale=-2:{height}",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-crf",
                "20",
                "-preset",
                "medium",
                "-movflags",
                "+faststart",
                str(out),
            ]
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await process.communicate()
            if process.returncode != 0:
                _LOGGER.error(
                    "ffmpeg failed for %s %s: %s", job, res, stderr.decode(errors="replace")[-500:]
                )
                out.unlink(missing_ok=True)
                raise HomeAssistantError(f"ffmpeg failed for {job} ({res})")

        # Marker must be written after every video is closed so nothing
        # still being written is ever archived.
        await self.hass.async_add_executor_job(
            atomic_write_json,
            job_dir / ASSEMBLED_MARKER,
            {"frames": len(frames), "ts": time.time()},
        )

        tz = dt_util.get_time_zone(self.hass.config.time_zone) or datetime.timezone.utc

        def _archive() -> None:
            names = load_names(self.archive_root)
            metadata = archive_job(
                job_dir, self.archive_root, names.get(job), tz, self.reserve_bytes
            )
            if metadata is not None:
                self._manifest = build_index(self.archive_root, tz)

        await self.hass.async_add_executor_job(_archive)

        if not self.keep_frames:
            await self.hass.async_add_executor_job(shutil.rmtree, job_dir, True)
        _LOGGER.info("Archived timelapse %s", job)

    # -- index / reporting ---------------------------------------------------

    def _rebuild_index_safe(self) -> None:
        tz = dt_util.get_time_zone(self.hass.config.time_zone) or datetime.timezone.utc
        try:
            self._manifest = build_index(self.archive_root, tz)
        except OSError as err:
            _LOGGER.error("Could not rebuild archive index: %s", err)

    async def async_rebuild_index(self) -> None:
        """Service handler: rebuild the archive index from job metadata."""
        await self.hass.async_add_executor_job(self._rebuild_index_safe)
        _LOGGER.debug(
            "Recorder started: watching %s for %s, interval %ss",
            self.status_entity, self.printing_states, self.capture_interval,
        )
        self._notify()

    def archive_manifest(self) -> dict[str, Any]:
        """Return the cached archive manifest (small version for sensors)."""
        manifest = self._manifest
        jobs = manifest.get("jobs", [])
        latest = jobs[0] if jobs else None
        return {
            "schema": manifest.get("schema"),
            "updated_at": manifest.get("updated_at"),
            "job_count": manifest.get("job_count", len(jobs)),
            "free_bytes": manifest.get("free_bytes"),
            "retention": manifest.get("retention"),
            "latest_job": (
                {
                    "job_id": latest.get("job_id"),
                    "file_name": latest.get("file_name"),
                    "assembled_at": latest.get("assembled_at"),
                }
                if latest
                else None
            ),
            "capture_state": self.capture_state,
            "last_error": self.last_error,
        }

    def list_jobs(self, query: str | None, offset: int, limit: int) -> dict[str, Any]:
        """Return a page of archived jobs for the frontend panel."""
        manifest = self._manifest or {"jobs": []}
        jobs = manifest.get("jobs", [])
        if query:
            needle = query.lower()
            jobs = [
                job
                for job in jobs
                if needle in f"job {job.get('job_id')} {job.get('file_name') or ''}".lower()
            ]
        return {
            "schema": manifest.get("schema"),
            "updated_at": manifest.get("updated_at"),
            "free_bytes": manifest.get("free_bytes"),
            "retention": manifest.get("retention"),
            "total": len(jobs),
            "offset": offset,
            "jobs": jobs[offset : offset + limit],
        }

    @callback
    def _notify(self) -> None:
        async_dispatcher_send(
            self.hass, SIGNAL_ARCHIVE_UPDATED.format(self.entry.entry_id)
        )
