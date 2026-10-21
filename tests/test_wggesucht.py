"""Tests für wggesucht.

Die Tests sind netz-frei: ein FakeHttpClient in conftest.py
liefert die Fixture-HTMLs aus tests/fixtures/ aus. Auch die
Akzeptanztests starten das CLI mit der agent-learnings
Network-Sandbox (sitecustomize), die alle Nicht-Loopback-
Verbindungen blockiert.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import pytest

# src/ zum Pfad hinzufügen, damit `import wggesucht_cli` ohne Install geht
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from wggesucht_cli import auth, cities, messages, parser  # noqa: E402
from wggesucht_cli.http_client import (  # noqa: E402
    ActionDenied,
    AuthError,
    HttpClient,
    HTTPError,
    clear_session,
    load_session,
    save_session,
    session_path,
)


FIX = Path(__file__).parent / "fixtures"


class FakeResp:
    def __init__(self, status=200, text="", url="", cookies=None, headers=None):
        self.status = status
        self.text = text
        self.url = url
        self.cookies = cookies or {}
        self.headers = headers or {}


class FakeHttp:
    """Sehr einfacher HTTP-Stub."""

    def __init__(self, routes: dict):
        # routes: GET/POST url -> (status, text) oder eine Sequenz
        self.routes = routes
        self.calls: list[tuple[str, str, dict]] = []
        self.cookies: dict[str, str] = {}
        self._session = _FakeCookieJar()

    def get(self, url, *, allow_redirects=True):
        self.calls.append(("GET", url, {}))
        if url not in self.routes:
            raise HTTPError(f"unexpected GET {url}", url=url)
        v = self.routes[url]
        if isinstance(v, list):
            if not v:
                raise HTTPError(f"GET {url} exhausted", url=url)
            v = v.pop(0)
        status, text = v
        return FakeResp(status=status, text=text, url=url)

    def post(self, url, *, data=None, json=None, allow_redirects=True):
        body = data if data is not None else json
        self.calls.append(("POST", url, {"body": body}))
        if url not in self.routes:
            raise HTTPError(f"unexpected POST {url}", url=url)
        v = self.routes[url]
        if isinstance(v, list):
            v = v.pop(0)
        status, text = v
        return FakeResp(status=status, text=text, url=url)

    def load_cookies(self, jar):
        for c in jar:
            self._session.cookies[c["name"]] = c

    def _export_cookies(self):
        return list(self._session.cookies.values())


class _FakeCookieJar:
    def __init__(self):
        self.cookies: dict[str, dict] = {}


@pytest.fixture
def search_html():
    return (FIX / "search_berlin_wg.html").read_text(encoding="utf-8")


@pytest.fixture
def detail_html():
    return (FIX / "detail_13374505.html").read_text(encoding="utf-8")


@pytest.fixture
def login_html():
    return (FIX / "login_page.html").read_text(encoding="utf-8")


@pytest.fixture
def nachrichten_html():
    return (FIX / "nachrichten_logged_in.html").read_text(encoding="utf-8")


@pytest.fixture
def thread_html():
    return (FIX / "thread_9123456.html").read_text(encoding="utf-8")


# ---------- cities ----------

def test_cities_resolve_known():
    c = cities.resolve_city("Berlin")
    assert c and c["id"] == 8 and c["slug"] == "Berlin"


def test_cities_resolve_umlaute():
    c = cities.resolve_city("München")
    assert c and c["slug"] == "Muenchen"


def test_cities_resolve_unknown():
    assert cities.resolve_city("Atlantis") is None


def test_build_search_url_wg():
    c = cities.resolve_city("Berlin")
    url = cities.build_search_url(c, rooms="wg", max_rent=600, min_size=15)
    assert url.startswith("https://www.wg-gesucht.de/wg-zimmer-in-Berlin.8.0.1.0.html")
    assert "rMax=600" in url
    assert "sizeMin=15" in url


def test_build_search_url_rooms():
    c = cities.resolve_city("Berlin")
    assert "1-zimmer-wohnungen" in cities.build_search_url(c, rooms="1zimmer")
    assert "/wohnungen" in cities.build_search_url(c, rooms="wohnung")
    assert "/haeuser" in cities.build_search_url(c, rooms="haus")


# ---------- parser ----------

def test_parse_search_returns_offers(search_html):
    offers = parser.parse_search(search_html, limit=5)
    assert offers, "no offers parsed"
    first = offers[0]
    assert first["id"]
    assert first["url"].startswith("https://www.wg-gesucht.de/")
    assert first["stadt"] is None or isinstance(first["stadt"], str)
    # title or rent should be set on at least one
    assert any(o["titel"] for o in offers)


def test_parse_search_limit(search_html):
    offers = parser.parse_search(search_html, limit=2)
    assert len(offers) <= 2


def test_parse_search_skips_ads_only(search_html):
    # search_berlin_wg enthält sowohl Werbung (housinganywhere) als auch echte Anzeigen
    # wir wollen nur data-id-Karten
    offers = parser.parse_search(search_html, limit=100)
    ids = [o["id"] for o in offers]
    assert all(re.match(r"^\d+$", i) for i in ids), ids
    # ensure at least one real offer (id 13374505 ist in der Live-Seite)
    # fixtures können sich ändern, daher nur "nicht leer"
    assert offers


def test_parse_search_verfuegbar_bis_from_middle_row_only(search_html):
    """verfuegbar_bis darf nicht aus Online-/Print-Duplikaten stammen (#2)."""
    offers = parser.parse_search(search_html, limit=100)
    by_id = {o["id"]: o for o in offers}
    assert by_id["14080537"]["verfuegbar_ab"] == "2026-11-16"
    assert by_id["14080537"]["verfuegbar_bis"] is None
    assert by_id["12329701"]["verfuegbar_ab"] == "2027-01-01"
    assert by_id["12329701"]["verfuegbar_bis"] is None
    assert by_id["14169169"]["verfuegbar_ab"] == "2026-11-01"
    assert by_id["14169169"]["verfuegbar_bis"] == "2027-02-28"
    impossible = [
        o for o in offers
        if o["verfuegbar_bis"] and o["verfuegbar_ab"]
        and o["verfuegbar_bis"] < o["verfuegbar_ab"]
    ]
    assert impossible == []
    bogus_bis_eq_ab = [
        o["id"] for o in offers
        if o["verfuegbar_bis"] and o["verfuegbar_ab"]
        and o["verfuegbar_bis"] == o["verfuegbar_ab"]
        and o["id"] in {"12329701", "4668942", "14059016"}
    ]
    assert bogus_bis_eq_ab == []


def test_parse_detail_extracts_fields(detail_html):
    ang = parser.parse_detail(detail_html)
    assert ang["titel"]
    assert ang["id"] == "13374505"
    # kaltmiete 680€ aus dem Live-Detail
    assert ang["kaltmiete_euro"] == 680
    # 18m²
    assert ang["groesse_qm"] == 18


def test_parse_detail_extracts_beschreibung_text(detail_html):
    ang = parser.parse_detail(detail_html)
    text = ang["beschreibung_text"]
    assert text
    assert len(text) > 200
    assert "Friedrichshagen" in text
    assert "The Highlights" in text


def test_parse_login_form(login_html):
    info = parser.parse_login_form(login_html)
    assert info["action"] == "/mein-wg-gesucht.html"
    assert "csrf" in info["fields"]
    assert info["fields"]["csrf"] == "abc123"


def test_looks_logged_in():
    assert parser.looks_logged_in('<a href="/nachrichten.html">Nachrichten</a>')
    assert parser.looks_logged_in('<a href="/x">Abmelden</a>')
    assert not parser.looks_logged_in('<html><body>just marketing</body></html>')


def test_normalize_offer_input():
    assert parser.normalize_offer_input("13374505") == "13374505"
    assert parser.normalize_offer_input("https://www.wg-gesucht.de/wg-zimmer-in-Berlin-X.13374505.html") == "13374505"
    assert parser.normalize_offer_input("/wg-zimmer-in-Y.42.html") == "42"
    with pytest.raises(ValueError):
        parser.normalize_offer_input("not a thing")


# ---------- http_client session ----------

def test_session_save_load_roundtrip(tmp_path, monkeypatch):
    p = tmp_path / "session.json"
    save_session(str(p), email="x@y.de", cookies=[{
        "name": "PHPSESSID", "value": "abc", "domain": ".wg-gesucht.de", "path": "/"
    }])
    assert oct(p.stat().st_mode & 0o777) == "0o600"
    data = load_session(str(p))
    assert data and data["email"] == "x@y.de"
    assert data["cookies"][0]["name"] == "PHPSESSID"


def test_session_load_filters_other_domain(tmp_path):
    p = tmp_path / "session.json"
    save_session(str(p), email="x@y.de", cookies=[
        {"name": "PHPSESSID", "value": "abc", "domain": ".wg-gesucht.de", "path": "/"},
        {"name": "keycloak", "value": "evil", "domain": ".id.bund.de", "path": "/"},
    ])
    data = load_session(str(p))
    domains = [c["domain"] for c in data["cookies"]]
    assert ".id.bund.de" not in domains


def test_clear_session_idempotent(tmp_path):
    p = tmp_path / "session.json"
    assert clear_session(str(p)) is False
    save_session(str(p), email="x@y.de", cookies=[])
    assert clear_session(str(p)) is True
    assert clear_session(str(p)) is False


# ---------- auth (mit FakeHttp) ----------

def test_login_succeeds_and_saves_session(tmp_path, login_html, nachrichten_html, monkeypatch):
    # Session-Pfad in tmp
    p = tmp_path / "session.json"
    monkeypatch.setattr(auth, "session_path", lambda: str(p))
    routes = {
        "https://www.wg-gesucht.de/?modal=sign_in": (200, login_html),
        "https://www.wg-gesucht.de/ajax/sessions.php?action=login":
            (200, json.dumps({
                "access_token": "tk",
                "expires_in": 3600,
                "token_type": "Bearer",
                "refresh_token": "rt",
                "user_id": "42",
                "dev_ref_no": "dev",
                "csrf_token": "csrf",
            })),
        "https://www.wg-gesucht.de/nachrichten.html": (200, nachrichten_html),
    }
    http = FakeHttp(routes)
    res = auth.login(http=http, env={"WG_EMAIL": "x@y.de", "WG_PASSWORD": "pw"}, store_path=str(p))
    assert res["ok"] is True
    assert res["user"] == "x@y.de"
    assert res["user_id"] == "42"
    assert os.path.exists(str(p))


def test_login_rejects_bad_credentials(tmp_path, login_html, monkeypatch):
    p = tmp_path / "session.json"
    monkeypatch.setattr(auth, "session_path", lambda: str(p))
    routes = {
        "https://www.wg-gesucht.de/?modal=sign_in": (200, login_html),
        "https://www.wg-gesucht.de/ajax/sessions.php?action=login":
            (401, json.dumps({
                "type": "about:blank", "title": "Unauthorized",
                "status": 401, "detail": "Invalid username and password combination",
            })),
    }
    http = FakeHttp(routes)
    with pytest.raises(AuthError):
        auth.login(http=http, env={"WG_EMAIL": "x@y.de", "WG_PASSWORD": "BAD"},
                   store_path=str(p))
    assert not os.path.exists(str(p))


def test_login_fails_without_proof(tmp_path, login_html, monkeypatch):
    p = tmp_path / "session.json"
    monkeypatch.setattr(auth, "session_path", lambda: str(p))
    routes = {
        "https://www.wg-gesucht.de/?modal=sign_in": (200, login_html),
        "https://www.wg-gesucht.de/ajax/sessions.php?action=login":
            (200, json.dumps({
                "access_token": "tk", "user_id": "42",
                "refresh_token": "rt", "dev_ref_no": "d",
                "csrf_token": "c",
            })),
        "https://www.wg-gesucht.de/nachrichten.html": (200, "<html>nope</html>"),
    }
    http = FakeHttp(routes)
    with pytest.raises(AuthError):
        auth.login(http=http, env={"WG_EMAIL": "x@y.de", "WG_PASSWORD": "pw"},
                   store_path=str(p))
    # keine Session gespeichert
    assert not os.path.exists(str(p))


def test_login_missing_credentials(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "session_path", lambda: str(tmp_path / "s.json"))
    http = FakeHttp({})
    with pytest.raises(AuthError) as e:
        auth.login(http=http, env={}, store_path=str(tmp_path / "s.json"))
    assert e.value.code == "missing_credentials"


# ---------- messages (mit FakeHttp) ----------

def test_messages_list(tmp_path, nachrichten_html, monkeypatch):
    p = tmp_path / "session.json"
    save_session(str(p), email="x@y.de", cookies=[{
        "name": "PHPSESSID", "value": "abc", "domain": ".wg-gesucht.de", "path": "/"
    }])
    monkeypatch.setattr(auth, "session_path", lambda: str(p))
    http = FakeHttp({"https://www.wg-gesucht.de/nachrichten.html": (200, nachrichten_html)})
    res = messages.list_messages(http)
    assert res["anzahl"] >= 1
    assert res["threads"][0]["thread_id"] == "9123456"
    # Drei Threads (Lisa+unread, Tom+gelesen, Sara+unread+gelöschte Anzeige)
    tids = sorted(t["thread_id"] for t in res["threads"])
    assert tids == ["9123456", "9123457", "9123458"]
    lisa = next(t for t in res["threads"] if t["thread_id"] == "9123456")
    assert lisa["absender"] == "Lisa M."
    assert lisa["gelesen"] is False
    assert lisa["datum"] == "2026-10-11"
    tom = next(t for t in res["threads"] if t["thread_id"] == "9123457")
    assert tom["gelesen"] is True
    # relatives Datum ("vor 3 Tagen") ist OK, kann nicht in ISO gewandelt werden
    assert tom["datum"] is None
    sara = next(t for t in res["threads"] if t["thread_id"] == "9123458")
    assert "Diese Anzeige wurde gelöscht" in (sara["subject"] or "")


def test_parse_messages_list_handles_empty_html():
    assert parser.parse_messages_list("") == []
    assert parser.parse_messages_list("<html><body></body></html>") == []
    # keine conversation_div-Selektoren → keine Threads
    html = '<html><body><div data-conversation_id="11"></div></body></html>'
    assert parser.parse_messages_list(html) == []


def test_messages_read_thread(tmp_path, nachrichten_html, thread_html, monkeypatch):
    p = tmp_path / "session.json"
    save_session(str(p), email="x@y.de", cookies=[{
        "name": "PHPSESSID", "value": "abc", "domain": ".wg-gesucht.de", "path": "/"
    }])
    monkeypatch.setattr(auth, "session_path", lambda: str(p))
    routes = {
        "https://www.wg-gesucht.de/nachrichten.html": (200, nachrichten_html),
        "https://www.wg-gesucht.de/nachricht.html?nachrichten-id=9123456&list=1":
            (200, thread_html),
    }
    http = FakeHttp(routes)
    res = messages.read_thread(http, "9123456")
    assert res["thread"]["thread_id"] == "9123456"
    assert res["thread"]["subject"] == "WG-Zimmer in Berlin-Friedrichshagen"
    msgs = res["thread"]["nachrichten"]
    assert len(msgs) == 2
    # Eigene Nachricht (my_message)
    assert msgs[0]["von"] == "self"
    assert msgs[0]["text"].startswith("Hi Lisa")
    assert msgs[0]["von_user_id"] == "99999999"
    # Gegenüber
    assert msgs[1]["von"] == "other"
    assert msgs[1]["text"].startswith("Ja, komm")
    assert msgs[1]["von_user_id"] == "12345678"
    # Gegenüber-User aus Header-Image (Fallback / direkter Pfad)
    assert res["thread"]["gegenueber_user_id"] == "12345678"
    assert res["thread"]["eigene_user_id"] == "99999999"
    assert res["thread"]["anzeige_geloescht"] is False


def test_messages_read_thread_no_session(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "session_path", lambda: str(tmp_path / "absent.json"))
    http = FakeHttp({})
    with pytest.raises(AuthError):
        messages.read_thread(http, "9123456")


def test_messages_read_thread_invalid_id(tmp_path, monkeypatch):
    p = tmp_path / "s.json"
    save_session(str(p), email="x@y.de", cookies=[{
        "name": "PHPSESSID", "value": "abc", "domain": ".wg-gesucht.de", "path": "/"
    }])
    monkeypatch.setattr(auth, "session_path", lambda: str(p))
    http = FakeHttp({})
    with pytest.raises(ValueError):
        messages.read_thread(http, "not a number")
    with pytest.raises(ValueError):
        messages.read_thread(http, "")


def test_messages_list_no_session(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "session_path", lambda: str(tmp_path / "absent.json"))
    http = FakeHttp({})
    with pytest.raises(AuthError) as e:
        messages.list_messages(http)
    assert e.value.code == "no_session"


def test_messages_send_requires_confirm(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "session_path", lambda: str(tmp_path / "absent.json"))
    http = FakeHttp({})
    with pytest.raises(ActionDenied):
        messages.send_message(http, to="13374505", text="hi", confirm=False)


# ---------- CLI (über Subprozess) ----------

def _run_cli(*args, env_extra=None):
    import subprocess
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    # erzwungene Loopback-Sandbox (siehe tests/acceptance/conftest.py)
    env["ACCEPTANCE_SANDBOX"] = "1"
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, "-m", "wggesucht_cli.cli", *args],
        capture_output=True, text=True, env=env, cwd=str(ROOT), timeout=30,
    )


