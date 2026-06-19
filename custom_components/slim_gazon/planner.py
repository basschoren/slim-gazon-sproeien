"""Berekening van het slimme dagplan.

Twee soorten bewatering, afhankelijk van de grasfase:

* **Diepe bewatering** (jong gras, rond eerste maaibeurt, volgroeid gazon):
  een lopende **waterbalans** (tekort). De basis is het sproeiadvies uit
  `sproeiadvies_gazon_temperatuurklassen.xlsx` (zie `ADVICE` in const.py): voor
  een zonnige dag de dagbehoefte (mm/dag) en de adviesdiepte per beurt. Een
  weerfactor schaalt dat naar de werkelijke dag; regen (incl. nowcast) wordt
  afgetrokken; er wordt pas (diep) gesproeid als het tekort de adviesdiepte
  haalt. Genoeg regen → de dag overslaan.

* **Toplaag-onderhoud** (net ingezaaid, kiemend gras): hier telt niet de totale
  mm maar of de bovenste 0–2 cm vochtig blijft. Nachtregen telt als buffer maar
  blokkeert de dag niet: een **toplaag-uitdroogrisico** (uit temperatuur,
  zon/straling, wind en luchtvochtigheid op dat moment) bepaalt of er een korte
  onderhoudsbeurt nodig is. Omdat de straling 's ochtends laag en 's middags hoog
  is en het plan meerdere keren per dag wordt herberekend, ontstaat vanzelf
  "ochtend overslaan, later op de dag wél een korte beurt".

De waterbalans-staat leeft in de coördinator; deze module is een pure functie.
Belangrijkste functies: `calculate` (kiest de fase-aanpak), `calculate_rain_credit`,
`calculate_top_layer_dry_risk`, `should_do_maintenance_watering`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from .const import (
    ADVICE,
    ADVICE_TEMPS,
    PHASE_GERM,
    PHASE_MANUAL,
    PHASE_NEW,
    SLOT_COUNT,
    AdviceCell,
)

# Op een warme, droge dag telt de bewolkt/nat-melding niet mee in de weerfactor:
# als het amper geregend heeft (< 2 mm in 24u) én het warm is (> 25 °C), blijft de
# verdamping hoog ondanks wat wolken — dan niet 20% afschalen.
HOT_DRY_RAIN_24H_MM = 2.0
HOT_DRY_TEMP_C = 25.0

# Fases waarvoor toplaag-onderhoud geldt (i.p.v. diepe bewatering).
TOPLAAG_PHASES = (PHASE_NEW, PHASE_GERM)


def _round(value: float, ndigits: int = 0) -> float:
    """Rond af zoals Jinja's `round` filter (half naar boven)."""
    quant = Decimal(1).scaleb(-ndigits)
    return float(Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP))


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(value, high))


@dataclass(slots=True)
class PlanInputs:
    """Ruwe meetwaarden die in de berekening gaan."""

    fase: str
    automatisering_aan: bool
    temp_max: float
    regen_vandaag: float
    regen_24u: float
    regen_middag: float
    wind_dag_max: float
    luchtvochtigheid: float
    uv_index: float
    straling: float
    bewolkt_of_nat: bool
    bodemvocht: float = -1.0
    forecast_items_count: int = 0
    # Lopend watertekort (mm) dat vandaag in ging — kern van de waterbalans.
    carry_mm: float = 0.0
    # De dag wordt volgens het weerbericht overwegend zonnig/helder.
    zonnig: bool = False
    # Huidige (momentane) waarden voor het toplaag-risico en regen-checks.
    temp_nu: float | None = None
    regen_nu_mmh: float = 0.0
    regen_komt_binnen_min: float | None = None


@dataclass(slots=True)
class PlanParams:
    """Instelbare parameters (de number-entiteiten)."""

    factor: float
    grote_rate: float
    kleine_rate: float
    max_minuten: float
    min_mm_per_beurt: float
    regen_negeren_onder: float
    regen_vandaag_skip: float
    regen_24u_skip: float
    wind_minderen: float
    wind_stop: float
    temp_warm: float
    temp_heet: float
    temp_extreem_heet: float
    rv_laag: float
    rv_hoog: float
    uv_hoog: float
    straling_hoog: float
    bodemvocht_nat: float
    max_runtime: float
    toplaag_risico_drempel: float = 50.0
    max_beurten_per_dag: float = 4.0
    regen_soon_min: float = 90.0


