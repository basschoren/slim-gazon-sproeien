"""Button entiteiten: handmatige acties."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import LawnConfigEntry
from .const import MANUAL_NORMAL, MANUAL_SHORT
from .coordinator import LawnCoordinator
from .entity import LawnEntity


@dataclass(frozen=True, kw_only=True)
class LawnButtonDescription(ButtonEntityDescription):
    """Beschrijving van een knop met bijbehorende actie."""

    action: Callable[[LawnCoordinator], Awaitable[None]]


BUTTONS: tuple[LawnButtonDescription, ...] = (
    LawnButtonDescription(
        key="recalculate",
        name="Bereken dagplan",
        icon="mdi:calculator-variant",
        action=lambda c: c.async_calculate_plan(),
    ),
    LawnButtonDescription(
        key="stop_all",
        name="Stop alle sproeiers",
        icon="mdi:stop-circle-outline",
        action=lambda c: c.async_stop_all(),
    ),
    LawnButtonDescription(
        key="manual_short",
        name="Handmatig kort sproeien",
        icon="mdi:sprinkler",
        action=lambda c: c.async_run_cycle(
            "Handmatig korte sproeibeurt", "Handmatig kort", *MANUAL_SHORT
        ),
    ),
    LawnButtonDescription(
        key="manual_normal",
        name="Handmatig normaal sproeien",
        icon="mdi:sprinkler-variant",
        action=lambda c: c.async_run_cycle(
            "Handmatig normale sproeibeurt", "Handmatig normaal", *MANUAL_NORMAL
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LawnConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Zet de button entiteiten op."""
    coordinator = entry.runtime_data
    async_add_entities(LawnButton(coordinator, desc) for desc in BUTTONS)


class LawnButton(LawnEntity, ButtonEntity):
    """Een knop die een actie op de coördinator uitvoert."""

    entity_description: LawnButtonDescription

    def __init__(self, coordinator, description: LawnButtonDescription) -> None:
        """Init."""
        super().__init__(coordinator, description.key)
        self.entity_description = description
        self._attr_name = description.name

    async def async_press(self) -> None:
        """Voer de actie uit."""
        await self.entity_description.action(self.coordinator)
