"""Tests für lesbare Fehler im Terminal (ohne --json)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from wggesucht_cli import cli  # noqa: E402
from wggesucht_cli.http_client import AuthError  # noqa: E402


# ---------- Fehler: lesbar im Terminal, JSON bei Pipe/--json ----------

def _tty_stderr(monkeypatch):
    monkeypatch.setattr(cli, "_stderr_is_tty", lambda: True)


def test_error_is_human_line_on_tty(monkeypatch, capsys):
    _tty_stderr(monkeypatch)
    with pytest.raises(SystemExit) as exc:
        cli.main(["search", "--city", "Atlantis"])
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert err.startswith("Fehler: ")
    assert "Unbekannte Stadt" in err
    assert not err.lstrip().startswith("{")


def test_error_stays_json_when_piped(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_stderr_is_tty", lambda: False)
    with pytest.raises(SystemExit) as exc:
        cli.main(["search", "--city", "Atlantis"])
    assert exc.value.code == 1
    payload = json.loads(capsys.readouterr().err)
    assert "Unbekannte Stadt" in payload["error"]


def test_error_stays_json_with_flag_on_tty(monkeypatch, capsys):
    _tty_stderr(monkeypatch)
    with pytest.raises(SystemExit):
        cli.main(["search", "--city", "Atlantis", "--json"])
    payload = json.loads(capsys.readouterr().err)
    assert "Unbekannte Stadt" in payload["error"]


def test_error_human_includes_hint(monkeypatch, capsys):
    _tty_stderr(monkeypatch)

    def _no_session(_http):
        raise AuthError("Keine Session gefunden", code="no_session")

    monkeypatch.setattr(cli, "HttpClient", lambda: object())
    monkeypatch.setattr(cli.messages, "list_messages", _no_session)
    with pytest.raises(SystemExit) as exc:
        cli.main(["messages", "list"])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "Fehler: Keine Session gefunden" in err
    assert "Hinweis: wggesucht login" in err

