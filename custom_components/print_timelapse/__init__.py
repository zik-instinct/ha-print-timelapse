"""Print Timelapse Archive.

Captures interval snapshots from a camera entity while a printer status
entity reports printing, assembles a timelapse video per print with ffmpeg,
and archives finished jobs with a searchable sidebar panel.
"""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .api import async_register_websocket_commands
from .const import (
    CONF_SIDEBAR_TITLE,
    DEFAULT_SIDEBAR_TITLE,
    DOMAIN,
    PANEL_ICON,
    PANEL_JS_FILE,
    PANEL_URL_PATH,
    PANEL_WEBCOMPONENT,
    SERVICE_REBUILD_INDEX,
    STATIC_URL_PATH,
)
from .recorder import TimelapseRecorder

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up domain-level pieces: WebSocket API and services."""
    hass.data.setdefault(DOMAIN, {})
    async_register_websocket_commands(hass)

    async def _async_rebuild_index(call: ServiceCall) -> None:
        for recorder in hass.data[DOMAIN].values():
            if isinstance(recorder, TimelapseRecorder):
                await recorder.async_rebuild_index()

    hass.services.async_register(DOMAIN, SERVICE_REBUILD_INDEX, _async_rebuild_index)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a configured printer."""
    recorder = TimelapseRecorder(hass, entry)
    hass.data[DOMAIN][entry.entry_id] = recorder
    await recorder.async_start()

    panel_dir = Path(__file__).parent / "www"
    await hass.http.async_register_static_paths(
        [StaticPathConfig(STATIC_URL_PATH, str(panel_dir), cache_headers=False)]
    )

    config = {**entry.data, **entry.options}
    sidebar_title = config.get(CONF_SIDEBAR_TITLE) or DEFAULT_SIDEBAR_TITLE
    try:
        await panel_custom.async_register_panel(
            hass,
            frontend_url_path=PANEL_URL_PATH,
            webcomponent_name=PANEL_WEBCOMPONENT,
            sidebar_title=sidebar_title,
            sidebar_icon=PANEL_ICON,
            module_url=f"{STATIC_URL_PATH}/{PANEL_JS_FILE}",
        )
    except ValueError as err:
        _LOGGER.warning("Could not register the sidebar panel: %s", err)

    await _async_register_card_resource(hass)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_register_card_resource(hass: HomeAssistant) -> None:
    """Register the panel/card JS as a Lovelace resource for dashboard cards.

    Only possible when Lovelace is in storage mode; YAML-mode users add the
    resource themselves (documented in the README).
    """
    try:
        from homeassistant.components.lovelace.const import LOVELACE_DATA, MODE_STORAGE
        from homeassistant.components.lovelace.resources import (
            ResourceStorageCollection,
        )
    except ImportError:
        return

    lovelace_data = hass.data.get(LOVELACE_DATA)
    if lovelace_data is None or lovelace_data.resource_mode != MODE_STORAGE:
        _LOGGER.info(
            "Lovelace storage mode not available; the dashboard card resource "
            "must be added manually: %s/%s",
            STATIC_URL_PATH,
            PANEL_JS_FILE,
        )
        return
    resources = lovelace_data.resources
    if not isinstance(resources, ResourceStorageCollection):
        return
    await resources.async_get_info()  # ensures the collection is loaded
    url = f"{STATIC_URL_PATH}/{PANEL_JS_FILE}"
    if any(item.get("url") == url for item in resources.async_items()):
        return
    await resources.async_create_item({"res_type": "module", "url": url})
    _LOGGER.debug("Registered Lovelace resource %s", url)


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a printer."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    recorder: TimelapseRecorder | None = hass.data[DOMAIN].pop(entry.entry_id, None)
    if recorder is not None:
        await recorder.async_stop()
    if not any(
        isinstance(value, TimelapseRecorder) for value in hass.data[DOMAIN].values()
    ):
        frontend.async_remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False)
    return unload_ok
