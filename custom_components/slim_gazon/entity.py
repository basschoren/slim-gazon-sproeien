"""Gedeelde basisklasse voor alle Slim Gazon entiteiten."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, SIGNAL_UPDATE
from .coordinator import LawnCoordinator


class LawnEntity(Entity):
    """Basisklasse die de coördinator-updates volgt."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator: LawnCoordinator, key: str) -> None:
        """Init."""
        self.coordinator = coordinator
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name=coordinator.entry.title,
            manufacturer="Slim Gazon",
            model="Slim Gazon Sproeien",
        )

    async def async_added_to_hass(self) -> None:
        """Abonneer op updates van de coördinator."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{SIGNAL_UPDATE}_{self.coordinator.entry.entry_id}",
                self.async_write_ha_state,
            )
        )
