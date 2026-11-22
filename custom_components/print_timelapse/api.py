"""WebSocket API for the Print Timelapse Archive panel."""

from __future__ import annotations

from typing import Any

import probatio as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from .const import DOMAIN, MEDIA_DIR_NAME, WS_TYPE_JOB, WS_TYPE_LIST
from .recorder import TimelapseRecorder

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


def async_register_websocket_commands(hass: HomeAssistant) -> None:
    """Register the panel's WebSocket commands once per instance."""
    websocket_api.async_register_command(hass, websocket_list_jobs)
    websocket_api.async_register_command(hass, websocket_get_job)


def _first_recorder(hass: HomeAssistant) -> TimelapseRecorder | None:
    recorders = hass.data.get(DOMAIN, {})
    return next(iter(recorders.values()), None)


@websocket_api.websocket_command(
    {
        vol.Required("type"): WS_TYPE_LIST,
        vol.Optional("query"): str,
        vol.Optional("offset", default=0): int,
        vol.Optional("limit", default=DEFAULT_PAGE_SIZE): int,
    }
)
@websocket_api.async_response
async def websocket_list_jobs(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """List archived jobs, optionally filtered by a search query."""
    recorder = _first_recorder(hass)
    if recorder is None:
        connection.send_error(msg["id"], "not_configured", "Integration is not set up")
        return
    limit = min(int(msg.get("limit", DEFAULT_PAGE_SIZE)), MAX_PAGE_SIZE)
    result = recorder.list_jobs(
        query=msg.get("query"), offset=int(msg.get("offset", 0)), limit=limit
    )
    result["media_prefix"] = MEDIA_DIR_NAME
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {
        vol.Required("type"): WS_TYPE_JOB,
        vol.Required("job_id"): int,
    }
)
@websocket_api.async_response
async def websocket_get_job(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return metadata for one archived job."""
    recorder = _first_recorder(hass)
    if recorder is None:
        connection.send_error(msg["id"], "not_configured", "Integration is not set up")
        return
    result = recorder.list_jobs(query=None, offset=0, limit=MAX_PAGE_SIZE)
    for job in result["jobs"]:
        if job["job_id"] == msg["job_id"]:
            connection.send_result(msg["id"], job)
            return
    connection.send_error(msg["id"], "not_found", "Unknown job")
