"""Tests für die menschenfreundliche CLI-Bedienung."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from wggesucht_cli import auth, cli  # noqa: E402
from wggesucht_cli.http_client import AuthError  # noqa: E402


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


# ---------- login ----------

def _tty(monkeypatch):
    monkeypatch.setattr(auth.sys, "stdin", SimpleNamespace(isatty=lambda: True))


def test_login_eof_is_cancelled_without_traceback(monkeypatch):
    _tty(monkeypatch)
    monkeypatch.setattr("builtins.input", lambda _prompt: "x@y.de")

    def _eof(_prompt):
        raise EOFError()

    monkeypatch.setattr(auth.getpass, "getpass", _eof)
    with pytest.raises(AuthError) as exc:
        auth._read_credentials({})
    assert str(exc.value) == "Abgebrochen."
    assert exc.value.code == "cancelled"


def test_login_ctrl_c_is_cancelled_without_traceback(monkeypatch):
    _tty(monkeypatch)
    monkeypatch.setattr("builtins.input", lambda _prompt: "x@y.de")

    def _interrupt(_prompt):
        raise KeyboardInterrupt()

    monkeypatch.setattr(auth.getpass, "getpass", _interrupt)
    with pytest.raises(AuthError) as exc:
        auth._read_credentials({})
    assert str(exc.value) == "Abgebrochen."


def test_login_empty_password_is_rejected_without_traceback(monkeypatch):
    _tty(monkeypatch)
    monkeypatch.setattr(auth.getpass, "getpass", lambda _prompt: "")
    with pytest.raises(AuthError) as exc:
        auth._read_credentials({"WG_EMAIL": "x@y.de"})
    assert str(exc.value) == "Passwort darf nicht leer sein."


def test_login_without_tty_or_env_explains_next_step():
    with pytest.raises(AuthError) as exc:
        auth.login(http=object(), env={}, store_path="/tmp/unused.json")
    assert exc.value.code == "missing_credentials"
    assert "Login fehlt" in str(exc.value)
    assert "wggesucht login" in str(exc.value)
    assert "WG_EMAIL/WG_PASSWORD" in str(exc.value)


def test_cli_login_without_tty_or_env_is_json_error():
    r = _run_cli(
        "login", "--json",
        env_extra={"WG_EMAIL": "", "WG_PASSWORD": ""},
    )
    assert r.returncode == 2
    assert "Traceback" not in r.stderr
    payload = json.loads(r.stderr.strip())
    assert payload["kind"] == "missing_credentials"
    assert "Login fehlt" in payload["error"]


def test_login_help_mentions_env_for_agents():
    r = _run_cli("login", "--help")
    assert r.returncode == 0
    assert "WG_EMAIL/WG_PASSWORD" in r.stdout
    assert "Fragt E-Mail und Passwort ab" in r.stdout


# ---------- search: Stadt positional ----------

class _FakeResp:
    status = 200
    text = "<html><body></body></html>"
    url = "https://www.wg-gesucht.de/"


class _FakeHttp:
    def __init__(self):
        self.urls: list[str] = []

    def get(self, url):
        self.urls.append(url)
        return _FakeResp()


def test_search_positional_city_matches_city_option(monkeypatch, capsys):
    http = _FakeHttp()
    monkeypatch.setattr(cli, "HttpClient", lambda: http)

    assert cli.main(["search", "heilbronn", "--max-rent", "500", "--json"]) == 0
    positional = json.loads(capsys.readouterr().out)
    assert cli.main(["search", "--city", "heilbronn", "--max-rent", "500", "--json"]) == 0
    option = json.loads(capsys.readouterr().out)

    assert positional["url"] == option["url"]
    assert "Heilbronn.60" in positional["url"]
    assert positional["stadt"] == "heilbronn"


def test_search_missing_city_is_usage_error(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["search", "--json"])
    assert exc.value.code == 1


# ---------- lesbare Ausgabe im Terminal ----------

FIX = ROOT / "tests" / "fixtures"


class _HtmlHttp:
    def __init__(self, html: str):
        self.html = html

    def get(self, url):
        return SimpleNamespace(status=200, text=self.html, url=url)


def _tty_stdout(monkeypatch):
    monkeypatch.setattr(cli, "_stdout_is_tty", lambda: True)


def test_format_search_readable_line():
    payload = {
        "stadt": "Heilbronn",
        "angebote": [{
            "id": "123456",
            "gesamtmiete_euro": 450,
            "groesse_qm": 14,
            "typ": "wg",
            "stadt": "Heilbronn",
            "stadtteil": "Mitte",
            "verfuegbar_ab": "2026-12-01",
        }],
    }
    text = cli._format_search(payload)
    assert (
        "[1] 450 € | 14 m² | WG-Zimmer | Heilbronn-Mitte | ab 01.12. | ID 123456"
        in text
    )


def test_search_human_output_on_tty(monkeypatch, capsys):
    html = (FIX / "search_berlin_wg.html").read_text(encoding="utf-8")
    monkeypatch.setattr(cli, "HttpClient", lambda: _HtmlHttp(html))
    _tty_stdout(monkeypatch)

    assert cli.main(["search", "Berlin", "--limit", "1"]) == 0
    out = capsys.readouterr().out
    assert not out.lstrip().startswith("{")
    assert "Angebot(e) in Berlin" in out
    assert " | ID " in out


def test_search_pipe_stays_json_without_flag(monkeypatch, capsys):
    html = (FIX / "search_berlin_wg.html").read_text(encoding="utf-8")
    monkeypatch.setattr(cli, "HttpClient", lambda: _HtmlHttp(html))
    monkeypatch.setattr(cli, "_stdout_is_tty", lambda: False)

    assert cli.main(["search", "Berlin", "--limit", "1"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["stadt"] == "Berlin"
    assert len(payload["angebote"]) == 1


def test_show_human_output_on_tty(monkeypatch, capsys):
    html = (FIX / "detail_13374505.html").read_text(encoding="utf-8")
    monkeypatch.setattr(cli, "HttpClient", lambda: _HtmlHttp(html))
    _tty_stdout(monkeypatch)

    assert cli.main(["show", "13374505"]) == 0
    out = capsys.readouterr().out
    assert not out.lstrip().startswith("{")
    assert "13374505" in out
    assert "Berlin-Friedrichshagen" in out
    assert "480 €" in out
    assert "18 m²" in out


def test_messages_list_human_output_on_tty(monkeypatch, capsys):
    payload = {
        "user": "x@y.de",
        "anzahl": 1,
        "threads": [{
            "thread_id": "9123456",
            "subject": "WG-Zimmer in Berlin-Friedrichshagen",
            "absender": "Lisa M.",
            "datum": "2026-10-11",
            "gelesen": False,
        }],
    }
    monkeypatch.setattr(cli, "HttpClient", lambda: object())
    monkeypatch.setattr(cli.messages, "list_messages", lambda _http: payload)
    _tty_stdout(monkeypatch)

    assert cli.main(["messages", "list"]) == 0
    out = capsys.readouterr().out
    assert not out.lstrip().startswith("{")
    assert "Lisa M." in out
    assert "ungelesen" in out
    assert "ID 9123456" in out


# ---------- Captcha-/Sperrseite ----------

def test_search_block_page_reports_captcha(monkeypatch, capsys):
    html = (FIX / "search_blocked.html").read_text(encoding="utf-8")
    monkeypatch.setattr(cli, "HttpClient", lambda: _HtmlHttp(html))
    monkeypatch.setattr(cli, "_stdout_is_tty", lambda: False)
    with pytest.raises(SystemExit) as exc:
        cli.main(["search", "Stuttgart", "--json"])
    assert exc.value.code == 3
    payload = json.loads(capsys.readouterr().err)
    assert payload["kind"] == "blocked"
    assert "blockiert gerade (Captcha)" in payload["error"]


def test_search_new_card_markup_on_tty(monkeypatch, capsys):
    html = (FIX / "search_stuttgart_new.html").read_text(encoding="utf-8")
    monkeypatch.setattr(cli, "HttpClient", lambda: _HtmlHttp(html))
    _tty_stdout(monkeypatch)
    assert cli.main(["search", "Stuttgart", "--limit", "1"]) == 0
    out = capsys.readouterr().out
    assert "Angebot(e) in Stuttgart" in out
    assert "350 €" in out
    assert "ID 9000001" in out


# ---------- login: lesbare Ausgabe ----------

def test_login_human_output_on_tty(monkeypatch, capsys):
    payload = {"ok": True, "user": "test@example.org", "user_id": "42"}
    monkeypatch.setattr(cli, "HttpClient", lambda: object())
    monkeypatch.setattr(cli.auth, "login", lambda **_kwargs: payload)
    _tty_stdout(monkeypatch)

    assert cli.main(["login"]) == 0
    out = capsys.readouterr().out
    assert out == "Angemeldet als test@example.org.\n"


def test_login_pipe_stays_json_without_flag(monkeypatch, capsys):
    payload = {"ok": True, "user": "test@example.org", "user_id": "42"}
    monkeypatch.setattr(cli, "HttpClient", lambda: object())
    monkeypatch.setattr(cli.auth, "login", lambda **_kwargs: payload)
    monkeypatch.setattr(cli, "_stdout_is_tty", lambda: False)

    assert cli.main(["login"]) == 0
    assert json.loads(capsys.readouterr().out)["user"] == "test@example.org"