def test_cli_version():
    r = _run_cli("--version")
    assert r.returncode == 0
    assert "0.1.0" in r.stdout


def test_cli_help():
    r = _run_cli("--help")
    assert r.returncode == 0
    assert "search" in r.stdout
    assert "messages" in r.stdout


def test_cli_validation_errors_exit_1():
    """argparse usage errors must be exit 1 (Usage), not 2 (Auth)."""
    cases = [
        ["search"],
        ["frobnicate"],
        ["search", "--city", "Berlin", "--limit", "abc"],
        ["search", "--city", "Berlin", "--rooms", "bad"],
        ["show"],
    ]
    for args in cases:
        r = _run_cli(*args)
        assert r.returncode == 1, f"{args!r} → {r.returncode}"


def test_cli_search_unknown_city():
    r = _run_cli("search", "--city", "Atlantis", "--json")
    assert r.returncode == 1
    assert "error" in r.stderr


def test_cli_send_without_confirm_exits_5():
    r = _run_cli("messages", "send", "--to", "13374505", "--text", "hi", "--json")
    assert r.returncode == 5
    assert "confirm_required" in r.stderr


def test_cli_messages_read_invalid_thread_id():
    for thread_id in ("abc123", ""):
        r = _run_cli("messages", "read", thread_id, "--json")
        assert r.returncode == 1
        assert "Traceback" not in r.stderr
        payload = json.loads(r.stderr.strip())
        assert payload["error"]
        assert "thread_id" in payload["error"]


def test_cli_logout_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    r = _run_cli("logout", "--json")
    assert r.returncode == 0
    payload = json.loads(r.stdout)
    assert payload["ok"] is True
    assert payload["session_entfernt"] is False
    r2 = _run_cli("logout", "--json")
    assert r2.returncode == 0
    assert json.loads(r2.stdout)["session_entfernt"] is False
