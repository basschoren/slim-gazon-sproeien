"""Select entiteit: de grasfase."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import LawnConfigEntry
from .const import PHASES
from .entity import LawnEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LawnConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Zet de select entiteit op."""
    async_add_entities([LawnPhaseSelect(entry.runtime_data)])


class LawnPhaseSelect(LawnEntity, SelectEntity):
    """Keuze van de grasfase."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:grass"
    _attr_name = "Gazon fase"
    _attr_options = PHASES
    _attr_translation_key = "fase"

    def __init__(self, coordinator) -> None:
        """Init."""
        super().__init__(coordinator, "fase")

    @property
    def current_option(self) -> str:
        """Huidige fase."""
        return self.coordinator.phase

    async def async_select_option(self, option: str) -> None:
        """Wijzig de fase."""
        await self.coordinator.async_set_phase(option)
