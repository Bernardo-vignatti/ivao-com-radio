"""Lista de ATC online, vinda da Whazzup publica da IVAO.

Quem busca e' o servidor, nao o celular: uma requisicao a cada 15 s em vez
de uma por dispositivo, e a lista chega no telefone ja filtrada e ordenada
por distancia.
"""

import asyncio
import logging
import math

import httpx

log = logging.getLogger("whazzup")

URL = "https://api.ivao.aero/v2/tracker/whazzup"
EARTH_NM = 3440.065

POSITION_LABEL = {
    "DEL": "clearance",
    "GND": "solo",
    "TWR": "torre",
    "APP": "aproximacao",
    "DEP": "saida",
    "CTR": "centro",
    "FSS": "informacao",
    "RDO": "radio",
}


def distance_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return EARTH_NM * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


class WhazzupFeed:
    def __init__(self, cfg: dict):
        self.interval = float(cfg.get("whazzup_interval_s", 15))
        self.radius = float(cfg.get("whazzup_radius_nm", 250))
        self.limit = int(cfg.get("whazzup_max_stations", 12))
        self.raw: list[dict] = []
        self.error: str | None = None

    async def run(self, stop: asyncio.Event) -> None:
        async with httpx.AsyncClient(timeout=10.0) as client:
            while not stop.is_set():
                try:
                    resp = await client.get(URL)
                    resp.raise_for_status()
                    self.raw = self._parse(resp.json())
                    self.error = None
                except Exception as exc:
                    self.error = str(exc)
                    log.warning("whazzup falhou: %s", exc)
                try:
                    await asyncio.wait_for(stop.wait(), timeout=self.interval)
                except asyncio.TimeoutError:
                    pass

    @staticmethod
    def _parse(payload: dict) -> list[dict]:
        out = []
        for atc in payload.get("clients", {}).get("atcs", []) or []:
            session = atc.get("atcSession") or {}
            track = atc.get("lastTrack") or {}
            freq = session.get("frequency")
            lat, lon = track.get("latitude"), track.get("longitude")
            callsign = atc.get("callsign")
            if not callsign or freq is None or lat is None or lon is None:
                continue
            suffix = callsign.rsplit("_", 1)[-1].upper()
            out.append(
                {
                    "callsign": callsign,
                    "frequency": round(float(freq), 3),
                    "lat": float(lat),
                    "lon": float(lon),
                    "role": POSITION_LABEL.get(suffix, session.get("position") or ""),
                }
            )
        return out

    def nearby(self, lat: float | None, lon: float | None) -> list[dict]:
        if not self.raw:
            return []
        if lat is None or lon is None:
            return [dict(s, distance=None) for s in self.raw[: self.limit]]
        scored = []
        for station in self.raw:
            d = distance_nm(lat, lon, station["lat"], station["lon"])
            if d <= self.radius:
                scored.append(dict(station, distance=round(d)))
        scored.sort(key=lambda s: s["distance"])
        return scored[: self.limit]