@dataclass(slots=True)
class Slot:
    """Eén geplande sproeibeurt."""

    index: int
    time: str
    mm: float
    big_minutes: float
    small_minutes: float
    active: bool
    reason: str


@dataclass(slots=True)
class Plan:
    """Het volledige berekende dagplan."""

    temp_range: str
    daily_need: float
    rain_offset: float
    carry_in: float
    gross_deficit: float
    netto_mm: float
    aantal_beurten: int
    mm_per_beurt: float
    big_minutes_per_beat: float
    small_minutes_per_beat: float
    total_mm: float
    big_minutes_total: float
    small_minutes_total: float
    hard_stop_reason: str | None
    soil_reset: bool
    capped: bool
    mode: str
    dry_risk: float
    rain_credit: float
    decision: str
    reason: str
    summary: str
    slots: list[Slot] = field(default_factory=list)


def _temp_range(t: float) -> str:
    if t < 10:
        return "onder_10"
    if t < 15:
        return "10_14"
    if t < 20:
        return "15_19"
    if t < 25:
        return "20_24"
    if t < 30:
        return "25_29"
    if t < 35:
        return "30_34"
    if t < 40:
        return "35_39"
    return "40_plus"


def _nearest_class(temp: float) -> int:
    """De dichtstbijzijnde temperatuurklasse uit de advies-tabel."""
    if temp <= ADVICE_TEMPS[0]:
        return ADVICE_TEMPS[0]
    if temp >= ADVICE_TEMPS[-1]:
        return ADVICE_TEMPS[-1]
    return min(ADVICE_TEMPS, key=lambda c: (abs(c - temp), c))


def _cell(fase: str, temp: float) -> AdviceCell | None:
    """De advies-cel voor deze fase en temperatuur (None = niet sproeien)."""
    table = ADVICE.get(fase)
    if not table:
        return None
    return table.get(_nearest_class(temp))


def _cold_factor(temp: float) -> float:
    """Onder 10 °C verdampt er nauwelijks; schaal de behoefte lineair af naar 0."""
    if temp >= 10:
        return 1.0
    return max(0.0, min(1.0, (temp - 5) / 5))


def _weather_factor(inputs: PlanInputs, params: PlanParams) -> float:
    """Schaal de zonnige-dag-behoefte naar de werkelijke dag (diepe bewatering).

    De tabel gaat uit van volle zon, dus de factor blijft vooral ≤ 1: bewolkt/nat
    of vochtig weer verlaagt de behoefte; droge hitte en wind verhogen 'm iets.
    Uitzondering: op een warme, droge dag (zie HOT_DRY_*) telt de bewolkt/nat-
    melding niet mee.
    """
    wf = 1.0
    if inputs.luchtvochtigheid <= params.rv_laag and inputs.temp_max >= params.temp_warm:
        wf += 0.10
    elif inputs.luchtvochtigheid >= params.rv_hoog:
        wf -= 0.10
    hot_dry = (
        inputs.regen_24u < HOT_DRY_RAIN_24H_MM and inputs.temp_max > HOT_DRY_TEMP_C
    )
    if inputs.bewolkt_of_nat and not hot_dry:
        wf -= 0.20
    elif (
        inputs.zonnig
        or inputs.uv_index >= params.uv_hoog
        or inputs.straling >= params.straling_hoog
    ):
        wf += 0.05
    if params.wind_minderen <= inputs.wind_dag_max < params.wind_stop:
        wf += 0.05
    return _round(max(0.55, min(wf, 1.15)), 2)


def calculate_rain_credit(inputs: PlanInputs, params: PlanParams, toplaag: bool) -> float:
    """Hoeveel mm behoefte de regen van vandaag wegneemt (de regen-credit).

    Regen vóór de middag telt volledig; regen ná de middag telt voor zaad/kiemend
    minder mee, want de toplaag moet 's ochtends al vochtig zijn (een middagbui
    komt te laat om de ochtendbeurt te vervangen). Regen onder de negeer-drempel
    telt als 0.
    """
    drempel = params.regen_negeren_onder
    regen_vandaag = 0.0 if inputs.regen_vandaag < drempel else _round(inputs.regen_vandaag, 1)
    regen_middag = 0.0 if inputs.regen_vandaag < drempel else _round(inputs.regen_middag, 1)
    voor = min(regen_middag, regen_vandaag)
    na = max(0.0, regen_vandaag - voor)
    gewicht_na = 0.4 if toplaag else 0.9
    return _round(max(0.0, voor + na * gewicht_na), 1)


