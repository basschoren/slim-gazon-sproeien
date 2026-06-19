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
CONF_RAIN_DATA = "rain_data_sensor"
CONF_DETAIL = "detail_condition_sensor"
CONF_SOIL = "soil_moisture_sensor"
CONF_BIG_SWITCH = "big_switch"
CONF_SMALL_SWITCH = "small_switch"
CONF_CALC_TIME = "calc_time"
CONF_EXTRA_CALC_TIMES = "extra_calc_times"

DEFAULT_CALC_TIME = "04:00:00"
DEFAULT_NAME = "Slim Gazon"

# Extra herberekeningen overdag (naast de hoofdtijd, standaard 04:00). Zo blijven
# UV/straling/temperatuur en de nowcast-regen actueel en past het plan zich aan
# de werkelijke dag aan. Tijden bewust naast de sproeislots gekozen. Instelbaar
# via de UI; een lege lijst betekent geen extra herberekeningen.
DEFAULT_EXTRA_CALC_TIMES: list[str] = ["07:00", "11:00", "13:30", "16:00"]

# Vanaf welke intensiteit (mm/h) we "het gaat regenen" rekenen in de nowcast.
NOWCAST_ONSET_MMH = 0.1

# -- Grasfases ---------------------------------------------------------------
PHASE_NEW = "pas_ingezaaid"
PHASE_GERM = "kiemend"
PHASE_YOUNG = "jong_gras"
PHASE_PREMOW = "rond_eerste_maaibeurt"
PHASE_ESTABLISHED = "bestaand_gras"
PHASE_MANUAL = "alleen_handmatig"
PHASES = [
    PHASE_NEW,
    PHASE_GERM,
    PHASE_YOUNG,
    PHASE_PREMOW,
    PHASE_ESTABLISHED,
    PHASE_MANUAL,
]

# -- Sproeiadvies (zonnige dag) ----------------------------------------------
# Bron: `sproeiadvies_gazon_temperatuurklassen.xlsx` (blad "Advies"). Het is een
# 2D-tabel temperatuurklasse (10..40 °C) × grasstadium voor een zonnige zuidtuin
# zonder regen. Per cel: de gemiddelde dagbehoefte (mm/dag), de adviesdiepte per
# beurt (mm), of het advies "per week" is (diep & weinig) en de aanbevolen
# momenten. De planner gebruikt dit als basis en past het aan met de sensoren
# (zon/bewolking, luchtvochtigheid, wind, regen, bodemvocht) via een lopende
# waterbalans.
ADVICE_TEMPS: tuple[int, ...] = (10, 15, 20, 25, 30, 35, 40)


@dataclass(frozen=True, kw_only=True)
class AdviceCell:
    """Eén advies-cel uit de tabel (temperatuurklasse × stadium)."""

    daily_need: float  # gemiddelde behoefte mm/dag op een zonnige dag
    depth: float  # adviesdiepte per beurt (mm)
    per_week: bool  # True = diep & weinig (per week), False = (meerdere) per dag
    times: tuple[str, ...]  # aanbevolen momenten ("HH:MM")


# Per-week stadia krijgen één diepe ochtendbeurt; de frequentie volgt vanzelf
# uit de waterbalans (hoe snel het tekort de adviesdiepte bereikt).
_MORNING: tuple[str, ...] = ("06:00",)

