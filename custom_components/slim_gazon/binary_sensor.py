"""Binary sensor: sproeibeurt bezig."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import LawnConfigEntry
from .entity import LawnEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LawnConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Zet de binary sensor op."""
    async_add_entities([BusyBinarySensor(entry.runtime_data)])


class BusyBinarySensor(LawnEntity, BinarySensorEntity):
    """Geeft aan of er op dit moment gesproeid wordt."""

    _attr_name = "Sproeien bezig"
    _attr_icon = "mdi:sprinkler-variant"
    _attr_device_class = BinarySensorDeviceClass.RUNNING

    def __init__(self, coordinator) -> None:
        """Init."""
        super().__init__(coordinator, "busy")

    @property
    def is_on(self) -> bool:
        """Of er gesproeid wordt."""
        return self.coordinator.busy
