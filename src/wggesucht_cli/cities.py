"""Stadt-Mapping und URL-Bau für wg-gesucht.de.

Die Liste der unterstützten URL-Parameter wurde am 2026-10-13 aus dem
echten Suchformular (https://www.wg-gesucht.de/wg-zimmer-in-<Stadt>...) abgeleitet.
Sollte wg-gesucht die Parameternamen ändern, schlägt der Aufruf fehl –
`build_search_url` ist absichtlich dünn: nur Werte, die der Nutzer gesetzt
hat, landen in der Query.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import quote

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


# Whitelist der erlaubten WG-Typen (wg-gesucht-IDs)
WG_FLATMATES_GENDER = {1: "Frau", 2: "Mann", 4: "Divers", 5: "keine Angabe"}
WG_SEARCHED_GENDER = {1: "Frau", 2: "Mann", 3: "Divers", 4: "keine Angabe"}
RENT_TYPES = {1: "befristet", 2: "unbefristet", 3: "uebernachtung"}
FURNISHED = {1: "ja", 2: "nein"}
SMOKING = {1: "erlaubt", 2: "nicht_erwuenscht", 3: "eigenes_zimmer", 4: "balkon"}
PETS = {1: "ja", 2: "nein"}
KITCHEN = {1: "ja", 2: "nein"}
EXCHANGE = {1: "ja", 2: "nein"}


def _join_list(values: Iterable[int | str]) -> str:
    """Komma-Liste (wg-gesucht-Trenner für Mehrfachauswahl)."""
    return ",".join(str(v) for v in values if v not in (None, ""))


def _calendar_iso(yyyy: str, mm: str, dd: str) -> str:
    """Liefert ISO YYYY-MM-DD nach Kalenderprüfung."""
    iso = f"{yyyy}-{mm}-{dd}"
    try:
        datetime.strptime(iso, "%Y-%m-%d")
    except ValueError:
        raise ValueError(f"ungültiges Kalenderdatum: {iso}") from None
    return iso


def _date_ddmmyyyy(value: str) -> str:
    """Akzeptiert ISO (YYYY-MM-DD) oder deutsch (DD.MM.YYYY) und liefert DD.MM.YYYY."""
    s = (value or "").strip()
    if not s:
        raise ValueError("leeres Datum")
    # ISO?
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        yyyy, mm, dd = s[0:4], s[5:7], s[8:10]
    elif len(s) >= 10 and s[2] == "." and s[5] == ".":
        dd, mm, yyyy = s[0:2], s[3:5], s[6:10]
    else:
        raise ValueError(f"unerwartetes Datumsformat: {value!r}")
    if not (yyyy.isdigit() and mm.isdigit() and dd.isdigit()):
        raise ValueError(f"Datums-Bestandteile nicht numerisch: {value!r}")
    _calendar_iso(yyyy, mm, dd)
    return f"{dd}.{mm}.{yyyy}"


# URL-Bau: /wg-zimmer-in-<Stadt>.<CityID>.0.1.0.html
# --rooms wg:      /wg-zimmer-in-<Stadt>.<ID>.0.1.0.html
# --rooms 1zimmer: /1-zimmer-wohnungen-in-<Stadt>.<ID>.1.1.0.html
# --rooms wohnung: /wohnungen-in-<Stadt>.<ID>.2.1.0.html
# --rooms haus:    /haeuser-in-<Stadt>.<ID>.3.1.0.html
#
# Suchformular-Parameternamen (aus Live-Form, 2026-10-13):
#   rMax / rMin       Miete (€)
#   sizeMin / sizeMax  Größe (m²)
#   dFr / dTo         Einzug von / bis (DD.MM.YYYY)
#   sMin / sMax       Zimmermerkmale 1..4 (Zimmerzahl bei Wohnungen)
#   rent_types[]      1=befristet, 2=unbefristet, 3=Übernachtung
#   wgFla             Mitbewohner-Geschlecht (1=Frau, 2=Mann, 4=Divers, 5=k.A.)
#   wgSea             gesuchtes Geschlecht (1=Frau, 2=Mann, 3=Divers, 4=k.A.)
#   wgMnF / wgMxT     Alter der Mitbewohner (von/bis)
#   wgArt             WG-Art-Mehrfachauswahl: 0=Zweck-WG, 1=Studenten,
#                     2=Frauen-WG, 6=Berufstätigen, 11=keine Zweck,
#                     12=gemischte, 16=LGBTQIA+, 19=Internationals welcome
#   wgFlaFrom..       nicht verwendet; Mitbewohner-Anzahl wird über
#                     wg_flatmates_from/to (1=2er, 2=3er, …) gesteuert
#   fur               möbliert (1/2)
#   wgSmo             Rauchen (1/2/3/4)
#   districts         Stadtteil-IDs (kommasepariert)
#   rad               Radius (Meter; Werte 500, 1000, …, 30000)
#   sin               Anzeigen seit (Tage/Index)
#   exc               Tausch gegen andere Wohnung (1/2)
#   pet               Haustiere erlaubt
#   pets_present      Haustiere vorhanden
#   kit               eigene Küche (1/2)
#   flo               Etage (Index)
#   han               rollstuhlgerecht (1)
#   bal_or_ter        Balkon / Terrasse (1)
#   gar               Garten
#   onl_tour          Online-Besichtigung
#   img_only          nur Anzeigen mit Bildern
#   radAdd/radLat/radLng/radDis   Radialsuche (für später)
def build_search_url(
    city: dict,
    rooms: str = "wg",
    max_rent: int | None = None,
    min_rent: int | None = None,
    min_size: int | None = None,
    max_size: int | None = None,
    radius: int | None = None,
    move_in_from: str | None = None,
    move_in_to: str | None = None,
    rent_types: Iterable[int] | None = None,
    wg_gender: int | None = None,
    wg_searched_gender: int | None = None,
    flatmate_age_min: int | None = None,
    flatmate_age_max: int | None = None,
    flatmates_min: int | None = None,
    flatmates_max: int | None = None,
    flatshare_types: Iterable[int] | None = None,
    furnished: int | None = None,
    smoking: int | None = None,
    pets_allowed: int | None = None,
    pets_present: int | None = None,
    kitchen: int | None = None,
    district_ids: Iterable[int | str] | None = None,
    offers_since: int | None = None,
    exchange: int | None = None,
    floor: int | None = None,
    handicapped: bool = False,
    balcony: bool = False,
    garden: bool = False,
    online_tour: bool = False,
    images_only: bool = False,
) -> str:
    """Baut die Such-URL mit den echten Parametern des wg-gesucht-Formulars.

    Nicht gesetzte Argumente tauchen nicht in der URL auf.
    """
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

    qs: list[tuple[str, str]] = []
    if max_rent is not None:
        qs.append(("rMax", str(max_rent)))
    if min_rent is not None:
        qs.append(("rMin", str(min_rent)))
    if min_size is not None:
        qs.append(("sizeMin", str(min_size)))
    if max_size is not None:
        qs.append(("sizeMax", str(max_size)))
    if radius is not None:
        qs.append(("rad", str(radius)))
    if move_in_from:
        # wg-gesucht-Form: User-Eingabe landet in 'dFrDe' (deutsches Datum
        # DD.MM.YYYY) und triggert die Filterung; 'dFr' (hidden) wird
        # per JS gesynct und liefert aktuell HTTP 500 bei GET-Requests.
        qs.append(("dFrDe", _date_ddmmyyyy(move_in_from)))
    if move_in_to:
        qs.append(("dToDe", _date_ddmmyyyy(move_in_to)))
    rt = _join_list(rent_types or [])
    if rt:
        qs.append(("rent_types[]", rt))
    if wg_gender is not None:
        qs.append(("wgFla", str(wg_gender)))
    if wg_searched_gender is not None:
        qs.append(("wgSea", str(wg_searched_gender)))
    if flatmate_age_min is not None:
        qs.append(("wgMnF", str(flatmate_age_min)))
    if flatmate_age_max is not None:
        qs.append(("wgMxT", str(flatmate_age_max)))
    if flatmates_min is not None:
        # Form: 1=2er, 2=3er, … 7=8er, 8=9er (Index im Formular)
        qs.append(("wg_flatmates_from", str(flatmates_min)))
    if flatmates_max is not None:
        qs.append(("wg_flatmates_to", str(flatmates_max)))
    fs = _join_list(flatshare_types or [])
    if fs:
        qs.append(("wgArt", fs))
    if furnished is not None:
        qs.append(("fur", str(furnished)))
    if smoking is not None:
        qs.append(("wgSmo", str(smoking)))
    if pets_allowed is not None:
        qs.append(("pet", str(pets_allowed)))
    if pets_present is not None:
        qs.append(("pets_present", str(pets_present)))
    if kitchen is not None:
        qs.append(("kit", str(kitchen)))
    d = _join_list(district_ids or [])
    if d:
        qs.append(("districts", d))
    if offers_since is not None:
        qs.append(("sin", str(offers_since)))
    if exchange is not None:
        qs.append(("exc", str(exchange)))
    if floor is not None:
        qs.append(("flo", str(floor)))
    if handicapped:
        qs.append(("han", "1"))
    if balcony:
        qs.append(("bal_or_ter", "1"))
    if garden:
        qs.append(("gar", "1"))
    if online_tour:
        qs.append(("onl_tour", "1"))
    if images_only:
        qs.append(("img_only", "1"))

    if not qs:
        return "https://www.wg-gesucht.de" + path
    encoded = "&".join(f"{quote(k, safe='[]') }={quote(v, safe=',')}" for k, v in qs)
    return "https://www.wg-gesucht.de" + path + "?" + encoded
