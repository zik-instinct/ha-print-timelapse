"""Config flow for Print Timelapse Archive."""

from __future__ import annotations

import logging
from typing import Any

import probatio as vol

from homeassistant.components.camera import async_get_image
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_CAMERA_ENTITY,
    CONF_CAPTURE_INTERVAL,
    CONF_FPS,
    CONF_JOB_NAME_ATTRIBUTE,
    CONF_KEEP_FRAMES,
    CONF_PRINTING_STATES,
    CONF_RESERVE_GB,
    CONF_SIDEBAR_TITLE,
    CONF_STATUS_ENTITY,
    DEFAULT_CAPTURE_INTERVAL,
    DEFAULT_FPS,
    DEFAULT_KEEP_FRAMES,
    DEFAULT_PRINTING_STATES,
    DEFAULT_RESERVE_GB,
    DEFAULT_SIDEBAR_TITLE,
    DOMAIN,
    MAX_CAPTURE_INTERVAL,
    MIN_CAPTURE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


def _options_schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_STATUS_ENTITY,
                default=defaults.get(CONF_STATUS_ENTITY),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            vol.Required(
                CONF_PRINTING_STATES,
                default=defaults.get(CONF_PRINTING_STATES, DEFAULT_PRINTING_STATES),
            ): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
            ),
            vol.Required(
                CONF_CAPTURE_INTERVAL,
                default=defaults.get(CONF_CAPTURE_INTERVAL, DEFAULT_CAPTURE_INTERVAL),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=MIN_CAPTURE_INTERVAL,
                    max=MAX_CAPTURE_INTERVAL,
                    unit_of_measurement="s",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                CONF_JOB_NAME_ATTRIBUTE,
                default=defaults.get(CONF_JOB_NAME_ATTRIBUTE) or "",
            ): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
            ),
            vol.Optional(
                CONF_SIDEBAR_TITLE,
                default=defaults.get(CONF_SIDEBAR_TITLE) or DEFAULT_SIDEBAR_TITLE,
            ): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
            ),
            vol.Optional(
                CONF_FPS,
                default=defaults.get(CONF_FPS, DEFAULT_FPS),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1, max=120, mode=selector.NumberSelectorMode.BOX
                )
            ),
            vol.Optional(
                CONF_RESERVE_GB,
                default=defaults.get(CONF_RESERVE_GB, DEFAULT_RESERVE_GB),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=100, unit_of_measurement="GB",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                CONF_KEEP_FRAMES,
                default=defaults.get(CONF_KEEP_FRAMES, DEFAULT_KEEP_FRAMES),
            ): selector.BooleanSelector(),
        }
    )


def _user_schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_CAMERA_ENTITY): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="camera")
            ),
            vol.Required(CONF_STATUS_ENTITY): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            vol.Required(
                CONF_PRINTING_STATES, default=DEFAULT_PRINTING_STATES
            ): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
            ),
            vol.Required(
                CONF_CAPTURE_INTERVAL, default=DEFAULT_CAPTURE_INTERVAL
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=MIN_CAPTURE_INTERVAL,
                    max=MAX_CAPTURE_INTERVAL,
                    unit_of_measurement="s",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(CONF_JOB_NAME_ATTRIBUTE): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
            ),
            vol.Optional(
                CONF_SIDEBAR_TITLE, default=DEFAULT_SIDEBAR_TITLE
            ): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
            ),
            vol.Optional(CONF_FPS, default=DEFAULT_FPS): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1, max=120, mode=selector.NumberSelectorMode.BOX
                )
            ),
            vol.Optional(
                CONF_RESERVE_GB, default=DEFAULT_RESERVE_GB
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=100, unit_of_measurement="GB",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                CONF_KEEP_FRAMES, default=DEFAULT_KEEP_FRAMES
            ): selector.BooleanSelector(),
        }
    )


class PrintTimelapseConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is not None:
            camera_entity = user_input[CONF_CAMERA_ENTITY]
            status_entity = user_input[CONF_STATUS_ENTITY]

            if self.hass.states.get(status_entity) is None:
                errors[CONF_STATUS_ENTITY] = "entity_not_found"
            else:
                try:
                    await async_get_image(self.hass, camera_entity, timeout=15)
                except Exception as err:
                    _LOGGER.warning("Test capture from %s failed: %s", camera_entity, err)
                    errors[CONF_CAMERA_ENTITY] = "cannot_capture"

            if not errors:
                await self.async_set_unique_id(camera_entity)
                self._abort_if_unique_id_configured()
                title = (
                    self.hass.states.get(camera_entity).name
                    if self.hass.states.get(camera_entity) is not None
                    else camera_entity
                )
                return self.async_create_entry(title=title, data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=_user_schema(), errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlow:
        return PrintTimelapseOptionsFlow()


class PrintTimelapseOptionsFlow(OptionsFlow):
    """Reconfigure capture behavior without removing the entry."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        defaults = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(
            step_id="init", data_schema=_options_schema(defaults)
        )