def calculate_top_layer_dry_risk(inputs: PlanInputs, params: PlanParams) -> float:
    """Risico (0–100) dat de bovenste 0–2 cm uitdroogt, op dít moment.

    Hoog bij warm, veel zon/straling, wind en droge lucht; lager bij bewolking.
    Gebruikt de huidige temperatuur (niet de dagmax), zodat het 's ochtends laag
    is en 's middags hoog — precies wanneer de toplaag echt uitdroogt.
    """
    temp = inputs.temp_nu if inputs.temp_nu is not None else inputs.temp_max
    temp_term = _clamp((temp - 15) / 20, 0, 1)  # 15 °C → 0, 35 °C → 1
    sun_term = max(
        _clamp(inputs.straling / max(params.straling_hoog, 1), 0, 1),
        _clamp(inputs.uv_index / max(params.uv_hoog, 1), 0, 1),
    )
    wind_term = _clamp(inputs.wind_dag_max / max(params.wind_stop, 1), 0, 1)
    dry_air_term = _clamp((100 - inputs.luchtvochtigheid) / 100, 0, 1)
    risk = 100 * (0.40 * temp_term + 0.30 * sun_term + 0.15 * wind_term + 0.15 * dry_air_term)
    if inputs.bewolkt_of_nat:
        risk *= 0.65
    return _round(_clamp(risk, 0, 100), 0)


def should_do_maintenance_watering(
    inputs: PlanInputs, params: PlanParams, dry_risk: float
) -> tuple[bool, str]:
    """Bepaal of een korte toplaag-onderhoudsbeurt nu zinvol is (met uitleg)."""
    if not inputs.automatisering_aan:
        return False, "automatisch sproeien staat uit"
    if inputs.wind_dag_max >= params.wind_stop:
        return False, f"wind te hard ({inputs.wind_dag_max} km/h) — niet sproeien"
    if inputs.regen_nu_mmh > 0:
        return False, "het regent nu — geen onderhoudsbeurt nodig"
    if (
        inputs.regen_komt_binnen_min is not None
        and inputs.regen_komt_binnen_min <= params.regen_soon_min
    ):
        return (
            False,
            f"regen binnen {int(inputs.regen_komt_binnen_min)} min verwacht — beurt uitgesteld",
        )
    if inputs.bodemvocht >= 0 and inputs.bodemvocht >= params.bodemvocht_nat:
        return False, f"bodem is nat ({inputs.bodemvocht}%) — toplaag nog vochtig"
    if dry_risk < params.toplaag_risico_drempel:
        return (
            False,
            f"toplaag-risico {dry_risk}% onder drempel {params.toplaag_risico_drempel}% "
            "— toplaag blijft voorlopig vochtig genoeg",
        )
    return (
        True,
        f"toplaag-risico {dry_risk}% ≥ drempel {params.toplaag_risico_drempel}% "
        "— korte onderhoudsbeurt om de bovenlaag vochtig te houden",
    )


def _hhmm_to_min(value: str) -> int:
    hour, minute = value.split(":")[:2]
    return int(hour) * 60 + int(minute)


def _min_to_time(total: int) -> str:
    total = max(0, min(total, 21 * 60 + 30))
    return f"{total // 60:02d}:{total % 60:02d}:00"


def _slot_time(times: tuple[str, ...], index: int, step: int = 90) -> str:
    """Tijd van beurt `index`. Stabiel per index, ook bij wisselend aantal."""
    if index < len(times):
        return f"{times[index]}:00"
    extra = index - len(times) + 1
    return _min_to_time(_hhmm_to_min(times[-1]) + extra * step)


def _beat_minutes(mm_per_beat: float, params: PlanParams) -> tuple[float, float]:
    """Looptijd grote/kleine sproeier voor een beurt van `mm_per_beat` mm."""
    big = small = 0.0
    if mm_per_beat > 0 and params.grote_rate > 0:
        big = _round(min(params.max_runtime, _round(mm_per_beat / params.grote_rate * 2, 0) / 2), 1)
    if mm_per_beat > 0 and params.kleine_rate > 0:
        small = _round(min(params.max_runtime, _round(mm_per_beat / params.kleine_rate * 2, 0) / 2), 1)
    return big, small


