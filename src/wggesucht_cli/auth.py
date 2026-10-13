"""Login gegen wg-gesucht.de via HTTP-Form-POST.

Funktioniert mit einer normalen `requests`-Session, weil
wg-gesucht.de einen klassischen Formular-Login hat (Stand 2026-10-13).
Der Login-Endpoint ist **nicht** offiziell dokumentiert; die hier
verwendeten URLs sind aus dem gerenderten HTML abgeleitet und über
die Login-Seite reproduzierbar.

Wichtig: Ein erfolgreicher Login erfordert **Beweis** – das
bloße Setzen eines Session-Cookies reicht nicht (siehe
learnings/2026-10-08-login-erfolg-braucht-beweis.md).
"""

from __future__ import annotations

import getpass
import os
from typing import Any, Optional
from urllib.parse import urljoin

from . import parser
from .http_client import (
    AuthError,
    HttpClient,
    HTTPError,
    Response,
    save_session,
    session_path,
)


BASE = "https://www.wg-gesucht.de"
LOGIN_URL_CANDIDATES = [
    BASE + "/mein-wg-gesucht.html",
    BASE + "/mein-wg-gesucht",
    BASE + "/nachrichten.html",
]


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
        if not os.isatty(0):
            return email, password
    except OSError:
        return email, password
    if not email:
        email = input("WG-Gesucht E-Mail: ").strip()
    if not password:
        password = getpass.getpass("WG-Gesucht Passwort: ")
    return email or None, password or None


def login(*, http: HttpClient, env: Optional[dict] = None, store_path: Optional[str] = None) -> dict:
    email, password = _read_credentials(env)
    if not email or not password:
        raise AuthError("WG_EMAIL / WG_PASSWORD fehlen", code="missing_credentials")
    # 1) Login-Seite holen, um Formular-Action + versteckte Felder zu lesen
    last_err: Optional[Exception] = None
    for url in LOGIN_URL_CANDIDATES:
        try:
            r = http.get(url)
        except HTTPError as e:
            last_err = e
            continue
        if r.status >= 400:
            continue
        info = parser.parse_login_form(r.text)
        action = info["action"]
        fields = dict(info["fields"])
        fields["login_email"] = email
        fields["login_password"] = password
        # WG-Gesucht hat typischerweise "login_remember" / "login_submit"
        fields.setdefault("login_remember", "1")
        if not action:
            post_url = url
        else:
            post_url = action if "://" in action else urljoin(r.url, action)
        try:
            r2 = http.post(post_url, data=fields)
        except HTTPError as e:
            last_err = e
            continue
        # 2) Beweis: GET auf /nachrichten.html
        if _is_logged_in_response(r2):
            # session beweis auch noch über einen frischen GET auf /nachrichten
            check = http.get(BASE + "/nachrichten.html")
            if not _is_logged_in_response(check):
                continue
        else:
            # Manche Setups: nach POST direkt auf nachrichten umgeleitet.
            check = http.get(BASE + "/nachrichten.html")
            if not _is_logged_in_response(check):
                continue
        # Erfolg: Cookies speichern
        cookies = _export_cookies(http)
        path = store_path or session_path()
        save_session(path, email=email, cookies=cookies)
        return {
            "ok": True,
            "user": email,
            "session_file": path,
            "cookie_anzahl": len(cookies),
        }
    # Wenn wir hier ankommen, hat nichts geklappt
    if last_err:
        raise AuthError(f"Login fehlgeschlagen: {last_err}", code="auth_failed")
    raise AuthError("Login fehlgeschlagen (kein Beweis-Endpoint erreichbar)", code="auth_failed")


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
        # requests-Cookie: .domain, .name, .value, .path
        # Test-Cookie: dict
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
        raise AuthError("Keine Session gefunden", code="no_session")
    http.load_cookies(data["cookies"])
    return data
