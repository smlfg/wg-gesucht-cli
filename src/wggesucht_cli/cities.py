"""Stadt-Mapping und URL-Bau für wg-gesucht.de."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

# WG-Gesucht verwendet Slugs ohne Umlaute/ß: ä->ae, ö->oe, ü->ue, ß->ss
_UMLAUT = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss"})

_DATA_PATH = Path(__file__).resolve().parent / "data" / "cities.json"


def _load() -> dict:
    return json.loads(_DATA_PATH.read_text(encoding="utf-8"))


def _normalize(name: str) -> str:
    return name.strip().translate(_UMLAUT)


def resolve_city(name: str) -> Optional[dict]:
    """Liefert {id, slug} für einen Stadtnamen oder None."""
    norm = _normalize(name)
    cities = _load()
    if norm in cities:
        return cities[norm]
    # Fallback: case-insensitive
    lower = norm.lower()
    for k, v in cities.items():
        if k.lower() == lower:
            return v
    return None


def list_cities() -> list[str]:
    return sorted(_load().keys())


# URL-Bau: /wg-zimmer-in-<Stadt>.<CityID>.0.1.0.html
# --rooms wg:      /wg-zimmer-in-<Stadt>.<ID>.0.1.0.html
# --rooms 1zimmer: /1-zimmer-wohnungen-in-<Stadt>.<ID>.1.1.0.html
# --rooms wohnung: /wohnungen-in-<Stadt>.<ID>.2.1.0.html
# --rooms haus:    /haeuser-in-<Stadt>.<ID>.3.1.0.html
def build_search_url(city: dict, rooms: str = "wg", max_rent: int | None = None,
                     min_size: int | None = None, radius: int | None = None) -> str:
    slug = city["slug"]
    cid = city["id"]
    if rooms == "wg":
        path = f"/wg-zimmer-in-{slug}.{cid}.0.1.0.html"
    elif rooms == "1zimmer":
        path = f"/1-zimmer-wohnungen-in-{slug}.{cid}.1.1.0.html"
    elif rooms == "wohnung":
        path = f"/wohnungen-in-{slug}.{cid}.2.1.0.html"
    elif rooms == "haus":
        path = f"/haeuser-in-{slug}.{cid}.3.1.0.html"
    else:
        raise ValueError(f"unknown rooms: {rooms}")
    qs: list[str] = []
    if max_rent is not None:
        qs.append(f"rMax={max_rent}")
    if min_size is not None:
        qs.append(f"sizeMin={min_size}")
    if radius is not None:
        qs.append(f"rad={radius}")
    return "https://www.wg-gesucht.de" + path + ("?" + "&".join(qs) if qs else "")