def _maintenance_plan(inputs: PlanInputs, params: PlanParams) -> Plan:
    """Toplaag-onderhoud voor net ingezaaid en kiemend gras (korte beurten)."""
    temp_range = _temp_range(inputs.temp_max)
    cell = _cell(inputs.fase, inputs.temp_max)
    carry = max(0.0, _round(inputs.carry_mm, 1))
    rain_credit = calculate_rain_credit(inputs, params, toplaag=True)
    dry_risk = calculate_top_layer_dry_risk(inputs, params)
    do, decision = should_do_maintenance_watering(inputs, params, dry_risk)

    n_advies = len(cell.times) if cell else 0
    n_max = int(max(1, min(SLOT_COUNT, round(params.max_beurten_per_dag))))
    count = min(n_advies, n_max) if (do and cell) else 0

    max_mm = max(
        params.min_mm_per_beurt,
        min(params.max_minuten, params.max_runtime) * params.grote_rate,
    )
    mm_per_beat = _round(min(cell.depth, max_mm), 2) if count else 0.0
    if 0 < mm_per_beat < params.min_mm_per_beurt:
        mm_per_beat = _round(params.min_mm_per_beurt, 2)
    big, small = _beat_minutes(mm_per_beat, params)

    slots: list[Slot] = []
    for i in range(count):
        slots.append(
            Slot(
                index=i + 1,
                time=_slot_time(cell.times, i),
                mm=mm_per_beat,
                big_minutes=big,
                small_minutes=small,
                active=True,
                reason=decision[:100],
            )
        )

    total_mm = _round(mm_per_beat * count, 1)
    buffer_txt = (
        f"nachtregen/regen meegeteld als buffer: {rain_credit} mm. " if rain_credit > 0 else ""
    )
    reason = f"{inputs.fase}; toplaag-onderhoud; {buffer_txt}{decision}"
    if do:
        summary = (
            f"{count}× korte beurt {mm_per_beat} mm (totaal {total_mm} mm); "
            f"toplaag-risico {dry_risk}%. {decision}"
        )[:255]
    else:
        summary = f"geen onderhoudsbeurt; toplaag-risico {dry_risk}%. {decision}"[:255]

    return Plan(
        temp_range=temp_range,
        daily_need=0.0,
        rain_offset=0.0,
        carry_in=carry,
        gross_deficit=0.0,
        netto_mm=0.0,
        aantal_beurten=count,
        mm_per_beurt=mm_per_beat,
        big_minutes_per_beat=big,
        small_minutes_per_beat=small,
        total_mm=total_mm,
        big_minutes_total=_round(big * count, 1),
        small_minutes_total=_round(small * count, 1),
        hard_stop_reason=None,
        soil_reset=False,
        capped=False,
        mode="toplaag",
        dry_risk=dry_risk,
        rain_credit=rain_credit,
        decision=decision,
        reason=reason,
        summary=summary,
        slots=slots,
    )


