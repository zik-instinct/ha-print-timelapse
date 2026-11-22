"""Sensors for Print Timelapse Archive."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SIGNAL_ARCHIVE_UPDATED
from .recorder import TimelapseRecorder


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the archive and capture sensors."""
    recorder: TimelapseRecorder = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [PrintTimelapseArchiveSensor(recorder), PrintTimelapseCaptureSensor(recorder)]
    )


class _BaseSensor(SensorEntity):
    """Shared update wiring."""

    _attr_has_entity_name = True

    def __init__(self, recorder: TimelapseRecorder) -> None:
        self._recorder = recorder

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_ARCHIVE_UPDATED.format(self._recorder.entry.entry_id),
                self._handle_update,
            )
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

    @property
    def device_info(self) -> dict[str, Any]:
        return {
            "identifiers": {(DOMAIN, self._recorder.entry.entry_id)},
            "name": self._recorder.entry.title,
        }


class PrintTimelapseArchiveSensor(_BaseSensor):
    """Archive summary: state is the number of saved prints."""

    _attr_name = "Archive"
    _attr_icon = "mdi:video-vintage"

    def __init__(self, recorder: TimelapseRecorder) -> None:
        super().__init__(recorder)
        self._attr_unique_id = f"{recorder.entry.entry_id}_archive"

    @property
    def native_value(self) -> int:
        manifest = self._recorder.archive_manifest()
        return int(manifest.get("job_count") or 0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self._recorder.archive_manifest()


class PrintTimelapseCaptureSensor(_BaseSensor):
    """Live capture state: idle, capturing or assembling."""

    _attr_name = "Capture"
    _attr_icon = "mdi:record-rec"

    def __init__(self, recorder: TimelapseRecorder) -> None:
        super().__init__(recorder)
        self._attr_unique_id = f"{recorder.entry.entry_id}_capture"

    @property
    def native_value(self) -> str:
        return self._recorder.capture_state

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        recorder = self._recorder
        return {
            "active_job": recorder.active_job,
            "active_job_frames": recorder.active_job_frames(),
            "camera_entity": recorder.camera_entity,
            "status_entity": recorder.status_entity,
            "capture_interval": recorder.capture_interval,
            "last_error": recorder.last_error,
        }
