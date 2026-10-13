"""Posteingang lesen / Nachrichten senden.

Hinweis zu Pfaden (Stand 2026-10-13, reproduziert mit eingeloggtem
Browser-Use gegen wg-gesucht.de):
- Liste: GET https://www.wg-gesucht.de/nachrichten.html  (Mehrzahl!)
- Thread: GET https://www.wg-gesucht.de/nachricht.html?nachrichten-id=<ID>
          (Einzahl!) - hier ANZEIGEN steht eine Detail-Karte, sonst steht
          "Diese Anzeige wurde gelöscht".
"""

from __future__ import annotations

from typing import Optional
from urllib.parse import urljoin

from . import parser
from .auth import restore_session
from .http_client import (
    ActionDenied,
    AuthError,
    HttpClient,
    HTTPError,
)

BASE = "https://www.wg-gesucht.de"


def _ensure_session(http: HttpClient) -> dict:
    try:
        return restore_session(http)
    except AuthError:
        raise


def list_messages(http: HttpClient) -> dict:
    sess = _ensure_session(http)
    r = http.get(BASE + "/nachrichten.html")
    if r.status >= 400 or not parser.looks_logged_in(r.text):
        raise AuthError("Session abgelaufen oder ungültig", code="session_expired")
    threads = parser.parse_messages_list(r.text)
    return {
        "quelle": BASE + "/nachrichten.html",
        "user": sess.get("email"),
        "anzahl": len(threads),
        "threads": threads,
    }


def read_thread(http: HttpClient, thread_id: str) -> dict:
    """Liest eine Konversation.

    ``thread_id`` ist die ``nachrichten-id`` aus der ``/nachricht.html``-URL.
    """
    if not thread_id or not thread_id.isdigit():
        raise ValueError(f"ungültige thread_id: {thread_id!r}")
    sess = _ensure_session(http)
    url = f"{BASE}/nachricht.html?nachrichten-id={thread_id}&list=1"
    r = http.get(url)
    if r.status >= 400 or not parser.looks_logged_in(r.text):
        raise AuthError("Session abgelaufen oder ungültig", code="session_expired")
    payload = parser.parse_thread(r.text, thread_id=thread_id)
    return {
        "quelle": url,
        "thread": payload,
    }


def send_message(http: HttpClient, *, to: str, text: str, confirm: bool = False) -> dict:
    if not confirm:
        raise ActionDenied(
            "Nachricht Senden verlangt --confirm; ohne wird nichts abgeschickt.",
            code="confirm_required",
        )
    sess = _ensure_session(http)
    # WG-Gesucht hat einen Endpoint /nachrichten/send-message.html
    # mit einem Formular. Ziel = to (User-ID oder Anzeigen-ID).
    page = http.get(BASE + "/nachrichten/send-message.html?user_id=" + to)
    if page.status >= 400 or not parser.looks_logged_in(page.text):
        raise AuthError("Session abgelaufen oder ungültig", code="session_expired")
    info = parser.parse_login_form(page.text)
    fields = dict(info["fields"])
    fields["message_text"] = text
    fields["user_id"] = to
    post_url = info["action"] or BASE + "/nachrichten/send-message.html"
    if not post_url.startswith("http"):
        post_url = urljoin(page.url, post_url)
    r = http.post(post_url, data=fields)
    if r.status >= 400:
        raise HTTPError(f"Senden fehlgeschlagen (HTTP {r.status})", status=r.status, url=post_url)
    from datetime import datetime
    return {
        "ok": True,
        "an": to,
        "gesendet_am": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