def _deep_plan(inputs: PlanInputs, params: PlanParams) -> Plan:
    """Diepe bewatering (jong gras, rond eerste maaibeurt, volgroeid) — waterbalans."""
    fase = inputs.fase
    temp_max = inputs.temp_max
    carry = max(0.0, _round(inputs.carry_mm, 1))
    toplaag = fase in (PHASE_NEW, PHASE_GERM)
    temp_range = _temp_range(temp_max)
    cell = _cell(fase, temp_max)

    drempel = params.regen_negeren_onder
    regen_vandaag_eff = 0.0 if inputs.regen_vandaag < drempel else _round(inputs.regen_vandaag, 1)
    regen_24u_eff = 0.0 if inputs.regen_24u < drempel else _round(inputs.regen_24u, 1)

    weather_factor = _weather_factor(inputs, params)
    cold = _cold_factor(temp_max)
    dry_risk = calculate_top_layer_dry_risk(inputs, params)

    if cell is not None:
        daily_need = _round(cell.daily_need * weather_factor * params.factor * cold, 2)
    else:
        daily_need = 0.0
    rain_offset = calculate_rain_credit(inputs, params, toplaag)

    soil_reset = False
    if fase == PHASE_MANUAL or cell is None:
        hard_stop: str | None = "fase staat op Alleen handmatig / uit"
    elif not inputs.automatisering_aan:
        hard_stop = "master staat uit"
    elif inputs.wind_dag_max >= params.wind_stop:
        hard_stop = f"wind te hard: {inputs.wind_dag_max} km/h"
    elif inputs.bodemvocht >= 0 and inputs.bodemvocht >= params.bodemvocht_nat:
        hard_stop = f"bodemvocht is hoog: {inputs.bodemvocht}%"
        soil_reset = True
    elif regen_24u_eff >= params.regen_24u_skip:
        hard_stop = f"genoeg regen laatste 24u: {regen_24u_eff} mm"
    elif regen_vandaag_eff >= params.regen_vandaag_skip:
        hard_stop = f"genoeg regen verwacht: {regen_vandaag_eff} mm"
    else:
        hard_stop = None

    frozen = fase == PHASE_MANUAL or cell is None or not inputs.automatisering_aan
    if frozen:
        gross_deficit = _round(carry, 1)
    elif soil_reset:
        gross_deficit = 0.0
    else:
        gross_deficit = _round(max(0.0, carry + daily_need - rain_offset), 1)

    beats = 0
    mm_per_beat = 0.0
    capped = False
    if hard_stop is None and cell is not None and gross_deficit >= cell.depth:
        depth = cell.depth
        n_base = len(cell.times)
        target = min(gross_deficit, depth * n_base)
        max_mm = max(
            params.min_mm_per_beurt,
            min(params.max_minuten, params.max_runtime) * params.grote_rate,
        )
        beats = max(1, min(n_base, math.ceil(target / depth)))
        if target / beats > max_mm:
            beats = math.ceil(target / max_mm)
        beats = min(beats, SLOT_COUNT)
        mm_per_beat = target / beats
        if mm_per_beat > max_mm:
            mm_per_beat = max_mm
            capped = True
        mm_per_beat = _round(mm_per_beat, 2)
        if mm_per_beat < params.min_mm_per_beurt:
            beats = 0
            mm_per_beat = 0.0

    big_minutes, small_minutes = _beat_minutes(mm_per_beat if beats else 0.0, params)
    total_mm = _round(mm_per_beat * beats, 1)

    if hard_stop is not None:
        reason = f"overgeslagen: {hard_stop}"
    elif beats == 0:
        depth_txt = cell.depth if cell is not None else 0
        reason = (
            f"vandaag niet sproeien: watertekort {gross_deficit} mm haalt de "
            f"adviesdiepte {depth_txt} mm nog niet"
        )
    else:
        reason = (
            f"{fase}; {temp_range}; dagbehoefte {daily_need} mm; weerfactor "
            f"{weather_factor}; tekort {gross_deficit} mm; {beats}× {mm_per_beat} mm "
            f"gepland ({total_mm} mm)"
        )
    if capped:
        reason += " (beperkt door max minuten/runtime — verhoog die voor diepere beurten)"

    slots: list[Slot] = []
    if cell is not None:
        for i in range(beats):
            slots.append(
                Slot(
                    index=i + 1,
                    time=_slot_time(cell.times, i),
                    mm=mm_per_beat,
                    big_minutes=big_minutes,
                    small_minutes=small_minutes,
                    active=True,
                    reason=reason[:100],
                )
            )

    summary = (
        f"{beats}× {mm_per_beat} mm/beurt; totaal {total_mm} mm; "
        f"groot {big_minutes}m, klein {small_minutes}m. {reason}."
    )[:255]

    return Plan(
        temp_range=temp_range,
        daily_need=daily_need,
        rain_offset=rain_offset,
        carry_in=carry,
        gross_deficit=gross_deficit,
        netto_mm=gross_deficit,
        aantal_beurten=beats,
        mm_per_beurt=mm_per_beat,
        big_minutes_per_beat=big_minutes,
        small_minutes_per_beat=small_minutes,
        total_mm=total_mm,
        big_minutes_total=_round(big_minutes * beats, 1),
        small_minutes_total=_round(small_minutes * beats, 1),
        hard_stop_reason=hard_stop,
        soil_reset=soil_reset,
        capped=capped,
        mode="diep",
        dry_risk=dry_risk,
        rain_credit=rain_offset,
        decision=reason,
        reason=reason,
        summary=summary,
        slots=slots,
    )


def calculate(inputs: PlanInputs, params: PlanParams) -> Plan:
    """Bereken het dagplan; kiest toplaag-onderhoud of diepe bewatering per fase."""
    if inputs.fase in TOPLAAG_PHASES:
        return _maintenance_plan(inputs, params)
    return _deep_plan(inputs, params)
