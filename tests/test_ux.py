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
