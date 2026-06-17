"""Config flow voor Slim Gazon Sproeien."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_BIG_SWITCH,
    CONF_CALC_TIME,
    CONF_DETAIL,
    CONF_HUMIDITY,
    CONF_RAIN_24H,
    CONF_RAIN_DATA,
    CONF_RAIN_FORECAST,
    CONF_RAIN_NOW,
    CONF_SMALL_SWITCH,
    CONF_SOIL,
    CONF_SOLAR,
    CONF_TEMP,
    CONF_TEMP_MAX,
    CONF_UV,
    CONF_WEATHER,
    CONF_WIND,
    DEFAULT_CALC_TIME,
    DEFAULT_NAME,
    DOMAIN,
)

# Domeinen die als sproeier gebruikt kunnen worden.
SWITCH_DOMAINS = ["switch", "input_boolean", "light", "valve"]


def _entity(domain) -> selector.EntitySelector:
    return selector.EntitySelector(selector.EntitySelectorConfig(domain=domain))


def _base_schema() -> dict:
    """Velden voor zowel de setup als de opties."""
    return {
        vol.Required(CONF_WEATHER): _entity("weather"),
        vol.Required(CONF_TEMP): _entity("sensor"),
        vol.Required(CONF_BIG_SWITCH): _entity(SWITCH_DOMAINS),
        vol.Required(CONF_SMALL_SWITCH): _entity(SWITCH_DOMAINS),
        vol.Optional(CONF_TEMP_MAX): _entity("sensor"),
        vol.Optional(CONF_WIND): _entity("sensor"),
        vol.Optional(CONF_HUMIDITY): _entity("sensor"),
        vol.Optional(CONF_UV): _entity("sensor"),
        vol.Optional(CONF_SOLAR): _entity("sensor"),
        vol.Optional(CONF_RAIN_NOW): _entity("sensor"),
        vol.Optional(CONF_RAIN_24H): _entity("sensor"),
        vol.Optional(CONF_RAIN_FORECAST): _entity("sensor"),
        vol.Optional(CONF_RAIN_DATA): _entity("sensor"),
        vol.Optional(CONF_DETAIL): _entity("sensor"),
        vol.Optional(CONF_SOIL): _entity("sensor"),
        vol.Optional(CONF_CALC_TIME, default=DEFAULT_CALC_TIME): selector.TimeSelector(),
    }


class SlimGazonConfigFlow(ConfigFlow, domain=DOMAIN):
    """Setup van een nieuwe gazon-zone."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Eerste stap."""
        if user_input is not None:
            name = user_input.pop(CONF_NAME, DEFAULT_NAME)
            return self.async_create_entry(title=name, data=user_input)

        schema = vol.Schema(
            {vol.Required(CONF_NAME, default=DEFAULT_NAME): str, **_base_schema()}
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlow:
        """Opties flow."""
        return SlimGazonOptionsFlow()


class SlimGazonOptionsFlow(OptionsFlow):
    """Aanpassen van de gekozen entiteiten en berekentijd."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Toon en bewaar de opties."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = dict(self.config_entry.options) or dict(self.config_entry.data)
        current.pop(CONF_NAME, None)
        schema = self.add_suggested_values_to_schema(vol.Schema(_base_schema()), current)
        return self.async_show_form(step_id="init", data_schema=schema)
