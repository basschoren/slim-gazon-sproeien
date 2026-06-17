"""Decodeert de Buienalarm/Buienradar nowcast-sensor.

Werkt met de sensor uit de integratie `aex351/home-assistant-neerslag-app`
(`sensor.neerslag_buienalarm_regen_data`). Die heeft een attribuut `data` met:

- ``start``: starttijd van de reeks (epoch seconden; ms wordt ook herkend)
- ``delta``: interval tussen de samples (seconden; ms wordt ook herkend)
- ``precip``: lijst Buienradar-codes (0-255), waarbij
  ``mm/h = 10 ** ((code - 109) / 32)`` en code 0 = droog.

Hiermee kunnen we vooruitkijken: hoeveel regen valt er de komende uren en
hoelaat begint het. Pure functies zonder Home Assistant-imports, zodat dit
los te testen is.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class NowcastResult:
    """Samenvatting van de nowcast."""

    available: bool
    horizon_min: int = 0
    window_mm: float = 0.0
    today_mm: float = 0.0
    before_noon_mm: float = 0.0
    minutes_until_rain: int | None = None


def decode_precip_code(code: object) -> float:
    """Zet een Buienradar-code (0-255) om naar mm/h."""
    try:
        value = float(code)
    except (TypeError, ValueError):
        return 0.0
    if value <= 0:
        return 0.0
    return 10 ** ((value - 109) / 32)


def _inner(attributes: Mapping) -> Mapping:
    """De sensor levert {"data": {...}}; val terug op platte attributen."""
    nested = attributes.get("data")
    if isinstance(nested, Mapping):
        return nested
    return attributes


def parse_nowcast(
    attributes: Mapping, now: datetime, onset_mmh: float = 0.1
) -> NowcastResult:
    """Bereken verwachte regen uit de nowcast vanaf ``now``.

    ``now`` moet timezone-aware zijn (lokale tijd); de epoch-timestamps worden
    naar diezelfde tijdzone omgezet voor de dag/voor-de-middag indeling.
    """
    data = _inner(attributes)
    precip = data.get("precip")
    start = data.get("start")
    if not precip or start is None:
        return NowcastResult(available=False)

    try:
        start_s = float(start)
    except (TypeError, ValueError):
        return NowcastResult(available=False)
    if start_s > 1e11:  # milliseconden
        start_s /= 1000.0

    try:
        delta_s = float(data.get("delta") or 0)
    except (TypeError, ValueError):
        delta_s = 0.0
    if delta_s > 3600:  # milliseconden
        delta_s /= 1000.0
    if delta_s <= 0:
        delta_s = 300.0  # val terug op 5 minuten

    now_ts = now.timestamp()
    hours_per_sample = delta_s / 3600.0
    tz = now.tzinfo

    window_mm = 0.0
    today_mm = 0.0
    before_noon_mm = 0.0
    minutes_until_rain: int | None = None

    for index, code in enumerate(precip):
        sample_ts = start_s + index * delta_s
        # Sla samples over die volledig in het verleden liggen.
        if sample_ts + delta_s <= now_ts:
            continue
        rate = decode_precip_code(code)
        mm = rate * hours_per_sample
        window_mm += mm

        local = datetime.fromtimestamp(sample_ts, tz=tz)
        if local.date() == now.date():
            today_mm += mm
            if local.hour < 12:
                before_noon_mm += mm

        if (
            minutes_until_rain is None
            and rate >= onset_mmh
            and sample_ts >= now_ts
        ):
            minutes_until_rain = max(0, round((sample_ts - now_ts) / 60))

    horizon_min = round(len(precip) * delta_s / 60)

    return NowcastResult(
        available=True,
        horizon_min=horizon_min,
        window_mm=round(window_mm, 2),
        today_mm=round(today_mm, 2),
        before_noon_mm=round(before_noon_mm, 2),
        minutes_until_rain=minutes_until_rain,
    )
