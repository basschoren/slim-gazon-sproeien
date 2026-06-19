"""De Slim Gazon Sproeien integratie."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN, MANUAL_NORMAL, MANUAL_SHORT, PHASES, PLATFORMS
from .coordinator import LawnCoordinator

type LawnConfigEntry = ConfigEntry[LawnCoordinator]

SERVICE_CALCULATE_PLAN = "calculate_plan"
SERVICE_RUN_CYCLE = "run_cycle"
SERVICE_START_BIG = "start_big"
SERVICE_START_SMALL = "start_small"
SERVICE_MANUAL_SHORT = "manual_short"
SERVICE_MANUAL_NORMAL = "manual_normal"
SERVICE_STOP_ALL = "stop_all"
SERVICE_TEST_SCENARIO = "test_scenario"

SCENARIOS = [
    "10c_geen_regen",
    "15c_geen_regen",
    "20c_geen_regen",
    "25c_geen_regen",
    "30c_geen_regen",
    "35c_geen_regen",
    "40c_geen_regen",
    "30c_5mm_regen_verwacht",
    "30c_5mm_regen_24u",
    "35c_harde_wind",
    "25c_bestaand_gras",
    "30c_rond_maaibeurt",
    "s1_volgroeid_8mm_zon",
    "s2_net_ingezaaid_8mm_heet",
    "s3_kiemend_4mm_heet_wind",
    "s4_net_ingezaaid_regen_komt",
    "s5_jong_5mm_halfbewolkt",
    "automatisering_uit",
    "sensoren_onbekend",
]

_MINUTES = vol.All(vol.Coerce(float), vol.Range(min=0, max=60))

CALC_PLAN_SCHEMA = vol.Schema(
    {
        vol.Optional("test_fase"): vol.In(PHASES),
        vol.Optional("test_temp_max"): vol.Coerce(float),
        vol.Optional("test_regen_vandaag"): vol.Coerce(float),
        vol.Optional("test_regen_24u"): vol.Coerce(float),
        vol.Optional("test_wind"): vol.Coerce(float),
        vol.Optional("test_automatisering_aan"): cv.boolean,
    }
)

RUN_CYCLE_SCHEMA = vol.Schema(
    {
        vol.Required("big_minutes"): _MINUTES,
        vol.Required("small_minutes"): _MINUTES,
        vol.Optional("reason", default="Handmatige sproeibeurt"): cv.string,
        vol.Optional("slot", default="Handmatig"): cv.string,
        vol.Optional("force_test", default=False): cv.boolean,
    }
)

MINUTES_SCHEMA = vol.Schema({vol.Required("minutes"): _MINUTES})

TEST_SCENARIO_SCHEMA = vol.Schema({vol.Required("scenario"): vol.In(SCENARIOS)})


def _loaded_coordinators(hass: HomeAssistant) -> list[LawnCoordinator]:
    """Alle geladen zones."""
    return [
        entry.runtime_data
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED
    ]


async def async_setup_entry(hass: HomeAssistant, entry: LawnConfigEntry) -> bool:
    """Zet een config entry op."""
    coordinator = LawnCoordinator(hass, entry)
    await coordinator.async_load()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    _async_register_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: LawnConfigEntry) -> bool:
    """Verwijder een config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.async_unload()

    # Verwijder services als dit de laatste zone was.
    remaining = [
        e
        for e in hass.config_entries.async_entries(DOMAIN)
        if e.entry_id != entry.entry_id
    ]
    if not remaining:
        for service in (
            SERVICE_CALCULATE_PLAN,
            SERVICE_RUN_CYCLE,
            SERVICE_START_BIG,
            SERVICE_START_SMALL,
            SERVICE_MANUAL_SHORT,
            SERVICE_MANUAL_NORMAL,
            SERVICE_STOP_ALL,
            SERVICE_TEST_SCENARIO,
        ):
            hass.services.async_remove(DOMAIN, service)
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: LawnConfigEntry) -> None:
    """Herlaad de entry als de opties wijzigen."""
    await hass.config_entries.async_reload(entry.entry_id)


