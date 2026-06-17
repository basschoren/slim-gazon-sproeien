"""Berekening van het slimme dagplan.

Dit is een getrouwe vertaling van de Jinja-logica uit het oorspronkelijke
`slim_gazon_sproeien.yaml` package naar pure Python, zodat het gedrag identiek
is maar makkelijk te onderhouden en te testen.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from .const import (
    PHASE_ESTABLISHED,
    PHASE_GERM,
    PHASE_MANUAL,
    PHASE_NEW,
    PHASE_YOUNG,
    SLOT_COUNT,
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


@dataclass(slots=True)
class PlanParams:
    """Instelbare parameters (de input_number waarden)."""

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
    base_total_mm: float
    bruto_mm: float
    regen_reductie: float
    netto_mm: float
    aantal_beurten: int
    mm_per_beurt: float
    big_minutes_per_beat: float
    small_minutes_per_beat: float
    total_mm: float
    big_minutes_total: float
    small_minutes_total: float
    hard_stop_reason: str | None
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


def _base_total_mm(t: float) -> float:
    if t < 10:
        return 0.5
    if t < 15:
        return 1.5
    if t < 20:
        return 3.0
    if t < 25:
        return 4.5
    if t < 30:
        return 6.0
    if t < 35:
        return 8.5
    if t < 40:
        return 12.0
    return 14.0


def _base_beurten(t: float) -> int:
    if t < 10:
        return 1
    if t < 15:
        return 2
    if t < 20:
        return 2
    if t < 25:
        return 3
    if t < 30:
        return 4
    if t < 35:
        return 5
    if t < 40:
        return 6
    return 7


def _phase_factor(fase: str) -> float:
    return {
        PHASE_NEW: 1.0,
        PHASE_GERM: 0.85,
        PHASE_YOUNG: 0.70,
        PHASE_ESTABLISHED: 1.0,
    }.get(fase, 0.0)


def _slot_times(fase: str, temp_range: str) -> list[str]:
    """Bepaal de 8 sproeitijden op basis van fase en temperatuurklasse."""
    young_or_est = fase in (PHASE_YOUNG, PHASE_ESTABLISHED)

    if young_or_est:
        slot1 = "06:30:00"
    elif temp_range == "onder_10":
        slot1 = "09:00:00"
    elif temp_range in ("10_14", "15_19"):
        slot1 = "06:00:00"
    else:
        slot1 = "05:00:00"

    if young_or_est:
        slot2 = "18:30:00"
    elif temp_range == "10_14":
        slot2 = "16:30:00"
    elif temp_range == "15_19":
        slot2 = "18:00:00"
    elif temp_range == "20_24":
        slot2 = "13:00:00"
    elif temp_range == "25_29":
        slot2 = "10:00:00"
    elif temp_range == "30_34":
        slot2 = "09:30:00"
    elif temp_range == "35_39":
        slot2 = "08:30:00"
    else:
        slot2 = "08:00:00"

    if temp_range == "20_24":
        slot3 = "18:30:00"
    elif temp_range == "25_29":
        slot3 = "14:00:00"
    elif temp_range == "30_34":
        slot3 = "12:30:00"
    elif temp_range == "35_39":
        slot3 = "11:30:00"
    else:
        slot3 = "10:30:00"

    if temp_range == "25_29":
        slot4 = "18:30:00"
    elif temp_range == "30_34":
        slot4 = "15:30:00"
    elif temp_range == "35_39":
        slot4 = "14:30:00"
    else:
        slot4 = "13:00:00"

    if temp_range == "30_34":
        slot5 = "18:30:00"
    elif temp_range == "35_39":
        slot5 = "17:00:00"
    else:
        slot5 = "15:30:00"

    slot6 = "19:30:00" if temp_range == "35_39" else "17:30:00"
    slot7 = "20:00:00"
    slot8 = "21:30:00"

    return [slot1, slot2, slot3, slot4, slot5, slot6, slot7, slot8]


def calculate(inputs: PlanInputs, params: PlanParams) -> Plan:
    """Bereken het dagplan."""
    fase = inputs.fase
    temp_max = inputs.temp_max
    toplaag = fase in (PHASE_NEW, PHASE_GERM)

    temp_range = _temp_range(temp_max)
    base_total_mm = _base_total_mm(temp_max)
    base_beurten = _base_beurten(temp_max)
    phase_factor = _phase_factor(fase)

    # Effectieve regen: alles onder de negeer-drempel telt als 0.
    drempel = params.regen_negeren_onder
    regen_vandaag_eff = 0.0 if inputs.regen_vandaag < drempel else _round(inputs.regen_vandaag, 1)
    regen_24u_eff = 0.0 if inputs.regen_24u < drempel else _round(inputs.regen_24u, 1)
    regen_middag_eff = 0.0 if inputs.regen_vandaag < drempel else _round(inputs.regen_middag, 1)

    # Weer-factor.
    wf = 1.0
    if inputs.luchtvochtigheid <= params.rv_laag and temp_max >= params.temp_warm:
        wf += 0.10
    elif inputs.luchtvochtigheid >= params.rv_hoog:
        wf -= 0.10
    if inputs.uv_index >= params.uv_hoog or inputs.straling >= params.straling_hoog:
        wf += 0.10
    elif inputs.bewolkt_of_nat:
        wf -= 0.10
    if params.wind_minderen <= inputs.wind_dag_max < params.wind_stop:
        wf += 0.05
    weather_factor = _round(max(0.5, min(wf, 1.35)), 2)

    # Basis-mm voor deze fase.
    if fase == PHASE_ESTABLISHED:
        if (regen_24u_eff + regen_vandaag_eff) >= params.regen_vandaag_skip:
            basis_mm_fase = 0.0
        elif temp_max >= params.temp_extreem_heet:
            basis_mm_fase = 15.0
        elif temp_max >= params.temp_heet:
            basis_mm_fase = 12.0
        elif temp_max >= params.temp_warm:
            basis_mm_fase = 10.0
        else:
            basis_mm_fase = 0.0
    else:
        basis_mm_fase = _round(base_total_mm * phase_factor * weather_factor * params.factor, 1)

    # Regenreductie.
    past_weight = 0.45 if toplaag else 0.85
    if inputs.forecast_items_count > 0:
        na_middag = max(0.0, regen_vandaag_eff - regen_middag_eff)
        expected = regen_middag_eff * 0.80 + na_middag * (0.30 if toplaag else 0.75)
    else:
        expected = regen_vandaag_eff * (0.40 if toplaag else 0.75)
    raw_reductie = regen_24u_eff * past_weight + expected
    max_reductie = basis_mm_fase * (0.75 if toplaag and temp_max >= params.temp_warm else 1.0)
    regen_reductie = _round(max(0.0, min(raw_reductie, max_reductie)), 1)

    # Harde stop-redenen.
    hard_stop: str | None
    if fase == PHASE_MANUAL:
        hard_stop = "fase staat op Alleen handmatig / uit"
    elif not inputs.automatisering_aan:
        hard_stop = "master staat uit"
    elif inputs.wind_dag_max >= params.wind_stop:
        hard_stop = f"wind te hard: {inputs.wind_dag_max} km/h"
    elif inputs.bodemvocht >= params.bodemvocht_nat and inputs.bodemvocht >= 0:
        hard_stop = f"bodemvocht is hoog: {inputs.bodemvocht}%"
    elif fase in (PHASE_YOUNG, PHASE_ESTABLISHED) and regen_24u_eff >= params.regen_24u_skip:
        hard_stop = f"genoeg regen laatste 24u: {regen_24u_eff} mm"
    elif fase == PHASE_ESTABLISHED and regen_vandaag_eff >= params.regen_vandaag_skip:
        hard_stop = f"genoeg regen verwacht: {regen_vandaag_eff} mm"
    else:
        hard_stop = None

    bruto_mm = _round(basis_mm_fase, 1)
    netto_mm_raw = _round(basis_mm_fase - regen_reductie, 1)
    netto_mm = 0.0 if hard_stop is not None else _round(max(0.0, netto_mm_raw), 1)

    # Limieten per fase.
    if fase == PHASE_NEW:
        max_groot = 25.0
        max_klein = 5.0
    elif fase == PHASE_GERM:
        max_groot = 28.0
        max_klein = 6.0
    elif fase == PHASE_YOUNG:
        max_groot = 35.0
        max_klein = 7.0
    else:
        max_groot = params.max_minuten
        max_klein = 10.0

    # Basis-aantal beurten per fase.
    if fase == PHASE_NEW:
        basis_beurten_fase = base_beurten
    elif fase == PHASE_GERM:
        basis_beurten_fase = max(1, base_beurten - (1 if base_beurten >= 4 else 0))
    elif fase == PHASE_YOUNG:
        basis_beurten_fase = max(1, min(3, base_beurten - 2))
    elif fase == PHASE_ESTABLISHED:
        basis_beurten_fase = 2 if netto_mm >= 12 else 1 if netto_mm >= 8 else 0
    else:
        basis_beurten_fase = 0

    max_mm_per_slot = _round(min(max_groot * params.grote_rate, max_klein * params.kleine_rate), 2)

    if netto_mm <= 0 or max_mm_per_slot <= 0:
        benodigde_door_max = 0
    else:
        benodigde_door_max = math.ceil(netto_mm / max_mm_per_slot)

    if netto_mm < params.min_mm_per_beurt:
        aantal_beurten = 0
    else:
        aantal_beurten = min(SLOT_COUNT, max(basis_beurten_fase, benodigde_door_max))

    if aantal_beurten > 0:
        mm_per_beurt = _round(min(netto_mm / aantal_beurten, max_mm_per_slot), 2)
    else:
        mm_per_beurt = 0.0

    total_mm = _round(mm_per_beurt * aantal_beurten, 1)

    if aantal_beurten > 0 and params.grote_rate > 0:
        minutes = mm_per_beurt / params.grote_rate
        big_minutes = _round(max(0.0, min(max_groot, _round(minutes * 2, 0) / 2)), 1)
    else:
        big_minutes = 0.0

    if aantal_beurten > 0 and params.kleine_rate > 0:
        minutes = mm_per_beurt / params.kleine_rate
        small_minutes = _round(max(0.0, min(max_klein, _round(minutes * 2, 0) / 2)), 1)
    else:
        small_minutes = 0.0

    # Reden-tekst.
    if hard_stop is not None:
        reason = f"overgeslagen: {hard_stop}"
    elif netto_mm < params.min_mm_per_beurt:
        reason = f"overgeslagen: netto behoefte {netto_mm} mm is te laag"
    else:
        reason = (
            f"{fase}; {temp_range}; basis {base_total_mm} mm; fase/weer {bruto_mm} mm; "
            f"regen reductie {regen_reductie} mm; gepland {total_mm} mm"
        )

    times = _slot_times(fase, temp_range)
    slots: list[Slot] = []
    for i in range(1, SLOT_COUNT + 1):
        active = i <= aantal_beurten
        slots.append(
            Slot(
                index=i,
                time=times[i - 1],
                mm=mm_per_beurt if active else 0.0,
                big_minutes=big_minutes if active else 0.0,
                small_minutes=small_minutes if active else 0.0,
                active=active,
                reason=reason[:100] if active else "",
            )
        )

    summary = (
        f"{aantal_beurten}x; {mm_per_beurt} mm/beurt; totaal {total_mm} mm; "
        f"groot {big_minutes}m, klein {small_minutes}m. {reason}."
    )[:255]

    return Plan(
        temp_range=temp_range,
        base_total_mm=base_total_mm,
        bruto_mm=bruto_mm,
        regen_reductie=regen_reductie,
        netto_mm=netto_mm,
        aantal_beurten=aantal_beurten,
        mm_per_beurt=mm_per_beurt,
        big_minutes_per_beat=big_minutes,
        small_minutes_per_beat=small_minutes,
        total_mm=total_mm,
        big_minutes_total=_round(big_minutes * aantal_beurten, 1),
        small_minutes_total=_round(small_minutes * aantal_beurten, 1),
        hard_stop_reason=hard_stop,
        reason=reason,
        summary=summary,
        slots=slots,
    )
