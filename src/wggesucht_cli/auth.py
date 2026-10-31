"""Login gegen wg-gesucht.de.

Stand 2026-10-13: wg-gesucht.de hat **kein klassisches HTML-Login-Formular
mehr**. Das Formular ``login_form`` ist nur ein Anzeige-Mockup; der echte
Login läuft per **JSON-POST** auf ``/ajax/sessions.php?action=login``.
Antwort enthält ``access_token`` (Bearer, 1h gültig) und ``refresh_token``
sowie ``user_id`` und ``dev_ref_no``. Diese Tokens werden als Cookies mit
HttpOnly/Secure-Flag in der Session gespeichert und bei jedem Request als
Header ``X-Authorization: Bearer <token>`` ausgewertet.

``PHPSESSID`` allein reicht für API-Calls nicht aus (siehe 401 auf
``POST /api/conversations`` ohne Bearer). Daher muss der Login alle
OAuth-Tokens korrekt speichern.
"""

from __future__ import annotations

import getpass
import json
import os
import sys
from typing import Any, Optional
from urllib.parse import urljoin  # noqa: F401  (legacy reference in module)

from . import parser
from .http_client import (
    AuthError,
    HttpClient,
    HTTPError,
    Response,
    base_url,
    save_session,
    session_path,
)


def _is_logged_in_response(r: Response) -> bool:
    if r.status >= 400:
        return False
    return parser.looks_logged_in(r.text)


def _read_credentials(env: Optional[dict] = None) -> tuple[Optional[str], Optional[str]]:
    env = env if env is not None else os.environ
    email = env.get("WG_EMAIL")
    password = env.get("WG_PASSWORD")
    if email and password:
        return email, password
    # TTY-Fallback: nur wenn stdin ein TTY ist
    try:
        if not sys.stdin.isatty():
            return email, password
    except (AttributeError, OSError):
        return email, password
    try:
        if not email:
            email = input("WG-Gesucht E-Mail: ").strip()
        if not password:
            password = getpass.getpass("WG-Gesucht Passwort: ")
    except (EOFError, KeyboardInterrupt):
        raise AuthError("Abgebrochen.", code="cancelled") from None
    if not password:
        raise AuthError("Passwort darf nicht leer sein.", code="missing_credentials")
    return email or None, password or None


def login(*, http: HttpClient, env: Optional[dict] = None, store_path: Optional[str] = None) -> dict:
    """Login per JSON-POST gegen /ajax/sessions.php?action=login.

    1) Holt eine frische PHPSESSID von der Startseite.
    2) POST login_email_username + login_password als JSON.
    3) Erwartet 200 mit access_token in der Response; speichert alle
       relevanten Tokens als Cookies.
    4) Beweis: GET auf /nachrichten.html - muss eingeloggt aussehen.
    """
    email, password = _read_credentials(env)
    if not email or not password:
        raise AuthError(
            "Login fehlt: `wggesucht login` im Terminal ausführen oder "
            "WG_EMAIL/WG_PASSWORD setzen",
            code="missing_credentials",
        )

    # 1) Vorlogin: PHPSESSID holen. Server leitet meist auf /?modal=sign_in,
    # wenn noch nichts gesetzt ist - das ist OK, der Server vergibt PHPSESSID.
    base = base_url()
    try:
        warm = http.get(base + "/?modal=sign_in")
    except HTTPError as e:
        raise AuthError(f"Login-Warmup fehlgeschlagen: {e}", code="auth_failed") from e

    # 2) Echter Login-Versuch: JSON-POST
    payload = {
        "login_email_username": email,
        "login_password": password,
        "display_language": "de",
    }
    try:
        r = http.post(base + "/ajax/sessions.php?action=login", json=payload)
    except HTTPError as e:
        raise AuthError(f"Login-POST fehlgeschlagen: {e}", code="auth_failed") from e

    if r.status >= 400:
        try:
            err_data = json.loads(r.text)
            detail = err_data.get("detail") or err_data.get("title") or r.text[:200]
        except json.JSONDecodeError:
            detail = r.text[:200]
        raise AuthError(f"Login abgelehnt (HTTP {r.status}): {detail}", code="auth_failed")

    try:
        data = json.loads(r.text)
    except json.JSONDecodeError as e:
        raise AuthError(f"Login-Antwort kein JSON: {e}", code="auth_failed") from e
    access_token = data.get("access_token")
    if not access_token:
        raise AuthError(
            f"Login-Antwort ohne access_token: {r.text[:200]}",
            code="auth_failed",
        )

    # 3) Beweis: GET /nachrichten.html
    check = http.get(base + "/nachrichten.html")
    if not _is_logged_in_response(check):
        raise AuthError(
            "Login-Beweis fehlgeschlagen: /nachrichten.html sieht nicht eingeloggt aus",
            code="auth_failed",
        )

    cookies = _export_cookies(http)
    path = store_path or session_path()
    save_session(path, email=email, cookies=cookies, base_url=base)
    return {
        "ok": True,
        "user": email,
        "user_id": data.get("user_id"),
        "session_file": path,
        "cookie_anzahl": len(cookies),
    }


def _export_cookies(http) -> list[dict]:
    """Sammelt nur .wg-gesucht.de-Cookies.

    Funktioniert sowohl mit HttpClient (requests-basiert) als auch
    mit Test-Doubles, die ein ._export_cookies() anbieten.
    """
    if hasattr(http, "_export_cookies"):
        all_c = http._export_cookies()
    else:
        all_c = http._session.cookies  # type: ignore[attr-defined]
    out: list[dict] = []
    for c in all_c:
        if isinstance(c, dict):
            domain = (c.get("domain") or "").lower().lstrip(".")
            name = c.get("name")
            value = c.get("value")
            path = c.get("path", "/")
        else:
            domain = (getattr(c, "domain", "") or "").lower().lstrip(".")
            name = getattr(c, "name", None)
            value = getattr(c, "value", None)
            path = getattr(c, "path", "/")
        if not name or value is None:
            continue
        if not (domain.endswith("wg-gesucht.de") or domain == "wg-gesucht.de"):
            continue
        out.append({
            "name": name,
            "value": value,
            "domain": "." + domain if not domain.startswith(".") else domain,
            "path": path,
        })
    return out


def restore_session(http: HttpClient, store_path: Optional[str] = None) -> dict:
    from .http_client import load_session
    path = store_path or session_path()
    data = load_session(path)
    if not data:
        raise AuthError(
            "Login fehlt – `wggesucht login` ausführen", code="no_session"
        )
    http.load_cookies(data["cookies"])
    return data
