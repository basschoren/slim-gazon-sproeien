"""Date entiteit: de zaaidatum."""

from __future__ import annotations

from datetime import date

from homeassistant.components.date import DateEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import LawnConfigEntry
from .entity import LawnEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LawnConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Zet de date entiteit op."""
    async_add_entities([SowDate(entry.runtime_data)])


class SowDate(LawnEntity, DateEntity):
    """Zaaidatum van het gazon (bepaalt het fase-advies)."""

    _attr_name = "Zaaidatum"
    _attr_icon = "mdi:calendar-start"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator) -> None:
        """Init."""
        super().__init__(coordinator, "sow_date")

    @property
    def native_value(self) -> date | None:
        """Huidige zaaidatum."""
        if not self.coordinator.sow_date:
            return None
        return dt_util.parse_date(self.coordinator.sow_date)

    async def async_set_value(self, value: date) -> None:
        """Stel de zaaidatum in."""
        await self.coordinator.async_set_sow_date(value.isoformat())
