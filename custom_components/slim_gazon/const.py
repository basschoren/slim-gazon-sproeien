"""Constanten voor de Slim Gazon Sproeien integratie."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.const import Platform

DOMAIN = "slim_gazon"

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.DATE,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

# Aantal geplande sproeibeurten (slots) per dag.
SLOT_COUNT = 8

# Signaal dat de coördinator stuurt wanneer er nieuwe data is.
SIGNAL_UPDATE = f"{DOMAIN}_update"

# -- Configuratie (config flow / options) -----------------------------------
# Bronentiteiten (sensoren / weer) en doelentiteiten (sproeiers).
CONF_WEATHER = "weather_entity"
CONF_TEMP = "temp_sensor"
CONF_TEMP_MAX = "temp_max_sensor"
CONF_WIND = "wind_sensor"
CONF_HUMIDITY = "humidity_sensor"
CONF_UV = "uv_sensor"
CONF_SOLAR = "solar_sensor"
CONF_RAIN_NOW = "rain_now_sensor"
CONF_RAIN_24H = "rain_24h_sensor"
CONF_RAIN_FORECAST = "rain_forecast_sensor"
CONF_DETAIL = "detail_condition_sensor"
CONF_SOIL = "soil_moisture_sensor"
CONF_BIG_SWITCH = "big_switch"
CONF_SMALL_SWITCH = "small_switch"
CONF_CALC_TIME = "calc_time"

DEFAULT_CALC_TIME = "04:00:00"
DEFAULT_NAME = "Slim Gazon"

# -- Grasfases ---------------------------------------------------------------
PHASE_NEW = "pas_ingezaaid"
PHASE_GERM = "kiemend"
PHASE_YOUNG = "jong_gras"
PHASE_ESTABLISHED = "bestaand_gras"
PHASE_MANUAL = "alleen_handmatig"
PHASES = [PHASE_NEW, PHASE_GERM, PHASE_YOUNG, PHASE_ESTABLISHED, PHASE_MANUAL]

# -- Opslagsleutels (Store) --------------------------------------------------
STORE_VERSION = 1
KEY_VALUES = "values"
KEY_PHASE = "phase"
KEY_MASTER = "master_on"
KEY_TEST = "test_mode"
KEY_SOW_DATE = "sow_date"
KEY_PLAN = "plan"
KEY_LAST_EXECUTED = "last_executed_slot"

DEFAULT_PHASE = PHASE_NEW
DEFAULT_MASTER = True
DEFAULT_TEST = True

# Vaste presets voor handmatige sproeibeurten (grote / kleine sproeier minuten).
MANUAL_SHORT = (5.0, 1.5)
MANUAL_NORMAL = (12.0, 3.0)


@dataclass(frozen=True, kw_only=True)
class NumberParam:
    """Definitie van een instelbaar getal (vervangt de input_number helpers)."""

    key: str
    name: str
    default: float
    min: float
    max: float
    step: float
    unit: str | None = None
    icon: str | None = None


# Alle instelbare parameters. Defaults komen 1-op-1 uit het oorspronkelijke
# YAML-package zodat het gedrag identiek is.
NUMBER_PARAMS: tuple[NumberParam, ...] = (
    NumberParam(
        key="sproei_factor",
        name="Sproei factor",
        default=1.0,
        min=0.2,
        max=2.0,
        step=0.1,
        icon="mdi:timer-cog-outline",
    ),
    NumberParam(
        key="grote_rate",
        name="Grote sproeier mm per minuut",
        default=0.133,
        min=0.01,
        max=5.0,
        step=0.001,
        unit="mm/min",
        icon="mdi:sprinkler-variant",
    ),
    NumberParam(
        key="kleine_rate",
        name="Kleine sproeier mm per minuut",
        default=0.667,
        min=0.01,
        max=5.0,
        step=0.001,
        unit="mm/min",
        icon="mdi:sprinkler",
    ),
    NumberParam(
        key="max_minuten_per_beurt",
        name="Max minuten per beurt",
        default=25.0,
        min=1.0,
        max=60.0,
        step=0.5,
        unit="min",
        icon="mdi:timer-alert-outline",
    ),
    NumberParam(
        key="min_pauze_minuten",
        name="Min pauze tussen beurten",
        default=180.0,
        min=30.0,
        max=480.0,
        step=15.0,
        unit="min",
        icon="mdi:timer-pause-outline",
    ),
    NumberParam(
        key="min_mm_per_beurt",
        name="Minimum mm per beurt",
        default=0.6,
        min=0.1,
        max=5.0,
        step=0.1,
        unit="mm",
        icon="mdi:water-percent",
    ),
    NumberParam(
        key="regen_negeren_onder_mm",
        name="Regen negeren onder",
        default=2.0,
        min=0.0,
        max=10.0,
        step=0.1,
        unit="mm",
        icon="mdi:weather-rainy",
    ),
    NumberParam(
        key="regen_vandaag_skip_mm",
        name="Regen vandaag overslaan vanaf",
        default=5.0,
        min=0.0,
        max=30.0,
        step=0.5,
        unit="mm",
        icon="mdi:weather-pouring",
    ),
    NumberParam(
        key="regen_24u_skip_mm",
        name="Regen laatste 24u overslaan vanaf",
        default=6.0,
        min=0.0,
        max=40.0,
        step=0.5,
        unit="mm",
        icon="mdi:weather-rainy",
    ),
    NumberParam(
        key="regen_intensiteit_stop",
        name="Stop bij regenintensiteit",
        default=0.2,
        min=0.0,
        max=10.0,
        step=0.1,
        unit="mm/h",
        icon="mdi:weather-pouring",
    ),
    NumberParam(
        key="wind_minderen_kmh",
        name="Wind verminderen vanaf",
        default=20.0,
        min=0.0,
        max=60.0,
        step=1.0,
        unit="km/h",
        icon="mdi:weather-windy",
    ),
    NumberParam(
        key="wind_stop_kmh",
        name="Wind stop vanaf",
        default=25.0,
        min=0.0,
        max=80.0,
        step=1.0,
        unit="km/h",
        icon="mdi:weather-windy-variant",
    ),
    NumberParam(
        key="temp_warm_c",
        name="Warm vanaf",
        default=24.0,
        min=10.0,
        max=40.0,
        step=0.5,
        unit="°C",
        icon="mdi:thermometer-high",
    ),
    NumberParam(
        key="temp_heet_c",
        name="Heet vanaf",
        default=29.0,
        min=15.0,
        max=45.0,
        step=0.5,
        unit="°C",
        icon="mdi:thermometer-alert",
    ),
    NumberParam(
        key="temp_extreem_heet_c",
        name="Extra heet vanaf",
        default=35.0,
        min=25.0,
        max=45.0,
        step=0.5,
        unit="°C",
        icon="mdi:sun-thermometer",
    ),
    NumberParam(
        key="rv_laag",
        name="Lage luchtvochtigheid vanaf",
        default=45.0,
        min=10.0,
        max=90.0,
        step=1.0,
        unit="%",
        icon="mdi:water-percent-alert",
    ),
    NumberParam(
        key="rv_hoog",
        name="Hoge luchtvochtigheid vanaf",
        default=80.0,
        min=10.0,
        max=100.0,
        step=1.0,
        unit="%",
        icon="mdi:water-percent",
    ),
    NumberParam(
        key="uv_hoog",
        name="Hoge UV vanaf",
        default=6.0,
        min=0.0,
        max=12.0,
        step=0.5,
        icon="mdi:white-balance-sunny",
    ),
    NumberParam(
        key="straling_hoog_wm2",
        name="Hoge globale straling vanaf",
        default=600.0,
        min=0.0,
        max=1200.0,
        step=25.0,
        unit="W/m²",
        icon="mdi:solar-power-variant",
    ),
    NumberParam(
        key="bodemvocht_nat",
        name="Bodemvocht nat drempel",
        default=45.0,
        min=0.0,
        max=100.0,
        step=1.0,
        unit="%",
        icon="mdi:water-percent",
    ),
    NumberParam(
        key="max_runtime_minuten",
        name="Veiligheid max runtime",
        default=30.0,
        min=5.0,
        max=90.0,
        step=1.0,
        unit="min",
        icon="mdi:timer-alert",
    ),
)

# Snelle opzoeklijst van defaults op sleutel.
NUMBER_DEFAULTS: dict[str, float] = {p.key: p.default for p in NUMBER_PARAMS}
