"""Tests für die echten wg-gesucht-Filter-URLs und die
clientseitigen Filter im `search`-Befehl.

Die synthetische HTML ist klein und deterministisch: vier echte
Anzeigen plus ein Werbe-Container ohne data-id, der ignoriert
werden muss.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from html import escape
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from wggesucht_cli import cities, parser  # noqa: E402
from wggesucht_cli.cli import _client_filter, _parse_date_arg  # noqa: E402

# ---------- synthetische Suche ----------

def _card(oid: str, titel: str, ort_text: str, rent: int, size: int,
          avail_from: str, avail_to: str | None = None,
          mitbewohner: int | None = None, mob: str | None = None,
          smoking: str | None = None) -> str:
    if avail_to:
        date_html = f'<div class="row">frei ab {avail_from} &ndash; {avail_to}</div>'
    else:
        date_html = f'<div class="row">ab {avail_from}</div>'
    extras = []
    if mob:
        extras.append(f"<span class=\"noprint\">{mob}</span>")
    if smoking:
        extras.append(f"<span class=\"noprint\">{smoking}</span>")
    if mitbewohner is not None:
        extras.append(f"<span class=\"noprint\">{mitbewohner}er WG</span>")
    return f"""
    <div class="offer_list_item" data-id="{oid}">
      <a href="/wg-zimmer-in-Heilbronn.60.0.1.0.html?asset_id={oid}#{oid}">{escape(titel)}</a>
      <h2 class="truncate_title">{escape(titel)}</h2>
      <span class="noprint">{ort_text}</span>
      <div class="row"><b>{rent} &euro;</b></div>
      <div class="row">{size} m&sup2;</div>
      {date_html}
      {''.join(extras)}
    </div>
    """


SYNTHETIC_HTML = f"""<!DOCTYPE html>
<html lang="de">
<head><title>Synth</title></head>
<body>
<form><input name="city_id" value="60"/></form>
{_card("1001", "Zimmer A", "2er WG | Heilbronn Altstadt | Str.1", 380, 14, "01.11.2026", "31.03.2027", mitbewohner=2, mob="möbliert", smoking="Rauchen nicht erwünscht")}
{_card("1002", "Zimmer B", "3er WG | Heilbronn Bretzenheim | Str.7", 460, 18, "15.11.2026", None, mitbewohner=3, mob="nicht möbliert", smoking="Rauchen auf dem Balkon erlaubt")}
{_card("1003", "Zimmer C", "4er WG | Heilbronn Altstadt | Str.12", 520, 22, "01.12.2026", "30.06.2027", mitbewohner=4, mob="möbliert", smoking="Rauchen im eigenen Zimmer erlaubt")}
{_card("1004", "Zimmer D", "2er WG | Heilbronn Bretzenheim | Str.3", 300, 11, "01.01.2027", None, mitbewohner=2, mob="nicht möbliert", smoking="Rauchen nicht erwünscht")}
<div class="offer_list_item housinganywhere_ad">SPONSORED</div>
</body>
</html>"""


@pytest.fixture
def synthetic_offers():
    return parser.parse_search(SYNTHETIC_HTML, limit=50, room_type="wg")


# ---------- cities / URL-Bau ----------

def test_cities_heilbronn_resolves():
    c = cities.resolve_city("Heilbronn")
    assert c and c["id"] == 60 and c["slug"] == "Heilbronn"


def test_build_url_basic():
    c = cities.resolve_city("Heilbronn")
    u = cities.build_search_url(c, rooms="wg", max_rent=500)
    assert u == "https://www.wg-gesucht.de/wg-zimmer-in-Heilbronn.60.0.1.0.html?rMax=500"


def test_build_url_dates():
    c = cities.resolve_city("Heilbronn")
    u = cities.build_search_url(c, move_in_from="2026-11-01", move_in_to="2027-01-31")
    # dFrDe / dToDe (deutsches Datumsformat) statt dFr / dTo –
    # letztere liefern HTTP 500 auf der Live-Site.
    assert "dFrDe=01.11.2026" in u
    assert "dToDe=31.01.2027" in u
    assert "dFr=" not in u
    assert "dTo=" not in u


def test_build_url_gender_and_ages():
    c = cities.resolve_city("Heilbronn")
    u = cities.build_search_url(
        c,
        wg_gender=2,           # Mann
        wg_searched_gender=1,  # Frau gesucht
        flatmate_age_min=22,
        flatmate_age_max=32,
    )
    assert "wgFla=2" in u
    assert "wgSea=1" in u
    assert "wgMnF=22" in u
    assert "wgMxT=32" in u


def test_build_url_flatmates_and_flatshare_types():
    c = cities.resolve_city("Heilbronn")
    # build_search_url erwartet die Formular-Index-Werte: 1=2er, 2=3er, …
    u = cities.build_search_url(
        c,
        flatmates_min=2,   # 3er WG
        flatmates_max=4,   # 5er WG
        flatshare_types=[1, 12],  # Studenten + gemischte
    )
    assert "wg_flatmates_from=2" in u
    assert "wg_flatmates_to=4" in u
    assert "wgArt=1,12" in u


def test_build_url_furnished_smoking_pets_kitchen():
    c = cities.resolve_city("Heilbronn")
    u = cities.build_search_url(
        c,
        furnished=1,
        smoking=2,
        pets_allowed=1,
        pets_present=2,
        kitchen=1,
    )
    assert "fur=1" in u
    assert "wgSmo=2" in u
    assert "pet=1" in u
    assert "pets_present=2" in u
    assert "kit=1" in u


def test_build_url_districts():
    c = cities.resolve_city("Heilbronn")
    u = cities.build_search_url(c, district_ids=[85215, 1955])
    assert "districts=85215%2C1955" in u.replace(",", "%2C")


def test_build_url_rent_types():
    c = cities.resolve_city("Heilbronn")
    u = cities.build_search_url(c, rent_types=[1, 2])
    # '[]' wird im Such-URL nicht encodiert (Anzeige in der Adressleiste)
    assert "rent_types[]=1,2" in u


def test_build_url_extras():
    c = cities.resolve_city("Heilbronn")
    u = cities.build_search_url(
        c, radius=5000, offers_since=2, exchange=1, floor=3,
        handicapped=True, balcony=True, garden=True, online_tour=True,
        images_only=True,
    )
    assert "rad=5000" in u
    assert "sin=2" in u
    assert "exc=1" in u
    assert "flo=3" in u
    assert "han=1" in u
    assert "bal_or_ter=1" in u
    assert "gar=1" in u
    assert "onl_tour=1" in u
    assert "img_only=1" in u


def test_build_url_min_rent_and_max_size():
    c = cities.resolve_city("Heilbronn")
    u = cities.build_search_url(c, min_rent=200, max_size=20)
    assert "rMin=200" in u
    assert "sizeMax=20" in u


def test_build_url_does_not_include_unset():
    c = cities.resolve_city("Heilbronn")
    u = cities.build_search_url(c, max_rent=500)
    for k in ("rMin", "sizeMax", "dFrDe", "dToDe", "dFr", "dTo", "wgFla", "fur", "wgSmo", "wgArt"):
        assert k not in u


def test_date_helper_iso():
    assert _parse_date_arg("2026-11-01") == "2026-11-01"
    assert _parse_date_arg("01.11.2026") == "2026-11-01"


def test_date_helper_invalid():
    import argparse
    with pytest.raises(argparse.ArgumentTypeError):
        _parse_date_arg("2026/11/01")
    with pytest.raises(argparse.ArgumentTypeError):
        _parse_date_arg("")


# ---------- Parser ----------

def test_parse_synthetic_offers_basic(synthetic_offers):
    assert len(synthetic_offers) == 4  # Ad-Container ohne data-id ignoriert
    oids = [o["id"] for o in synthetic_offers]
    assert oids == ["1001", "1002", "1003", "1004"]


def test_parse_synthetic_rent_size(synthetic_offers):
    rents = [o["gesamtmiete_euro"] for o in synthetic_offers]
    sizes = [o["groesse_qm"] for o in synthetic_offers]
    assert rents == [380, 460, 520, 300]
    assert sizes == [14, 18, 22, 11]


def test_parse_synthetic_dates(synthetic_offers):
    assert synthetic_offers[0]["verfuegbar_ab"] == "2026-11-01"
    assert synthetic_offers[0]["verfuegbar_bis"] == "2027-03-31"
    assert synthetic_offers[1]["verfuegbar_ab"] == "2026-11-15"
    assert synthetic_offers[1]["verfuegbar_bis"] is None


def test_parse_synthetic_mitbewohner(synthetic_offers):
    counts = [o["mitbewohner_anzahl"] for o in synthetic_offers]
    assert counts == [2, 3, 4, 2]


def test_parse_synthetic_furnished_smoking(synthetic_offers):
    mob = [o["moebliert"] for o in synthetic_offers]
    sm = [o["rauchen"] for o in synthetic_offers]
    assert mob == ["ja", "nein", "ja", "nein"]
    assert sm == ["nicht_erwuenscht", "balkon", "eigenes_zimmer", "nicht_erwuenscht"]


def test_parse_synthetic_stadtteil(synthetic_offers):
    teile = [o["stadtteil"] for o in synthetic_offers]
    assert teile == ["Altstadt", "Bretzenheim", "Altstadt", "Bretzenheim"]


# ---------- Client-Filter ----------

def _ns(**kwargs):
    """Baut einen argparse-Namespace mit Default-Parametern."""
    defaults = {
        "max_rent": None, "min_rent": None,
        "min_size": None, "max_size": None,
        "move_in_from": None, "move_in_to": None,
        "furnished": None, "smoking": None,
        "min_flatmates": None, "max_flatmates": None,
        "district": None, "limit": None,
    }
    defaults.update(kwargs)
    return type("NS", (), defaults)()


def test_client_filter_max_rent(synthetic_offers):
    out = _client_filter(_ns(max_rent=400), synthetic_offers)
    assert [o["id"] for o in out] == ["1001", "1004"]


def test_client_filter_min_size(synthetic_offers):
    out = _client_filter(_ns(min_size=18), synthetic_offers)
    assert [o["id"] for o in out] == ["1002", "1003"]


def test_client_filter_move_in_window(synthetic_offers):
    out = _client_filter(_ns(move_in_from="2026-11-15", move_in_to="2026-12-31"),
                         synthetic_offers)
    # verfuegbar_ab in [15.11.2026, 31.12.2026]: 1002 (15.11) und 1003 (01.12)
    assert [o["id"] for o in out] == ["1002", "1003"]


def test_client_filter_furnished(synthetic_offers):
    out = _client_filter(_ns(furnished=1), synthetic_offers)
    assert [o["id"] for o in out] == ["1001", "1003"]


def test_client_filter_smoking_nicht_erwuenscht(synthetic_offers):
    out = _client_filter(_ns(smoking=2), synthetic_offers)
    # 2 = nicht erwünscht → 1001, 1004
    assert [o["id"] for o in out] == ["1001", "1004"]


def test_client_filter_district(synthetic_offers):
    out = _client_filter(_ns(district="Altstadt"), synthetic_offers)
    assert [o["id"] for o in out] == ["1001", "1003"]


def test_client_filter_flatmates(synthetic_offers):
    out = _client_filter(_ns(min_flatmates=3), synthetic_offers)
    assert [o["id"] for o in out] == ["1002", "1003"]


# ---------- End-to-End (Subprozess mit Sandbox) ----------

def _run_cli(*args, env_extra=None):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    env["ACCEPTANCE_SANDBOX"] = "1"
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, "-m", "wggesucht_cli.cli", *args],
        capture_output=True, text=True, env=env, cwd=str(ROOT), timeout=30,
    )


def test_cli_help_lists_new_filters():
    r = _run_cli("search", "--help")
    assert r.returncode == 0
    for opt in (
        "--max-rent", "--min-size", "--move-in-from", "--move-in-to",
        "--wg-gender", "--flatmate-age-min", "--furnished", "--smoking",
        "--district", "--flatshare-type", "--since", "--handicapped",
    ):
        assert opt in r.stdout, f"missing {opt} in help"


def test_cli_search_rejects_unknown_date_format():
    r = _run_cli("search", "--city", "Heilbronn", "--move-in-from", "2026/11/01", "--json")
    assert r.returncode != 0
    assert "Datumsformat" in r.stderr or "Date" in r.stderr
