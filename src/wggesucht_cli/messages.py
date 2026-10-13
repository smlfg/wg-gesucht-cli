"""Posteingang lesen / Nachrichten senden."""

from __future__ import annotations

import re
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
    sess = _ensure_session(http)
    url = f"{BASE}/nachrichten/{thread_id}.html"
    r = http.get(url)
    if r.status >= 400 or not parser.looks_logged_in(r.text):
        raise AuthError("Session abgelaufen oder ungültig", code="session_expired")
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(r.text, "lxml")
    subject_node = soup.find("h1") or soup.find("h2")
    subject = subject_node.get_text(strip=True) if subject_node else None
    # Nachrichten
    msgs: list[dict] = []
    for msg_div in soup.find_all("div", class_=re.compile(r"message_(row|body|item)|nachricht")):
        von = None
        von_node = msg_div.find(class_=re.compile(r"sender|absender|user_name"))
        if von_node:
            von = von_node.get_text(strip=True)
        datum = None
        datum_node = msg_div.find(class_=re.compile(r"date|datum|time"))
        if datum_node:
            datum = datum_node.get_text(strip=True)
        # body
        body_node = msg_div.find(class_=re.compile(r"text|body|content")) or msg_div.find("p")
        text = body_node.get_text("\n", strip=True) if body_node else None
        msgs.append({"von": von, "datum": datum, "text": text})
    return {
        "quelle": url,
        "thread": {
            "thread_id": thread_id,
            "subject": subject,
            "nachrichten": msgs,
        },
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
