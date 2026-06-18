"""Coördinator voor Slim Gazon Sproeien.

Beheert de configuratie, de instelbare waarden, het dagplan, de veilige
uitvoering van sproeibeurten en alle tijdgestuurde taken. Vervangt de scripts
en automatiseringen uit het oorspronkelijke YAML-package.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import storage
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_change,
)
from homeassistant.helpers.start import async_at_started
from homeassistant.util import dt as dt_util

from .const import (
    CONF_BIG_SWITCH,
    CONF_CALC_TIME,
    CONF_DETAIL,
    CONF_HUMIDITY,
    CONF_RAIN_24H,
    CONF_RAIN_DATA,
    CONF_RAIN_FORECAST,
    CONF_RAIN_NOW,
    CONF_SMALL_SWITCH,
    CONF_SOIL,
    CONF_SOLAR,
    CONF_TEMP,
    CONF_TEMP_MAX,
    CONF_UV,
    CONF_WEATHER,
    CONF_WIND,
    DEFAULT_CALC_TIME,
    CONF_EXTRA_CALC_TIMES,
    DEFAULT_EXTRA_CALC_TIMES,
    DEFAULT_MASTER,
    DEFAULT_PHASE,
    DEFAULT_TEST,
    KEY_LAST_EXECUTED,
    KEY_MASTER,
    KEY_PHASE,
    KEY_PLAN,
    KEY_SOW_DATE,
    KEY_TEST,
    KEY_VALUES,
    KEY_WB_APPLIED,
    KEY_WB_CARRY,
    KEY_WB_DATE,
    KEY_WB_NEED,
    KEY_WB_RAIN,
    NOWCAST_ONSET_MMH,
    NUMBER_DEFAULTS,
    PHASE_MANUAL,
    SIGNAL_UPDATE,
    STORE_VERSION,
    WB_MAX_CARRY,
)
from .nowcast import NowcastResult, parse_nowcast
from .planner import PlanInputs, PlanParams, calculate

_LOGGER = logging.getLogger(__name__)

# Weercondities die als "bewolkt of nat" tellen.
WET_CONDITIONS = {
    "cloudy",
    "fog",
    "hail",
    "lightning-rainy",
    "pouring",
    "rainy",
    "snowy-rainy",
}
# Condities in het weerbericht die als bewolkt/nat resp. helder/zonnig tellen.
CLOUDY_CONDITIONS = WET_CONDITIONS | {"snowy", "lightning", "exceptional"}
SUNNY_CONDITIONS = {"sunny", "clear", "clear-night"}

UNAVAILABLE_STATES = {STATE_UNKNOWN, STATE_UNAVAILABLE, "", "none", "None"}

# Veilige pauze tussen het schakelen van de sproeiers (seconden).
SWITCH_PAUSE = 5
# Hoe vaak we tijdens een beurt op regen controleren (seconden).
RAIN_CHECK_INTERVAL = 2


class LawnCoordinator:
    """Centrale logica voor één gazon-zone."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Init."""
        self.hass = hass
        self.entry = entry
        self._store: storage.Store = storage.Store(
            hass, STORE_VERSION, f"{entry.domain}.{entry.entry_id}"
        )

        # Instelbare staat (persistent).
        self.values: dict[str, float] = dict(NUMBER_DEFAULTS)
        self.phase: str = DEFAULT_PHASE
        self.master_on: bool = DEFAULT_MASTER
        self.test_mode: bool = DEFAULT_TEST
        self.sow_date: str | None = None
        self.plan: dict | None = None
        self.last_executed: str = ""

        # Waterbalans (lopend tekort). wb_carry = tekort dat wb_date in ging,
        # wb_need/wb_rain = laatst berekende dagbehoefte/regen-aftrek, wb_applied
        # = vandaag daadwerkelijk gegeven water.
        self.wb_date: str = ""
        self.wb_carry: float = 0.0
        self.wb_need: float = 0.0
        self.wb_rain: float = 0.0
        self.wb_applied: float = 0.0

        # Vluchtige staat.
        self.busy: bool = False
        self._cycle_task: asyncio.Task | None = None
        self._unsubs: list[Callable[[], None]] = []
        self._recalc_unsub: Callable[[], None] | None = None

    # -- configuratie ------------------------------------------------------
    @property
    def config(self) -> dict:
        """Effectieve configuratie.

        Zodra de opties zijn aangepast vormen die de volledige, gezaghebbende
        bron (de options flow toont alle velden), anders gebruiken we de
        oorspronkelijke setup-data.
        """
        return dict(self.entry.options) if self.entry.options else dict(self.entry.data)

    def conf(self, key: str, default=None):
        """Lees één configuratiewaarde."""
        value = self.config.get(key, default)
        return value if value not in (None, "") else default

    @property
    def big_switch(self) -> str | None:
        return self.conf(CONF_BIG_SWITCH)

    @property
    def small_switch(self) -> str | None:
        return self.conf(CONF_SMALL_SWITCH)

    # -- laden / opslaan ---------------------------------------------------
    async def async_load(self) -> None:
        """Laad opgeslagen staat en start de tijdgestuurde taken."""
        data = await self._store.async_load()
        if data:
            stored = data.get(KEY_VALUES, {})
            for key, default in NUMBER_DEFAULTS.items():
                self.values[key] = float(stored.get(key, default))
            self.phase = data.get(KEY_PHASE, DEFAULT_PHASE)
            self.master_on = bool(data.get(KEY_MASTER, DEFAULT_MASTER))
            self.test_mode = bool(data.get(KEY_TEST, DEFAULT_TEST))
            self.sow_date = data.get(KEY_SOW_DATE)
            self.plan = data.get(KEY_PLAN)
            self.last_executed = data.get(KEY_LAST_EXECUTED, "")
            self.wb_date = data.get(KEY_WB_DATE, "")
            self.wb_carry = float(data.get(KEY_WB_CARRY, 0.0))
            self.wb_need = float(data.get(KEY_WB_NEED, 0.0))
            self.wb_rain = float(data.get(KEY_WB_RAIN, 0.0))
            self.wb_applied = float(data.get(KEY_WB_APPLIED, 0.0))

        self._setup_schedules()
        # Veiligheid: zet sproeiers uit zodra Home Assistant gestart is.
        self._unsubs.append(async_at_started(self.hass, self._async_startup_safety))

        # Ververs de nowcast-sensor zodra de bron-sensor verandert.
        rain_data = self.conf(CONF_RAIN_DATA)
        if rain_data:
            self._unsubs.append(
                async_track_state_change_event(
                    self.hass, [rain_data], self._on_rain_data
                )
            )

    @callback
    def _on_rain_data(self, event) -> None:
        """De Buienalarm-sensor is bijgewerkt; hertekenen de entiteiten."""
        self._notify_listeners()

    async def async_save(self) -> None:
        """Sla de huidige staat op."""
        await self._store.async_save(
            {
                KEY_VALUES: self.values,
                KEY_PHASE: self.phase,
                KEY_MASTER: self.master_on,
                KEY_TEST: self.test_mode,
                KEY_SOW_DATE: self.sow_date,
                KEY_PLAN: self.plan,
                KEY_LAST_EXECUTED: self.last_executed,
                KEY_WB_DATE: self.wb_date,
                KEY_WB_CARRY: self.wb_carry,
                KEY_WB_NEED: self.wb_need,
                KEY_WB_RAIN: self.wb_rain,
                KEY_WB_APPLIED: self.wb_applied,
            }
        )

    async def async_unload(self) -> None:
        """Stop taken en luisteraars."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._recalc_unsub:
            self._recalc_unsub()
            self._recalc_unsub = None
        if self._cycle_task and not self._cycle_task.done():
            self._cycle_task.cancel()

    # -- staat wijzigen ----------------------------------------------------
    @callback
    def _notify_listeners(self) -> None:
        async_dispatcher_send(self.hass, f"{SIGNAL_UPDATE}_{self.entry.entry_id}")

    def get_value(self, key: str) -> float:
        """Huidige waarde van een instelbare parameter."""
        return self.values.get(key, NUMBER_DEFAULTS.get(key, 0.0))

    async def async_set_value(self, key: str, value: float) -> None:
        """Wijzig een instelbare parameter."""
        self.values[key] = float(value)
        await self.async_save()
        self._notify_listeners()
        self._schedule_recalc()

    async def async_set_phase(self, phase: str) -> None:
        self.phase = phase
        await self.async_save()
        self._notify_listeners()
        self._schedule_recalc()

    async def async_set_master(self, value: bool) -> None:
        self.master_on = value
        await self.async_save()
        self._notify_listeners()
        self._schedule_recalc()

    async def async_set_test_mode(self, value: bool) -> None:
        self.test_mode = value
        await self.async_save()
        self._notify_listeners()

    async def async_set_sow_date(self, value: str | None) -> None:
        self.sow_date = value
        await self.async_save()
        self._notify_listeners()
        self._schedule_recalc()

    @callback
    def _schedule_recalc(self) -> None:
        """Plan een herberekening met korte debounce na wijzigingen."""
        if self._recalc_unsub:
            self._recalc_unsub()

        async def _run(_now=None) -> None:
            self._recalc_unsub = None
            await self.async_calculate_plan()

        self._recalc_unsub = async_call_later(self.hass, 5, _run)

    # -- sensoren lezen ----------------------------------------------------
    def _state_float(self, conf_key: str, default: float) -> float:
        """Lees een geconfigureerde sensor als float (komma/punt-veilig)."""
        entity_id = self.conf(conf_key)
        if not entity_id:
            return default
        state = self.hass.states.get(entity_id)
        if state is None or state.state in UNAVAILABLE_STATES:
            return default
        try:
            return float(str(state.state).replace(",", "."))
        except (ValueError, TypeError):
            return default

    def _is_configured_unavailable(self, conf_key: str) -> bool:
        """True als sensor is ingesteld maar (nog) geen waarde heeft."""
        entity_id = self.conf(conf_key)
        if not entity_id:
            return False
        state = self.hass.states.get(entity_id)
        return state is None or state.state in UNAVAILABLE_STATES

    def rain_now(self) -> float:
        """Huidige regenintensiteit (mm/h)."""
        return self._state_float(CONF_RAIN_NOW, 0.0)

    def _nowcast(self) -> NowcastResult | None:
        """Decodeer de optionele Buienalarm nowcast-sensor."""
        entity_id = self.conf(CONF_RAIN_DATA)
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in UNAVAILABLE_STATES:
            return None
        return parse_nowcast(dict(state.attributes), dt_util.now(), NOWCAST_ONSET_MMH)

    def nowcast_summary(self) -> dict | None:
        """Samenvatting van de nowcast voor de sensor (None als niet beschikbaar)."""
        result = self._nowcast()
        if result is None or not result.available:
            return None
        return {
            "window_mm": result.window_mm,
            "today_mm": result.today_mm,
            "before_noon_mm": result.before_noon_mm,
            "minutes_until_rain": result.minutes_until_rain,
            "horizon_min": result.horizon_min,
        }

    def _switch_unavailable(self) -> bool:
        for entity_id in (self.big_switch, self.small_switch):
            if not entity_id:
                return True
            state = self.hass.states.get(entity_id)
            if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                return True
        return False

    async def _async_get_forecast(self, forecast_type: str) -> list[dict]:
        """Haal een weersverwachting op via weather.get_forecasts."""
        weather = self.conf(CONF_WEATHER)
        if not weather:
            return []
        try:
            response = await self.hass.services.async_call(
                "weather",
                "get_forecasts",
                {"type": forecast_type, "entity_id": weather},
                blocking=True,
                return_response=True,
            )
        except Exception as err:  # noqa: BLE001 - verwachting is optioneel
            _LOGGER.debug("Weersverwachting (%s) niet beschikbaar: %s", forecast_type, err)
            return []
        if not response or weather not in response:
            return []
        return response[weather].get("forecast", []) or []

    def _assess_sky(
        self, hourly: list[dict], daily: list[dict], today
    ) -> tuple[bool, bool, bool]:
        """Hoe bewolkt/zonnig wordt de dág volgens het weerbericht.

        Geeft (heeft_verwachting, bewolkt, zonnig). Kijkt naar de condities
        overdag (8–20u) in de uur-verwachting — niet naar de toevallige bewolking
        op het rekenmoment — en valt terug op de dag-verwachting. `cloud_coverage`
        wordt gebruikt als de verwachting dat levert.
        """
        cloudy_h = sunny_h = total = 0
        cover: list[float] = []
        for item in hourly:
            parsed = dt_util.parse_datetime(str(item.get("datetime", "")))
            if parsed is None:
                continue
            local = dt_util.as_local(parsed)
            if local.date() != today or not 8 <= local.hour < 20:
                continue
            total += 1
            cond = str(item.get("condition", "")).lower()
            if cond in CLOUDY_CONDITIONS:
                cloudy_h += 1
            elif cond in SUNNY_CONDITIONS:
                sunny_h += 1
            cc = item.get("cloud_coverage")
            if cc is not None:
                try:
                    cover.append(float(cc))
                except (TypeError, ValueError):
                    pass
        if total:
            cloudy_frac = cloudy_h / total
            sunny_frac = sunny_h / total
            if cover:
                avg = sum(cover) / len(cover)
                cloudy = avg >= 65 or cloudy_frac >= 0.5
                sunny = (avg <= 35 or sunny_frac >= 0.5) and not cloudy
            else:
                cloudy = cloudy_frac >= 0.5
                sunny = sunny_frac >= 0.5 and not cloudy
            return True, cloudy, sunny
        # Geen uur-data: gebruik de dag-verwachting van vandaag.
        for item in daily:
            parsed = dt_util.parse_datetime(str(item.get("datetime", "")))
            if parsed is None or dt_util.as_local(parsed).date() != today:
                continue
            cc = item.get("cloud_coverage")
            if cc is not None:
                try:
                    avg = float(cc)
                    return True, avg >= 65, avg <= 35
                except (TypeError, ValueError):
                    pass
            cond = str(item.get("condition", "")).lower()
            return True, cond in CLOUDY_CONDITIONS, cond in SUNNY_CONDITIONS
        return False, False, False

    # -- plan berekenen ----------------------------------------------------
    async def async_calculate_plan(self, overrides: dict | None = None) -> dict:
        """Bereken een nieuw dagplan en sla het op."""
        overrides = overrides or {}
        today = dt_util.now().date()
        today_str = today.isoformat()

        # Een berekening met test-overrides is een preview: die mag de echte
        # waterbalans niet bijwerken.
        preview = bool(overrides)
        if preview:
            carry_in = float(overrides.get("carry_mm", self.wb_carry))
        else:
            carry_in = self._roll_water_balance(today_str)

        hourly = await self._async_get_forecast("hourly")
        daily = await self._async_get_forecast("daily")

        forecast_regen_vandaag = 0.0
        forecast_regen_middag = 0.0
        forecast_wind_max = 0.0
        source = hourly if hourly else daily
        for item in source:
            parsed = dt_util.parse_datetime(str(item.get("datetime", "")))
            if parsed is None:
                continue
            local = dt_util.as_local(parsed)
            if local.date() != today:
                continue
            precip = float(item.get("precipitation") or 0.0)
            forecast_regen_vandaag += precip
            if hourly and local.hour < 12:
                forecast_regen_middag += precip
            wind = float(item.get("wind_speed") or 0.0)
            forecast_wind_max = max(forecast_wind_max, wind)

        forecast_items_count = len(hourly)

        # Meetwaarden (met optionele test-overrides).
        temp_now = self._state_float(CONF_TEMP, 16.0)
        temp_max = float(overrides.get("temp_max", self._state_float(CONF_TEMP_MAX, temp_now)))

        # Nowcast (Buienalarm) geeft hoge-resolutie regen vooruit; gebruik die om
        # de verwachte regen van vandaag en vóór de middag preciezer te maken.
        nowcast = self._nowcast()
        nowcast_today = nowcast.today_mm if nowcast and nowcast.available else 0.0
        nowcast_before_noon = (
            nowcast.before_noon_mm if nowcast and nowcast.available else 0.0
        )

        sensor_regen_vandaag = self._state_float(CONF_RAIN_FORECAST, 0.0)
        regen_vandaag = float(
            overrides.get(
                "regen_vandaag",
                round(
                    max(sensor_regen_vandaag, forecast_regen_vandaag, nowcast_today), 1
                ),
            )
        )
        forecast_regen_middag = max(forecast_regen_middag, nowcast_before_noon)
        regen_24u = float(overrides.get("regen_24u", self._state_float(CONF_RAIN_24H, 0.0)))
        wind_now = self._state_float(CONF_WIND, 0.0)
        wind_dag_max = float(overrides.get("wind", round(max(forecast_wind_max, wind_now), 1)))

        luchtvochtigheid = self._state_float(CONF_HUMIDITY, 60.0)
        uv_index = self._state_float(CONF_UV, 0.0)
        straling = self._state_float(CONF_SOLAR, 0.0)

        # Bewolkt/zonnig vooral uit het weerbericht voor de dag; alleen als er
        # geen verwachting is, terugvallen op de toestand op het rekenmoment.
        have_sky, forecast_cloudy, zonnig = self._assess_sky(hourly, daily, today)
        if have_sky:
            bewolkt_of_nat = forecast_cloudy
        else:
            weather_state = ""
            weather_eid = self.conf(CONF_WEATHER)
            if weather_eid and (st := self.hass.states.get(weather_eid)):
                weather_state = st.state
            detail_state = ""
            detail_eid = self.conf(CONF_DETAIL)
            if detail_eid and (st := self.hass.states.get(detail_eid)):
                detail_state = str(st.state).lower()
            bewolkt_of_nat = (
                weather_state in WET_CONDITIONS
                or "bewolkt" in detail_state
                or "regen" in detail_state
                or "bui" in detail_state
            )

        bodemvocht = self._state_float(CONF_SOIL, -1.0) if self.conf(CONF_SOIL) else -1.0

        fase = str(overrides.get("fase", self.phase))
        master = bool(overrides.get("automatisering_aan", self.master_on))

        inputs = PlanInputs(
            fase=fase,
            automatisering_aan=master,
            temp_max=temp_max,
            regen_vandaag=regen_vandaag,
            regen_24u=regen_24u,
            regen_middag=forecast_regen_middag,
            wind_dag_max=wind_dag_max,
            luchtvochtigheid=luchtvochtigheid,
            uv_index=uv_index,
            straling=straling,
            bewolkt_of_nat=bewolkt_of_nat,
            bodemvocht=bodemvocht,
            forecast_items_count=forecast_items_count,
            carry_mm=carry_in,
            zonnig=zonnig,
        )
        params = self._build_params()
        plan = calculate(inputs, params)

        # Werk de waterbalans bij (alleen voor een echte berekening).
        if not preview:
            if plan.soil_reset:
                self.wb_carry = 0.0
                self.wb_need = 0.0
                self.wb_rain = 0.0
                self.wb_applied = 0.0
            else:
                self.wb_need = plan.daily_need
                self.wb_rain = plan.rain_offset
        water_tekort = self.water_deficit(plan.gross_deficit)

        warnings = self._sensor_warnings(overrides)
        if plan.capped:
            warnings = "diepe beurt beperkt door max minuten/runtime" + (
                "" if warnings == "geen" else f", {warnings}"
            )

        plan_dict = asdict(plan)
        plan_dict["calculated_at"] = dt_util.now().isoformat(timespec="seconds")
        plan_dict["warnings"] = warnings
        plan_dict["inputs"] = {
            "temp_max": temp_max,
            "regen_vandaag": regen_vandaag,
            "regen_24u": regen_24u,
            "regen_middag": round(forecast_regen_middag, 1),
            "wind_dag_max": wind_dag_max,
            "luchtvochtigheid": luchtvochtigheid,
            "uv_index": uv_index,
            "straling": straling,
            "bodemvocht": bodemvocht,
            "bewolkt_of_nat": bewolkt_of_nat,
            "zonnig": zonnig,
            "fase": fase,
            "dagbehoefte_mm": plan.daily_need,
            "regen_aftrek_mm": plan.rain_offset,
            "tekort_begin_mm": plan.carry_in,
            "watertekort_mm": water_tekort,
            "nowcast_vandaag_mm": nowcast_today if nowcast else None,
            "nowcast_voor_middag_mm": nowcast_before_noon if nowcast else None,
            "nowcast_minuten_tot_regen": (
                nowcast.minutes_until_rain if nowcast and nowcast.available else None
            ),
        }

        self.plan = plan_dict
        await self.async_save()
        self._notify_listeners()

        persistent_notification.async_create(
            self.hass,
            f"Dagplan voor {today}: {plan.summary}\n"
            f"Dagbehoefte {plan.daily_need} mm, regen-aftrek {plan.rain_offset} mm, "
            f"watertekort {water_tekort} mm. "
            f"Regen vandaag {regen_vandaag} mm, regen 24u {regen_24u} mm, "
            f"max temp {temp_max} °C, wind max {wind_dag_max} km/h, "
            f"RV {luchtvochtigheid}%, UV {uv_index}, straling {straling} W/m². "
            f"Fase {fase}, range {plan.temp_range}. "
            f"Testmodus: {self.test_mode}. Waarschuwingen: {warnings}.",
            title="Gazon dagplan aangemaakt",
            notification_id=f"{self.entry.entry_id}_plan",
        )
        _LOGGER.info("Dagplan berekend: %s", plan.summary)
        return plan_dict

    def _build_params(self) -> PlanParams:
        v = self.get_value
        return PlanParams(
            factor=v("sproei_factor"),
            grote_rate=v("grote_rate"),
            kleine_rate=v("kleine_rate"),
            max_minuten=v("max_minuten_per_beurt"),
            min_mm_per_beurt=v("min_mm_per_beurt"),
            regen_negeren_onder=v("regen_negeren_onder_mm"),
            regen_vandaag_skip=v("regen_vandaag_skip_mm"),
            regen_24u_skip=v("regen_24u_skip_mm"),
            wind_minderen=v("wind_minderen_kmh"),
            wind_stop=v("wind_stop_kmh"),
            temp_warm=v("temp_warm_c"),
            temp_heet=v("temp_heet_c"),
            temp_extreem_heet=v("temp_extreem_heet_c"),
            rv_laag=v("rv_laag"),
            rv_hoog=v("rv_hoog"),
            uv_hoog=v("uv_hoog"),
            straling_hoog=v("straling_hoog_wm2"),
            bodemvocht_nat=v("bodemvocht_nat"),
            max_runtime=v("max_runtime_minuten"),
        )

    # -- waterbalans -------------------------------------------------------
    def _roll_water_balance(self, today_str: str) -> float:
        """Sluit de vorige dag af bij een nieuwe dag en geef het tekort van vandaag.

        Het tekort dat een dag in gaat is wat er aan het eind van de vorige dag
        nog "open" stond: vorig tekort + behoefte − regen − gegeven water,
        afgetopt op `WB_MAX_CARRY`.
        """
        if self.wb_date != today_str:
            leftover = self.wb_carry + self.wb_need - self.wb_rain - self.wb_applied
            self.wb_carry = round(max(0.0, min(leftover, WB_MAX_CARRY)), 1)
            self.wb_date = today_str
            self.wb_need = 0.0
            self.wb_rain = 0.0
            self.wb_applied = 0.0
        return self.wb_carry

    def water_deficit(self, gross: float | None = None) -> float:
        """Actueel watertekort (mm): de dagbehoefte minus het al gegeven water."""
        if gross is None:
            gross = float((self.plan or {}).get("gross_deficit", 0.0) or 0.0)
        return round(max(0.0, gross - self.wb_applied), 1)

    async def _credit_applied(self, big_minutes: float, small_minutes: float) -> None:
        """Boek daadwerkelijk gegeven water af van het tekort."""
        applied = max(
            big_minutes * self.get_value("grote_rate"),
            small_minutes * self.get_value("kleine_rate"),
        )
        if applied <= 0:
            return
        self.wb_applied = round(self.wb_applied + applied, 2)
        await self.async_save()
        self._notify_listeners()

    def _sensor_warnings(self, overrides: dict) -> str:
        meldingen: list[str] = []
        if "temp_max" not in overrides and self._is_configured_unavailable(CONF_TEMP_MAX):
            meldingen.append("temperatuur default gebruikt")
        if "regen_vandaag" not in overrides and self._is_configured_unavailable(CONF_RAIN_FORECAST):
            meldingen.append("regenverwachting default gebruikt")
        if "wind" not in overrides and self._is_configured_unavailable(CONF_WIND):
            meldingen.append("wind default gebruikt")
        return ", ".join(meldingen) if meldingen else "geen"

    # -- sproeibeurt uitvoeren --------------------------------------------
    async def async_run_cycle(
        self,
        reason: str,
        slot_label: str,
        big_minutes: float,
        small_minutes: float,
        force_test: bool = False,
    ) -> None:
        """Voer veilig een sproeibeurt uit (met alle veiligheidschecks)."""
        if not self.master_on:
            await self._skip(slot_label, "master staat uit")
            return
        if self.phase == PHASE_MANUAL:
            await self._skip(slot_label, "gazonfase staat op Alleen handmatig / uit")
            return
        if self.busy or (self._cycle_task and not self._cycle_task.done()):
            await self._skip(slot_label, "er loopt al een sproeibeurt", notify=False)
            return
        if self._switch_unavailable():
            await self._skip(slot_label, "een sproeier is niet beschikbaar")
            return
        if self.test_mode or force_test:
            persistent_notification.async_create(
                self.hass,
                f"{slot_label} zou starten maar testmodus staat aan. "
                f"Groot {big_minutes} min, klein {small_minutes} min. Reden: {reason}",
                title="Gazon testmodus",
                notification_id=f"{self.entry.entry_id}_test",
            )
            _LOGGER.info("%s dry-run: groot %s min, klein %s min", slot_label, big_minutes, small_minutes)
            return
        if self.rain_now() >= self.get_value("regen_intensiteit_stop"):
            await self._skip(slot_label, "regenintensiteit is boven de stopdrempel")
            return

        self.busy = True
        self._notify_listeners()
        self._cycle_task = self.hass.async_create_background_task(
            self._execute(reason, slot_label, big_minutes, small_minutes),
            name=f"{self.entry.domain}_cycle",
        )

    async def _execute(
        self, reason: str, slot_label: str, big_minutes: float, small_minutes: float
    ) -> None:
        """De daadwerkelijke schakelvolgorde."""
        big_s = int(round(big_minutes * 60))
        small_s = int(round(small_minutes * 60))
        try:
            persistent_notification.async_create(
                self.hass,
                f"{slot_label} gestart. Groot {big_minutes} min, klein {small_minutes} min. Reden: {reason}",
                title="Gazon sproeibeurt gestart",
                notification_id=f"{self.entry.entry_id}_run",
            )
            _LOGGER.info("%s gestart: groot %s min, klein %s min", slot_label, big_minutes, small_minutes)

            await self._switch_off_both()
            await asyncio.sleep(SWITCH_PAUSE)

            if big_s > 0:
                stopped_by_rain = await self._run_switch(self.big_switch, big_s)
                if stopped_by_rain:
                    await self._switch_off_both()
                    _LOGGER.info("%s gestopt na grote sproeier: regen begon", slot_label)
                    persistent_notification.async_create(
                        self.hass,
                        f"{slot_label}: gestopt omdat regen startte.",
                        title="Gazon gestopt door regen",
                        notification_id=f"{self.entry.entry_id}_rain",
                    )
                    return

            await asyncio.sleep(SWITCH_PAUSE)

            if small_s > 0:
                await self._run_switch(self.small_switch, small_s)

            await self._switch_off_both()
            await self._credit_applied(big_minutes, small_minutes)
            persistent_notification.async_create(
                self.hass,
                f"{slot_label} afgerond; beide sproeiers zijn uitgezet.",
                title="Gazon sproeibeurt afgerond",
                notification_id=f"{self.entry.entry_id}_done",
            )
            _LOGGER.info("%s afgerond", slot_label)
        except asyncio.CancelledError:
            _LOGGER.info("%s onderbroken", slot_label)
            raise
        finally:
            await self._switch_off_both()
            self.busy = False
            self._notify_listeners()

    async def _run_switch(self, entity_id: str | None, seconds: int) -> bool:
        """Schakel een sproeier aan, wacht en stop bij regen. True = gestopt door regen."""
        if not entity_id:
            return False
        max_s = int(self.get_value("max_runtime_minuten") * 60)
        seconds = min(seconds, max_s)
        stop_drempel = self.get_value("regen_intensiteit_stop")
        await self._turn_on(entity_id)
        elapsed = 0
        try:
            while elapsed < seconds:
                await asyncio.sleep(min(RAIN_CHECK_INTERVAL, seconds - elapsed))
                elapsed += RAIN_CHECK_INTERVAL
                if self.rain_now() >= stop_drempel:
                    return True
        finally:
            await self._turn_off(entity_id)
        return False

    async def async_start_big(self, minutes: float) -> None:
        await self.async_run_cycle("Handmatig grote sproeier", "Start grote sproeier", minutes, 0)

    async def async_start_small(self, minutes: float) -> None:
        await self.async_run_cycle("Handmatig kleine sproeier", "Start kleine sproeier", 0, minutes)

    async def async_stop_all(self) -> None:
        """Stop alle sproeiers en annuleer een lopende beurt."""
        if self._cycle_task and not self._cycle_task.done():
            self._cycle_task.cancel()
        await self._switch_off_both()
        self.busy = False
        self._notify_listeners()
        _LOGGER.info("Stop: beide sproeiers uitgezet")

    # -- schakel-helpers ---------------------------------------------------
    async def _turn_on(self, entity_id: str) -> None:
        await self._switch_call("turn_on", entity_id)

    async def _turn_off(self, entity_id: str) -> None:
        await self._switch_call("turn_off", entity_id)

    async def _switch_off_both(self) -> None:
        entities = [e for e in (self.big_switch, self.small_switch) if e]
        if entities:
            await self._switch_call("turn_off", entities)

    async def _switch_call(self, service: str, entity_id) -> None:
        try:
            await self.hass.services.async_call(
                "homeassistant", service, {"entity_id": entity_id}, blocking=True
            )
        except Exception as err:  # noqa: BLE001 - schakelen mag nooit alles laten crashen
            _LOGGER.warning("Kon %s niet uitvoeren op %s: %s", service, entity_id, err)

    async def _skip(self, slot_label: str, reden: str, notify: bool = True) -> None:
        _LOGGER.info("%s overgeslagen: %s", slot_label, reden)
        if notify:
            persistent_notification.async_create(
                self.hass,
                f"{slot_label} niet gestart: {reden}.",
                title="Gazon sproeien overgeslagen",
                notification_id=f"{self.entry.entry_id}_skip",
            )

    # -- tijdgestuurde taken ----------------------------------------------
    @callback
    def _setup_schedules(self) -> None:
        hour, minute = self._calc_time()
        self._unsubs.append(
            async_track_time_change(
                self.hass, self._async_daily_calc, hour=hour, minute=minute, second=0
            )
        )
        # Extra herberekeningen overdag voor een actueler plan.
        for extra in self._extra_calc_times():
            try:
                parts = str(extra).split(":")
                extra_hour, extra_minute = int(parts[0]), int(parts[1])
            except (ValueError, IndexError):
                continue
            self._unsubs.append(
                async_track_time_change(
                    self.hass,
                    self._async_daily_calc,
                    hour=extra_hour,
                    minute=extra_minute,
                    second=0,
                )
            )
        self._unsubs.append(
            async_track_time_change(self.hass, self._async_minute_tick, second=0)
        )

    def _calc_time(self) -> tuple[int, int]:
        raw = self.conf(CONF_CALC_TIME, DEFAULT_CALC_TIME) or DEFAULT_CALC_TIME
        try:
            parts = [int(p) for p in str(raw).split(":")]
            return parts[0], parts[1]
        except (ValueError, IndexError):
            return 4, 0

    def _extra_calc_times(self) -> list[str]:
        """Extra rekentijden uit de config (lege lijst = geen, ontbreekt = default)."""
        value = self.config.get(CONF_EXTRA_CALC_TIMES)
        if value is None:
            return list(DEFAULT_EXTRA_CALC_TIMES)
        return list(value)

    async def _async_daily_calc(self, now: datetime) -> None:
        await self.async_calculate_plan()

    async def _async_minute_tick(self, now: datetime) -> None:
        await self._run_due_slots(now)
        if not self.busy:
            await self._watchdog(now)

    async def _run_due_slots(self, now: datetime) -> None:
        if not self.plan:
            return
        now_hm = now.strftime("%H:%M")
        date_str = now.strftime("%Y-%m-%d")
        for slot in self.plan.get("slots", []):
            if not slot.get("active"):
                continue
            if str(slot.get("time", ""))[:5] != now_hm:
                continue
            key = f"{date_str}-slot-{slot['index']}"
            if self.last_executed == key:
                continue
            self.last_executed = key
            await self.async_save()
            await self.async_run_cycle(
                reason=slot.get("reason") or self.plan.get("reason", ""),
                slot_label=f"Slot {slot['index']}",
                big_minutes=float(slot.get("big_minutes", 0)),
                small_minutes=float(slot.get("small_minutes", 0)),
            )
            return

    async def _watchdog(self, now: datetime) -> None:
        """Backstop: zet sproeiers uit die te lang aan staan."""
        max_s = self.get_value("max_runtime_minuten") * 60
        for entity_id in (self.big_switch, self.small_switch):
            if not entity_id:
                continue
            state = self.hass.states.get(entity_id)
            if state is None or state.state != "on":
                continue
            running = (now - state.last_changed).total_seconds()
            if running > max_s:
                _LOGGER.warning("Veiligheidsstop: %s stond %.0f s aan", entity_id, running)
                await self._switch_off_both()
                self.busy = False
                self._notify_listeners()
                persistent_notification.async_create(
                    self.hass,
                    "Een sproeier stond langer aan dan toegestaan en is uitgezet.",
                    title="Gazon veiligheidsstop",
                    notification_id=f"{self.entry.entry_id}_safety",
                )
                return

    async def _async_startup_safety(self, *_: object) -> None:
        await self._switch_off_both()
        self.busy = False
        self._notify_listeners()
        _LOGGER.debug("Startveiligheid: sproeiers uitgezet")

    # -- afgeleide waarden -------------------------------------------------
    def advised_phase(self) -> str:
        """Geadviseerde fase op basis van de zaaidatum."""
        if not self.sow_date:
            return "onbekend"
        parsed = dt_util.parse_date(self.sow_date)
        if parsed is None:
            return "onbekend"
        age = (dt_util.now().date() - parsed).days
        if age < 0:
            return "onbekend"
        if age <= 7:
            return "pas_ingezaaid"
        if age <= 21:
            return "kiemend"
        if age <= 49:
            return "jong_gras"
        if age <= 70:
            return "rond_eerste_maaibeurt"
        return "bestaand_gras"

    def next_run(self) -> str:
        """Tijd van de eerstvolgende geplande beurt vandaag."""
        if not self.plan:
            return "geen"
        now_hm = dt_util.now().strftime("%H:%M")
        for slot in self.plan.get("slots", []):
            if slot.get("active") and str(slot.get("time", ""))[:5] > now_hm:
                return str(slot["time"])[:5]
        return "geen"

    def status(self) -> str:
        """Korte statustekst."""
        if self.busy:
            return "bezig"
        if self.test_mode:
            return "testmodus"
        if not self.master_on:
            return "uit"
        return "actief"
