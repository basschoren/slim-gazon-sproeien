"""Sensor entiteiten: dagplan en status."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.util import dt as dt_util

from . import LawnConfigEntry
from .const import CONF_RAIN_DATA
from .coordinator import LawnCoordinator
from .entity import LawnEntity


def _plan(coordinator: LawnCoordinator, key: str, default=None):
    return (coordinator.plan or {}).get(key, default)


def _nowcast_state(coordinator: LawnCoordinator):
    summary = coordinator.nowcast_summary()
    return None if summary is None else summary["window_mm"]


def _nowcast_attributes(coordinator: LawnCoordinator) -> dict | None:
    summary = coordinator.nowcast_summary()
    if summary is None:
        return None
    return {
        "minuten_tot_regen": summary["minutes_until_rain"],
        "horizon_minuten": summary["horizon_min"],
        "voor_de_middag_mm": summary["before_noon_mm"],
        "vandaag_mm": summary["today_mm"],
    }


def _last_calc(coordinator: LawnCoordinator) -> datetime | None:
    raw = _plan(coordinator, "calculated_at")
    return dt_util.parse_datetime(raw) if raw else None


def _plan_attributes(coordinator: LawnCoordinator) -> dict:
    plan = coordinator.plan or {}
    active = [s for s in plan.get("slots", []) if s.get("active")]
    return {
        "reden": plan.get("reason"),
        "temperatuur_range": plan.get("temp_range"),
        "waarschuwingen": plan.get("warnings"),
        "totaal_mm": plan.get("total_mm"),
        "aantal_beurten": plan.get("aantal_beurten"),
        "mm_per_beurt": plan.get("mm_per_beurt"),
        "grote_minuten_per_beurt": plan.get("big_minutes_per_beat"),
        "kleine_minuten_per_beurt": plan.get("small_minutes_per_beat"),
        "slots": active,
        "meetwaarden": plan.get("inputs"),
        "berekend_op": plan.get("calculated_at"),
    }


@dataclass(frozen=True, kw_only=True)
class LawnSensorDescription(SensorEntityDescription):
    """Beschrijving van een sensor met waarde- en attribuutfunctie."""

    value_fn: Callable[[LawnCoordinator], StateType | datetime]
    attr_fn: Callable[[LawnCoordinator], dict] | None = None


SENSORS: tuple[LawnSensorDescription, ...] = (
    LawnSensorDescription(
        key="status",
        name="Status",
        icon="mdi:sprinkler-variant",
        value_fn=lambda c: c.status(),
    ),
    LawnSensorDescription(
        key="plan",
        name="Dagplan",
        icon="mdi:calendar-text",
        value_fn=lambda c: _plan(c, "summary", "Nog geen dagplan berekend."),
        attr_fn=_plan_attributes,
    ),
    LawnSensorDescription(
        key="reason",
        name="Dagplan reden",
        icon="mdi:text-box-check-outline",
        value_fn=lambda c: _plan(c, "reason", ""),
    ),
    LawnSensorDescription(
        key="temp_range",
        name="Temperatuur range",
        icon="mdi:thermometer-lines",
        value_fn=lambda c: _plan(c, "temp_range", ""),
    ),
    LawnSensorDescription(
        key="total_mm",
        name="Gepland totaal mm",
        icon="mdi:water",
        native_unit_of_measurement="mm",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: _plan(c, "total_mm"),
    ),
    LawnSensorDescription(
        key="netto_mm",
        name="Netto behoefte mm",
        icon="mdi:water-outline",
        native_unit_of_measurement="mm",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: _plan(c, "netto_mm"),
    ),
    LawnSensorDescription(
        key="water_deficit",
        name="Watertekort",
        icon="mdi:water-minus",
        native_unit_of_measurement="mm",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: c.water_deficit(),
    ),
    LawnSensorDescription(
        key="toplaag_risico",
        name="Toplaag uitdroogrisico",
        icon="mdi:water-alert-outline",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: _plan(c, "dry_risk"),
    ),
    LawnSensorDescription(
        key="regen_credit",
        name="Regen credit",
        icon="mdi:weather-rainy",
        native_unit_of_measurement="mm",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: _plan(c, "rain_credit"),
    ),
    LawnSensorDescription(
        key="laatste_beslissing",
        name="Laatste beslissing",
        icon="mdi:message-text-outline",
        value_fn=lambda c: (_plan(c, "decision") or _plan(c, "reason", ""))[:255],
    ),
    LawnSensorDescription(
        key="big_minutes_total",
        name="Geplande grote sproeier minuten",
        icon="mdi:sprinkler-variant",
        native_unit_of_measurement="min",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: _plan(c, "big_minutes_total"),
    ),
    LawnSensorDescription(
        key="small_minutes_total",
        name="Geplande kleine sproeier minuten",
        icon="mdi:sprinkler",
        native_unit_of_measurement="min",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: _plan(c, "small_minutes_total"),
    ),
    LawnSensorDescription(
        key="next_run",
        name="Eerstvolgende beurt",
        icon="mdi:calendar-clock",
        value_fn=lambda c: c.next_run(),
    ),
    LawnSensorDescription(
        key="advised_phase",
        name="Geadviseerde fase",
        icon="mdi:grass",
        value_fn=lambda c: c.advised_phase(),
    ),
    LawnSensorDescription(
        key="last_calculation",
        name="Laatste berekening",
        icon="mdi:clock-check-outline",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_last_calc,
    ),
)

# Alleen toegevoegd wanneer er een nowcast-sensor is geconfigureerd.
NOWCAST_SENSOR = LawnSensorDescription(
    key="rain_nowcast",
    name="Regen nowcast (komend)",
    icon="mdi:weather-pouring",
    native_unit_of_measurement="mm",
    state_class=SensorStateClass.MEASUREMENT,
    value_fn=_nowcast_state,
    attr_fn=_nowcast_attributes,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LawnConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Zet de sensor entiteiten op."""
    coordinator = entry.runtime_data
    descriptions = list(SENSORS)
    if coordinator.conf(CONF_RAIN_DATA):
        descriptions.append(NOWCAST_SENSOR)
    async_add_entities(LawnSensor(coordinator, desc) for desc in descriptions)


class LawnSensor(LawnEntity, SensorEntity):
    """Een sensor afgeleid van het dagplan of de status."""

    entity_description: LawnSensorDescription

    def __init__(self, coordinator, description: LawnSensorDescription) -> None:
        """Init."""
        super().__init__(coordinator, description.key)
        self.entity_description = description
        self._attr_name = description.name

    @property
    def native_value(self) -> StateType | datetime:
        """Huidige waarde."""
        return self.entity_description.value_fn(self.coordinator)

    @property
    def extra_state_attributes(self) -> dict | None:
        """Extra attributen (bijv. de slots)."""
        if self.entity_description.attr_fn is None:
            return None
        return self.entity_description.attr_fn(self.coordinator)
