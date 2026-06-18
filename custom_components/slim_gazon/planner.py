"""Berekening van het slimme dagplan (waterbalans).

De basis is het sproeiadvies uit `sproeiadvies_gazon_temperatuurklassen.xlsx`
(zie `ADVICE` in const.py): voor een **zonnige dag** geeft de tabel per
temperatuurklasse en grasstadium de dagbehoefte (mm/dag) en de adviesdiepte per
beurt. Sommige stadia zijn "per week" (diep & weinig), andere "per dag".

Bovenop die basis ligt een **slim, adaptief algoritme**:

* een **weerfactor** schaalt de zonnige-dag-behoefte naar de werkelijke dag op
  basis van bewolking/zon, luchtvochtigheid en wind;
* een **lopende waterbalans** (tekort) telt elke dag de behoefte op en trekt de
  gevallen/verwachte regen af. Pas wanneer het tekort de adviesdiepte bereikt,
  wordt er gesproeid. Zo ontstaat vanzelf de juiste frequentie: bij zaad meerdere
  beurten per dag, bij volgroeid gras een diepe beurt ~2× per week.

De waterbalans-staat (het tekort dat tussen dagen wordt meegenomen, en het al
gegeven water van vandaag) leeft in de coördinator; deze module is een pure
functie: gegeven het tekort van vandaag en de meetwaarden, geeft het het plan.
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


def _round(value: float, ndigits: int = 0) -> float:
    """Rond af zoals Jinja's `round` filter (half naar boven)."""
    quant = Decimal(1).scaleb(-ndigits)
    return float(Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP))


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


# Op een warme, droge dag telt de bewolkt/nat-melding niet mee in de weerfactor:
# als het amper geregend heeft (< 2 mm in 24u) én het warm is (> 25 °C), blijft de
# verdamping hoog ondanks wat wolken — dan niet 20% afschalen.
HOT_DRY_RAIN_24H_MM = 2.0
HOT_DRY_TEMP_C = 25.0


def _weather_factor(inputs: PlanInputs, params: PlanParams) -> float:
    """Schaal de zonnige-dag-behoefte naar de werkelijke dag.

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


def _rain_offset(regen_vandaag: float, regen_middag: float, toplaag: bool) -> float:
    """Hoeveel mm behoefte de regen van vandaag wegneemt.

    Regen vóór de middag telt volledig; regen ná de middag telt voor zaad/kiemend
    minder mee, want de toplaag moet 's ochtends al vochtig zijn (de middagbui
    komt te laat om de ochtendbeurt te vervangen).
    """
    voor = min(regen_middag, regen_vandaag)
    na = max(0.0, regen_vandaag - voor)
    gewicht_na = 0.4 if toplaag else 0.9
    return _round(max(0.0, voor + na * gewicht_na), 1)


def _hhmm_to_min(value: str) -> int:
    hour, minute = value.split(":")[:2]
    return int(hour) * 60 + int(minute)


def _min_to_time(total: int) -> str:
    total = max(0, min(total, 21 * 60 + 30))
    return f"{total // 60:02d}:{total % 60:02d}:00"


def _slot_time(times: tuple[str, ...], index: int, step: int = 90) -> str:
    """Tijd van beurt `index`. Stabiel per index, ook bij wisselend aantal.

    Tot het aantal aanbevolen momenten gebruiken we die exact; daarboven (een
    diepe beurt die gesplitst wordt om de veiligheidslimiet te respecteren)
    spreiden we extra beurten met vaste stappen over de ochtend.
    """
    if index < len(times):
        return f"{times[index]}:00"
    extra = index - len(times) + 1
    return _min_to_time(_hhmm_to_min(times[-1]) + extra * step)


def calculate(inputs: PlanInputs, params: PlanParams) -> Plan:
    """Bereken het dagplan op basis van de waterbalans."""
    fase = inputs.fase
    temp_max = inputs.temp_max
    carry = max(0.0, _round(inputs.carry_mm, 1))
    toplaag = fase in (PHASE_NEW, PHASE_GERM)
    temp_range = _temp_range(temp_max)
    cell = _cell(fase, temp_max)

    # Effectieve regen: alles onder de negeer-drempel telt als 0.
    drempel = params.regen_negeren_onder
    regen_vandaag_eff = 0.0 if inputs.regen_vandaag < drempel else _round(inputs.regen_vandaag, 1)
    regen_24u_eff = 0.0 if inputs.regen_24u < drempel else _round(inputs.regen_24u, 1)
    regen_middag_eff = 0.0 if inputs.regen_vandaag < drempel else _round(inputs.regen_middag, 1)

    weather_factor = _weather_factor(inputs, params)
    cold = _cold_factor(temp_max)

    if cell is not None:
        daily_need = _round(cell.daily_need * weather_factor * params.factor * cold, 2)
    else:
        daily_need = 0.0
    rain_offset = _rain_offset(regen_vandaag_eff, regen_middag_eff, toplaag)

    # Harde stop-redenen.
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

    # Het lopende tekort. Bij master uit / alleen-handmatig bevriezen we het
    # tekort (geen opbouw). Bij natte bodem is de grond de waarheid → reset.
    frozen = fase == PHASE_MANUAL or cell is None or not inputs.automatisering_aan
    if frozen:
        gross_deficit = _round(carry, 1)
    elif soil_reset:
        gross_deficit = 0.0
    else:
        gross_deficit = _round(max(0.0, carry + daily_need - rain_offset), 1)

    # Beurten bepalen (alleen als er geen harde stop is en het tekort de
    # adviesdiepte haalt).
    beats = 0
    mm_per_beat = 0.0
    capped = False
    if hard_stop is None and cell is not None and gross_deficit >= cell.depth:
        depth = cell.depth
        n_base = len(cell.times)
        target = min(gross_deficit, depth * n_base)
        # Max mm per beurt door de veiligheids-/looptijdlimiet (grote sproeier is
        # het traagst en dus bepalend).
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

    big_minutes = 0.0
    small_minutes = 0.0
    if beats > 0:
        if params.grote_rate > 0:
            big_minutes = _round(
                min(params.max_runtime, _round(mm_per_beat / params.grote_rate * 2, 0) / 2), 1
            )
        if params.kleine_rate > 0:
            small_minutes = _round(
                min(params.max_runtime, _round(mm_per_beat / params.kleine_rate * 2, 0) / 2), 1
            )

    total_mm = _round(mm_per_beat * beats, 1)

    # Reden-tekst.
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
        reason=reason,
        summary=summary,
        slots=slots,
    )
