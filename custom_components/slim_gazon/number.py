"""Number entiteiten: alle instelbare parameters."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import LawnConfigEntry
from .const import NUMBER_PARAMS, NumberParam
from .entity import LawnEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LawnConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Zet de number entiteiten op."""
    coordinator = entry.runtime_data
    async_add_entities(LawnNumber(coordinator, param) for param in NUMBER_PARAMS)


class LawnNumber(LawnEntity, NumberEntity):
    """Eén instelbare parameter."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator, param: NumberParam) -> None:
        """Init."""
        super().__init__(coordinator, param.key)
        self._param = param
        self._attr_name = param.name
        self._attr_native_min_value = param.min
        self._attr_native_max_value = param.max
        self._attr_native_step = param.step
        self._attr_native_unit_of_measurement = param.unit
        self._attr_icon = param.icon

    @property
    def native_value(self) -> float:
        """Huidige waarde."""
        return self.coordinator.get_value(self._param.key)

    async def async_set_native_value(self, value: float) -> None:
        """Stel een nieuwe waarde in."""
        await self.coordinator.async_set_value(self._param.key, value)