ADVICE: dict[str, dict[int, AdviceCell]] = {
    PHASE_NEW: {
        10: AdviceCell(daily_need=2.0, depth=1.0, per_week=False, times=("08:00", "14:00")),
        15: AdviceCell(daily_need=2.4, depth=1.2, per_week=False, times=("07:00", "14:00")),
        20: AdviceCell(daily_need=3.9, depth=1.3, per_week=False, times=("06:30", "12:00", "16:00")),
        25: AdviceCell(daily_need=6.0, depth=1.5, per_week=False, times=("06:00", "11:00", "15:00", "18:00")),
        30: AdviceCell(daily_need=8.5, depth=1.7, per_week=False, times=("06:00", "09:30", "12:30", "15:30", "18:00")),
        35: AdviceCell(daily_need=10.8, depth=1.8, per_week=False, times=("06:00", "09:00", "11:30", "14:00", "16:30", "18:30")),
        40: AdviceCell(daily_need=14.0, depth=2.0, per_week=False, times=("06:00", "08:30", "11:00", "13:30", "16:00", "18:00", "20:00")),
    },
    PHASE_GERM: {
        10: AdviceCell(daily_need=1.5, depth=1.5, per_week=False, times=("08:00",)),
        15: AdviceCell(daily_need=4.0, depth=2.0, per_week=False, times=("07:00", "15:00")),
        20: AdviceCell(daily_need=4.4, depth=2.2, per_week=False, times=("06:30", "15:30")),
        25: AdviceCell(daily_need=5.0, depth=2.5, per_week=False, times=("06:00", "16:00")),
        30: AdviceCell(daily_need=7.5, depth=2.5, per_week=False, times=("06:00", "12:30", "17:00")),
        35: AdviceCell(daily_need=12.0, depth=3.0, per_week=False, times=("06:00", "11:00", "15:00", "18:30")),
        40: AdviceCell(daily_need=12.0, depth=3.0, per_week=False, times=("06:00", "10:30", "15:00", "19:00")),
    },
    PHASE_YOUNG: {
        10: AdviceCell(daily_need=1.71, depth=4.0, per_week=True, times=_MORNING),
        15: AdviceCell(daily_need=2.57, depth=4.5, per_week=True, times=_MORNING),
        20: AdviceCell(daily_need=4.5, depth=4.5, per_week=False, times=("06:30",)),
        25: AdviceCell(daily_need=5.0, depth=5.0, per_week=False, times=("06:00",)),
        30: AdviceCell(daily_need=6.0, depth=6.0, per_week=False, times=("06:00",)),
        35: AdviceCell(daily_need=11.0, depth=5.5, per_week=False, times=("06:00", "18:00")),
        40: AdviceCell(daily_need=10.0, depth=5.0, per_week=False, times=("06:00", "18:30")),
    },
    PHASE_PREMOW: {
        10: AdviceCell(daily_need=2.29, depth=8.0, per_week=True, times=_MORNING),
        15: AdviceCell(daily_need=2.57, depth=9.0, per_week=True, times=_MORNING),
        20: AdviceCell(daily_need=3.86, depth=9.0, per_week=True, times=_MORNING),
        25: AdviceCell(daily_need=4.29, depth=10.0, per_week=True, times=_MORNING),
        30: AdviceCell(daily_need=4.71, depth=11.0, per_week=True, times=_MORNING),
        35: AdviceCell(daily_need=6.29, depth=11.0, per_week=True, times=_MORNING),
        40: AdviceCell(daily_need=6.86, depth=12.0, per_week=True, times=_MORNING),
    },
    PHASE_ESTABLISHED: {
        10: AdviceCell(daily_need=1.43, depth=10.0, per_week=True, times=_MORNING),
        15: AdviceCell(daily_need=1.71, depth=12.0, per_week=True, times=_MORNING),
        20: AdviceCell(daily_need=2.86, depth=10.0, per_week=True, times=_MORNING),
        25: AdviceCell(daily_need=3.43, depth=12.0, per_week=True, times=_MORNING),
        30: AdviceCell(daily_need=4.71, depth=11.0, per_week=True, times=_MORNING),
        35: AdviceCell(daily_need=5.14, depth=12.0, per_week=True, times=_MORNING),
        40: AdviceCell(daily_need=7.14, depth=12.5, per_week=True, times=_MORNING),
    },
}

# -- Opslagsleutels (Store) --------------------------------------------------
STORE_VERSION = 1
KEY_VALUES = "values"
KEY_PHASE = "phase"
KEY_MASTER = "master_on"
KEY_TEST = "test_mode"
KEY_SOW_DATE = "sow_date"
KEY_PLAN = "plan"
KEY_LAST_EXECUTED = "last_executed_slot"
# Waterbalans (lopend tekort) — kern van het slimme advies.
KEY_WB_DATE = "wb_date"  # datum waarvoor de balans-velden gelden
KEY_WB_CARRY = "wb_carry"  # tekort dat deze dag in ging (mm)
KEY_WB_NEED = "wb_need"  # laatst berekende dagbehoefte (mm)
KEY_WB_RAIN = "wb_rain"  # laatst berekende regen-aftrek (mm)
KEY_WB_APPLIED = "wb_applied"  # vandaag daadwerkelijk gegeven water (mm)

# Maximaal opgebouwd tekort (mm). Voorkomt dat een lange test/uit-periode een
# enorme inhaalslag oplevert zodra er weer gesproeid mag worden.
WB_MAX_CARRY = 30.0

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
        default=0.5,
        min=0.01,
        max=5.0,
        step=0.001,
        unit="mm/min",
        icon="mdi:sprinkler",
    ),
    NumberParam(
        key="max_minuten_per_beurt",
        name="Max minuten per beurt",
        default=95.0,
        min=1.0,
        max=120.0,
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
        default=100.0,
        min=5.0,
        max=180.0,
        step=1.0,
        unit="min",
        icon="mdi:timer-alert",
    ),
    NumberParam(
        key="toplaag_risico_drempel",
        name="Toplaag risico drempel",
        default=50.0,
        min=0.0,
        max=100.0,
        step=5.0,
        unit="%",
        icon="mdi:water-alert-outline",
    ),
    NumberParam(
        key="max_beurten_per_dag",
        name="Max sproeibeurten per dag",
        default=4.0,
        min=1.0,
        max=8.0,
        step=1.0,
        icon="mdi:counter",
    ),
    NumberParam(
        key="regen_binnen_minuten",
        name="Uitstellen bij regen binnen",
        default=90.0,
        min=0.0,
        max=180.0,
        step=15.0,
        unit="min",
        icon="mdi:weather-rainy",
    ),
    NumberParam(
        key="min_regen_voor_overslaan",
        name="Min. regen om beurt over te slaan",
        default=3.0,
        min=0.0,
        max=20.0,
        step=0.5,
        unit="mm",
        icon="mdi:weather-pouring",
    ),
)

# Snelle opzoeklijst van defaults op sleutel.
NUMBER_DEFAULTS: dict[str, float] = {p.key: p.default for p in NUMBER_PARAMS}
