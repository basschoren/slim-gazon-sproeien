"""Switch entiteiten: master-schakelaar en testmodus."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import LawnConfigEntry
from .entity import LawnEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LawnConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Zet de switch entiteiten op."""
    coordinator = entry.runtime_data
    async_add_entities([MasterSwitch(coordinator), TestModeSwitch(coordinator)])


class MasterSwitch(LawnEntity, SwitchEntity):
    """Hoofdschakelaar voor automatisch sproeien."""

    _attr_name = "Automatisch sproeien"
    _attr_icon = "mdi:sprinkler"

    def __init__(self, coordinator) -> None:
        """Init."""
        super().__init__(coordinator, "master")

    @property
    def is_on(self) -> bool:
        """Of automatisch sproeien aan staat."""
        return self.coordinator.master_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Zet aan."""
        await self.coordinator.async_set_master(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Zet uit."""
        await self.coordinator.async_set_master(False)


class TestModeSwitch(LawnEntity, SwitchEntity):
    """Testmodus: berekent en plant alles maar schakelt geen echte sproeiers."""

    _attr_name = "Testmodus (dry-run)"
    _attr_icon = "mdi:test-tube"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator) -> None:
        """Init."""
        super().__init__(coordinator, "test_mode")

    @property
    def is_on(self) -> bool:
        """Of testmodus aan staat."""
        return self.coordinator.test_mode

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Zet testmodus aan."""
        await self.coordinator.async_set_test_mode(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Zet testmodus uit."""
        await self.coordinator.async_set_test_mode(False)