def _async_register_services(hass: HomeAssistant) -> None:
    """Registreer de domein-services (eenmalig)."""
    if hass.services.has_service(DOMAIN, SERVICE_STOP_ALL):
        return

    async def _calculate_plan(call: ServiceCall) -> None:
        overrides: dict = {}
        if (val := call.data.get("test_fase")) is not None:
            overrides["fase"] = val
        if (val := call.data.get("test_temp_max")) is not None:
            overrides["temp_max"] = val
        if (val := call.data.get("test_regen_vandaag")) is not None:
            overrides["regen_vandaag"] = val
        if (val := call.data.get("test_regen_24u")) is not None:
            overrides["regen_24u"] = val
        if (val := call.data.get("test_wind")) is not None:
            overrides["wind"] = val
        if (val := call.data.get("test_automatisering_aan")) is not None:
            overrides["automatisering_aan"] = val
        for coord in _loaded_coordinators(hass):
            await coord.async_calculate_plan(overrides or None)

    async def _run_cycle(call: ServiceCall) -> None:
        for coord in _loaded_coordinators(hass):
            await coord.async_run_cycle(
                reason=call.data["reason"],
                slot_label=call.data["slot"],
                big_minutes=call.data["big_minutes"],
                small_minutes=call.data["small_minutes"],
                force_test=call.data["force_test"],
            )

    async def _start_big(call: ServiceCall) -> None:
        for coord in _loaded_coordinators(hass):
            await coord.async_start_big(call.data["minutes"])

    async def _start_small(call: ServiceCall) -> None:
        for coord in _loaded_coordinators(hass):
            await coord.async_start_small(call.data["minutes"])

    async def _manual_short(call: ServiceCall) -> None:
        for coord in _loaded_coordinators(hass):
            await coord.async_run_cycle(
                "Handmatig korte sproeibeurt", "Handmatig kort", *MANUAL_SHORT
            )

    async def _manual_normal(call: ServiceCall) -> None:
        for coord in _loaded_coordinators(hass):
            await coord.async_run_cycle(
                "Handmatig normale sproeibeurt", "Handmatig normaal", *MANUAL_NORMAL
            )

    async def _stop_all(call: ServiceCall) -> None:
        for coord in _loaded_coordinators(hass):
            await coord.async_stop_all()

    async def _test_scenario(call: ServiceCall) -> None:
        scenario = call.data["scenario"]
        overrides = _scenario_overrides(scenario)
        for coord in _loaded_coordinators(hass):
            await coord.async_set_test_mode(True)
            await coord.async_calculate_plan(overrides)

    hass.services.async_register(DOMAIN, SERVICE_CALCULATE_PLAN, _calculate_plan, CALC_PLAN_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_RUN_CYCLE, _run_cycle, RUN_CYCLE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_START_BIG, _start_big, MINUTES_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_START_SMALL, _start_small, MINUTES_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_MANUAL_SHORT, _manual_short)
    hass.services.async_register(DOMAIN, SERVICE_MANUAL_NORMAL, _manual_normal)
    hass.services.async_register(DOMAIN, SERVICE_STOP_ALL, _stop_all)
    hass.services.async_register(DOMAIN, SERVICE_TEST_SCENARIO, _test_scenario, TEST_SCENARIO_SCHEMA)


def _scenario_overrides(scenario: str) -> dict:
    """Vertaal een testscenario naar plan-overrides (een preview, geen echte run)."""
    # Uitgewerkte fase-scenario's (de gewenste testgevallen). Waarden simuleren het
    # moment waarop de planner draait (temp_nu/straling als "nu").
    detailed = {
        # 1. Volgroeid, 8 mm nachtregen, 25 C zonnig -> diepe logica slaat over.
        "s1_volgroeid_8mm_zon": {
            "fase": "bestaand_gras", "temp_max": 25, "temp_nu": 25, "regen_24u": 8,
            "straling": 700, "uv_index": 7, "luchtvochtigheid": 50, "bewolkt_of_nat": False,
        },
        # 2. Net ingezaaid, 8 mm nachtregen, 28 C zonnig veel straling (middag) ->
        #    toplaag-risico hoog -> korte onderhoudsbeurt ondanks nachtregen.
        "s2_net_ingezaaid_8mm_heet": {
            "fase": "pas_ingezaaid", "temp_max": 28, "temp_nu": 28, "regen_24u": 8,
            "straling": 800, "uv_index": 8, "luchtvochtigheid": 40, "bewolkt_of_nat": False,
        },
        # 3. Kiemend, 4 mm nachtregen, 30 C zonnig + wind -> meerdere korte beurten.
        "s3_kiemend_4mm_heet_wind": {
            "fase": "kiemend", "temp_max": 30, "temp_nu": 30, "regen_24u": 4,
            "straling": 750, "uv_index": 8, "wind": 22, "luchtvochtigheid": 35,
            "bewolkt_of_nat": False,
        },
        # 4. Net ingezaaid, geen regen, maar regen binnen 30 min -> beurt uitstellen.
        "s4_net_ingezaaid_regen_komt": {
            "fase": "pas_ingezaaid", "temp_max": 26, "temp_nu": 26, "regen_24u": 0,
            "straling": 600, "uv_index": 6, "luchtvochtigheid": 55,
            "regen_binnen_min": 30, "bewolkt_of_nat": False,
        },
        # 5. Jong gras, 5 mm nachtregen, 24 C half bewolkt -> minder snel sproeien.
        "s5_jong_5mm_halfbewolkt": {
            "fase": "jong_gras", "temp_max": 24, "temp_nu": 24, "regen_24u": 5,
            "straling": 300, "uv_index": 3, "luchtvochtigheid": 65, "bewolkt_of_nat": True,
        },
    }
    if scenario in detailed:
        return {"automatisering_aan": True, "carry_mm": 0.0, **detailed[scenario]}

    prefix = scenario[:3]
    temps = {
        "10c": 10,
        "15c": 15,
        "20c": 20,
        "25c": 25,
        "30c": 30,
        "35c": 35,
        "40c": 40,
    }
    temp = temps.get(prefix, 30 if scenario == "automatisering_uit" else 16)
    # Per-week stadia sproeien alleen als het tekort de adviesdiepte haalt; geef
    # die scenario's een opgebouwd tekort zodat de preview een sproeidag toont.
    if scenario == "25c_bestaand_gras":
        fase, carry = "bestaand_gras", 20.0
    elif scenario == "30c_rond_maaibeurt":
        fase, carry = "rond_eerste_maaibeurt", 20.0
    else:
        fase, carry = "pas_ingezaaid", 0.0
    return {
        "fase": fase,
        "carry_mm": carry,
        "temp_max": temp,
        "temp_nu": temp,
        "regen_vandaag": 5 if scenario == "30c_5mm_regen_verwacht" else 0,
        "regen_24u": 5 if scenario == "30c_5mm_regen_24u" else 0,
        "wind": 35 if scenario == "35c_harde_wind" else 5,
        "automatisering_aan": scenario != "automatisering_uit",
    }
