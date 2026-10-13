"""HTTP-Client-Wrapper (requests-Session) für wg-gesucht.de.

Stellt eine dünne Abstraktion bereit, die in Tests mit einem
Fake ersetzt werden kann.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional
from urllib.parse import urlparse

import requests

UA = "wg-gesucht-cli/0.1.0 (+https://github.com/smlfg/wg-gesucht-cli)"


class HTTPError(Exception):
    """Netzwerk- oder HTTP-Fehler (Exit 3)."""

    def __init__(self, message: str, status: Optional[int] = None, url: Optional[str] = None):
        super().__init__(message)
        self.status = status
        self.url = url


class ParseError(Exception):
    """Antwort konnte nicht wie erwartet geparst werden (Exit 4)."""

    def __init__(self, message: str, url: Optional[str] = None):
        super().__init__(message)
        self.url = url


class AuthError(Exception):
    """Login-Problem / fehlende Session (Exit 2)."""

    def __init__(self, message: str, code: str = "auth_failed"):
        super().__init__(message)
        self.code = code


class ActionDenied(Exception):
    """Aktion verweigert (z. B. send ohne --confirm) (Exit 5)."""

    def __init__(self, message: str, code: str = "action_denied"):
        super().__init__(message)
        self.code = code


@dataclass
class Response:
    status: int
    url: str
    text: str
    headers: dict = field(default_factory=dict)
    cookies: dict = field(default_factory=dict)

    def raise_for_status(self) -> None:
        if self.status >= 400:
            raise HTTPError(f"HTTP {self.status} for {self.url}", status=self.status, url=self.url)


class HttpClient:
    """Einfache Wrapper-Klasse, austauschbar in Tests."""

    def __init__(self, user_agent: str = UA, timeout: float = 30.0, session: Optional[requests.Session] = None):
        self.user_agent = user_agent
        self.timeout = timeout
        self._session = session or requests.Session()
        self._session.headers.setdefault("User-Agent", user_agent)
        self._session.headers.setdefault("Accept-Language", "de-DE,de;q=0.9,en;q=0.5")

    def get(self, url: str, *, allow_redirects: bool = True) -> Response:
        try:
            r = self._session.get(url, timeout=self.timeout, allow_redirects=allow_redirects)
        except requests.RequestException as e:
            raise HTTPError(f"GET {url} failed: {e}", url=url) from e
        return Response(
            status=r.status_code,
            url=r.url,
            text=r.text,
            headers=dict(r.headers),
            cookies={c.name: c.value for c in r.cookies},
        )

    def post(self, url: str, *, data: Mapping[str, Any] | None = None,
             json: Any = None,
             allow_redirects: bool = True) -> Response:
        try:
            r = self._session.post(
                url,
                data=data,
                json=json,
                timeout=self.timeout,
                allow_redirects=allow_redirects,
            )
        except requests.RequestException as e:
            raise HTTPError(f"POST {url} failed: {e}", url=url) from e
        return Response(
            status=r.status_code,
            url=r.url,
            text=r.text,
            headers=dict(r.headers),
            cookies={c.name: c.value for c in r.cookies},
        )

    def cookies(self) -> dict[str, str]:
        return {c.name: c.value for c in self._session.cookies}

    def load_cookies(self, jar: list[dict]) -> None:
        """Setzt Cookies aus einem Session-JSON."""
        for c in jar:
            if not _cookie_allowed(c.get("domain", "")):
                continue
            self._session.cookies.set(
                c["name"],
                c["value"],
                domain=c.get("domain") or ".wg-gesucht.de",
                path=c.get("path", "/"),
            )


def _cookie_allowed(domain: str) -> bool:
    """Allowlist: nur wg-gesucht.de-Cookies (kein Identity-Provider)."""
    d = domain.lower().lstrip(".")
    return d.endswith("wg-gesucht.de") or d == "wg-gesucht.de"


def session_path() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "wg-gesucht-cli", "session.json")


def save_session(path: str, email: str, cookies: list[dict], base_url: str = "https://www.wg-gesucht.de") -> None:
    import os as _os
    _os.makedirs(_os.path.dirname(path), exist_ok=True)
    _os.chmod(_os.path.dirname(path), 0o700)
    payload = {
        "version": 1,
        "email": email,
        "base_url": base_url,
        "cookies": cookies,
    }
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    _os.chmod(tmp, 0o600)
    _os.replace(tmp, path)
    try:
        _os.chmod(path, 0o600)
    except OSError:
        pass


def load_session(path: str) -> Optional[dict]:
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or data.get("version") != 1:
        return None
    cookies = data.get("cookies") or []
    # nochmal Allowlist beim Laden
    cookies = [c for c in cookies if _cookie_allowed(c.get("domain", ""))]
    return {
        "version": 1,
        "email": data.get("email"),
        "base_url": data.get("base_url", "https://www.wg-gesucht.de"),
        "cookies": cookies,
    }


def clear_session(path: str) -> bool:
    """Idempotent: löscht die Session-Datei, gibt True zurück, falls eine da war."""
    if not os.path.exists(path):
        return False
    try:
        os.remove(path)
        return True
    except OSError:
        return False
