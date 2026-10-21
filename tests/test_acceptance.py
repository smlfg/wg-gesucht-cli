"""Akzeptanztests – führen die CLI als Subprozess aus.

Lädt die agent-learnings-Sandbox via PYTHONPATH, so dass der
CLI-Subprozess nur Loopback-Verbindungen öffnen darf. Damit
kann eine Implementierung, die die Test-Konfiguration ignoriert,
niemals echte Server erreichen.
"""

from __future__ import annotations

import json
import os
import sys
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "harness"


def test_acceptance_harness_sitecustomize_in_repo():
    """Die Netz-Sandbox muss im Repo liegen (kein Maschinenpfad)."""
    assert (HARNESS / "sitecustomize.py").is_file()


def _run_cli(*args, env_extra=None, monkeypatch_env=None):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + str(HARNESS)
    env["ACCEPTANCE_SANDBOX"] = "1"
    if env_extra:
        env.update(env_extra)
    if monkeypatch_env:
        env.update(monkeypatch_env)
    return subprocess.run(
        [sys.executable, "-m", "wggesucht_cli.cli", *args],
        capture_output=True, text=True, env=env, cwd=str(ROOT), timeout=30,
    )


def test_no_network_access_at_all():
    """Der CLI-Aufruf ohne Subbefehl darf nirgendwo hin telefonieren."""
    r = _run_cli("--version")
    assert r.returncode == 0


def test_search_fails_cleanly_when_no_network():
    """Wenn der CLI-Subprozess versucht, echte Hosts zu erreichen,
    blockt die Sandbox und der Prozess antwortet mit Exit 3 oder
    wirft eine Exception."""
    r = _run_cli("search", "--city", "Berlin", "--limit", "1", "--json")
    # akzeptabel: 3 (HTTP/Netz), oder ein anderer Wert, aber
    # niemals 0 mit echten Daten
    assert r.returncode != 0
    assert r.returncode in (3, 4, 1)


def test_messages_list_no_session_exits_2(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    r = _run_cli("messages", "list", "--json")
    assert r.returncode == 2
    assert "no_session" in r.stderr or "wggesucht login" in r.stderr
