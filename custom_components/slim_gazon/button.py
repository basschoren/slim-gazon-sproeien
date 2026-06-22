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
    # (grote_minuten, kleine_minuten) voor een handmatige sproeipreset. Wordt
    # gebruikt om als attribuut te tonen hoeveel water en hoelang er gegeven
    # wordt. None = de knop is geen sproeibeurt.
    preset: tuple[float, float] | None = None


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
        preset=MANUAL_SHORT,
        action=lambda c: c.async_run_cycle(
            "Handmatig korte sproeibeurt", "Handmatig kort", *MANUAL_SHORT, manual=True
        ),
    ),
    LawnButtonDescription(
        key="manual_normal",
        name="Handmatig normaal sproeien",
        icon="mdi:sprinkler-variant",
        preset=MANUAL_NORMAL,
        action=lambda c: c.async_run_cycle(
            "Handmatig normale sproeibeurt", "Handmatig normaal", *MANUAL_NORMAL, manual=True
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

    @property
    def extra_state_attributes(self) -> dict | None:
        """Toon bij een sproeipreset hoeveel water en hoelang er gegeven wordt.

        De minuten liggen vast (de preset); de mm volgen live uit de ingestelde
        sproeisnelheden. De grote en kleine sproeier lopen ná elkaar, dus de mm
        gelden per zone (niet bij elkaar op te tellen).
        """
        preset = self.entity_description.preset
        if preset is None:
            return None
        big_min, small_min = preset
        grote_mm = round(big_min * self.coordinator.get_value("grote_rate"), 1)
        kleine_mm = round(small_min * self.coordinator.get_value("kleine_rate"), 1)
        return {
            "grote_sproeier_minuten": big_min,
            "kleine_sproeier_minuten": small_min,
            "grote_zone_mm": grote_mm,
            "kleine_zone_mm": kleine_mm,
            "totale_looptijd_minuten": round(big_min + small_min, 1),
            "omschrijving": (
                f"Grote sproeier {big_min:g} min (~{grote_mm:g} mm), "
                f"kleine sproeier {small_min:g} min (~{kleine_mm:g} mm); "
                f"na elkaar, samen ~{big_min + small_min:g} min sproeitijd"
            ),
        }

    async def async_press(self) -> None:
        """Voer de actie uit."""
        await self.entity_description.action(self.coordinator)
