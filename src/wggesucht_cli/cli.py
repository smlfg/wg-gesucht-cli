"""CLI für wggesucht (smlfg/wg-gesucht-cli).

Subbefehle:
  search       Suche (öffentlich, kein Login)
  show         Anzeigen-Details (öffentlich)
  login        Login (WG_EMAIL/WG_PASSWORD), Session speichern
  logout       Session löschen (idempotent)
  messages     list | read | send
  --version
  --help
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, NoReturn, Optional

from . import __version__, auth, cities, messages, parser
from .http_client import (
    ActionDenied,
    AuthError,
    clear_session,
    HttpClient,
    HTTPError,
    ParseError,
    session_path,
)


def _emit(payload: Any, as_json: bool) -> None:
    if as_json:
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
        sys.stdout.write("\n")
    else:
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
        sys.stdout.write("\n")


def _err(msg: str, *, code: int, **extra: Any) -> NoReturn:
    payload = {"error": msg, **extra}
    sys.stderr.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.exit(code)


def cmd_search(args: argparse.Namespace) -> int:
    city = cities.resolve_city(args.city)
    if not city:
        _err(
            f"Unbekannte Stadt: {args.city!r}. Verfügbar (Auszug): "
            + ", ".join(cities.list_cities()[:10]),
            code=1,
        )
    rooms = args.rooms or "wg"
    if rooms not in ("wg", "1zimmer", "wohnung", "haus"):
        _err(f"Unbekannter --rooms: {rooms!r}", code=1)
    url = cities.build_search_url(
        city,
        rooms=rooms,
        max_rent=args.max_rent,
        min_size=args.min_size,
        radius=args.radius,
    )
    http = HttpClient()
    try:
        r = http.get(url)
    except HTTPError as e:
        _err(f"HTTP-Fehler: {e}", code=3, status=e.status)
    if r.status >= 400:
        _err(f"HTTP {r.status} beim Laden der Suche", code=3, status=r.status, url=url)
    try:
        offers = parser.parse_search(r.text, limit=args.limit, room_type=rooms)
    except ParseError as e:
        _err(f"Parse-Fehler: {e}", code=4, url=url)
    # Filter anwenden (URL-Parameter werden von wg-gesucht ignoriert,
    # also clientseitig nachfiltern)
    if args.max_rent is not None:
        offers = [o for o in offers if o["kaltmiete_euro"] is None or o["kaltmiete_euro"] <= args.max_rent]
    if args.min_size is not None:
        offers = [o for o in offers if o["groesse_qm"] is None or o["groesse_qm"] >= args.min_size]
    if args.limit:
        offers = offers[: args.limit]
    payload = {
        "quelle": "https://www.wg-gesucht.de",
        "stadt": args.city,
        "filter": {
            "max_rent": args.max_rent,
            "min_size": args.min_size,
            "rooms": rooms,
            "radius": args.radius,
            "limit": args.limit,
        },
        "hinweis": None,
        "anzahl": len(offers),
        "angebote": offers,
    }
    _emit(payload, args.json)
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    try:
        offer_id = parser.normalize_offer_input(args.offer)
    except ValueError as e:
        _err(str(e), code=1)
    url = parser.detail_url(offer_id)
    http = HttpClient()
    try:
        r = http.get(url)
    except HTTPError as e:
        _err(f"HTTP-Fehler: {e}", code=3, status=e.status)
    if r.status >= 400:
        _err(f"HTTP {r.status} beim Laden der Anzeige", code=3, status=r.status, url=url)
    try:
        ang = parser.parse_detail(r.text)
    except ParseError as e:
        _err(f"Parse-Fehler: {e}", code=4, url=url)
    if not ang.get("id"):
        ang["id"] = offer_id
    if not ang.get("url"):
        ang["url"] = r.url
    _emit({"quelle": "https://www.wg-gesucht.de", "angebot": ang}, args.json)
    return 0


def cmd_login(args: argparse.Namespace) -> int:
    http = HttpClient()
    try:
        res = auth.login(http=http, env=os.environ, store_path=session_path())
    except AuthError as e:
        _err(str(e), code=2, kind=e.code)
    _emit(res, args.json)
    return 0


def cmd_logout(args: argparse.Namespace) -> int:
    removed = clear_session(session_path())
    _emit({"ok": True, "session_entfernt": removed}, args.json)
    return 0


def cmd_messages_list(args: argparse.Namespace) -> int:
    http = HttpClient()
    try:
        res = messages.list_messages(http)
    except AuthError as e:
        _err(str(e), code=2, kind=e.code, hint="wggesucht login")
    except HTTPError as e:
        _err(f"HTTP-Fehler: {e}", code=3, status=e.status)
    _emit(res, args.json)
    return 0


def cmd_messages_read(args: argparse.Namespace) -> int:
    http = HttpClient()
    try:
        res = messages.read_thread(http, args.thread_id)
    except AuthError as e:
        _err(str(e), code=2, kind=e.code, hint="wggesucht login")
    except HTTPError as e:
        _err(f"HTTP-Fehler: {e}", code=3, status=e.status)
    _emit(res, args.json)
    return 0


def cmd_messages_send(args: argparse.Namespace) -> int:
    if not args.confirm:
        _err(
            "Senden verlangt --confirm; ohne wird nichts abgeschickt.",
            code=5,
            kind="confirm_required",
        )
    http = HttpClient()
    try:
        res = messages.send_message(
            http, to=args.to, text=args.text, confirm=True
        )
    except ActionDenied as e:
        _err(str(e), code=5, kind=e.code)
    except AuthError as e:
        _err(str(e), code=2, kind=e.code, hint="wggesucht login")
    except HTTPError as e:
        _err(f"HTTP-Fehler: {e}", code=3, status=e.status)
    _emit(res, args.json)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="wggesucht",
        description="wggesucht – Agent-CLI für wg-gesucht.de (Suche, Login, Nachrichten).",
    )
    p.add_argument("--version", action="version", version=f"wggesucht {__version__}")
    sub = p.add_subparsers(dest="cmd", metavar="SUBCOMMAND")
    # search
    s = sub.add_parser("search", help="WG-/Wohnungs-Angebote suchen")
    s.add_argument("--city", required=True, help="Stadt, z.B. Berlin")
    s.add_argument("--max-rent", type=int, default=None, help="max. Kaltmiete in €")
    s.add_argument("--min-size", type=int, default=None, help="min. Zimmergröße in m²")
    s.add_argument(
        "--rooms",
        choices=["wg", "1zimmer", "wohnung", "haus"],
        default="wg",
    )
    s.add_argument("--radius", type=int, default=None, help="Umkreis in km")
    s.add_argument("--limit", type=int, default=20)
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_search)
    # show
    sh = sub.add_parser("show", help="Anzeigen-Details anzeigen")
    sh.add_argument("offer", help="Anzeigen-ID oder URL")
    sh.add_argument("--json", action="store_true")
    sh.set_defaults(func=cmd_show)
    # login
    li = sub.add_parser("login", help="Login mit WG_EMAIL/WG_PASSWORD")
    li.add_argument("--json", action="store_true")
    li.set_defaults(func=cmd_login)
    # logout
    lo = sub.add_parser("logout", help="Session löschen (idempotent)")
    lo.add_argument("--json", action="store_true")
    lo.set_defaults(func=cmd_logout)
    # messages
    m = sub.add_parser("messages", help="Posteingang (list/read/send)")
    msub = m.add_subparsers(dest="mcmd", metavar="ACTION")
    ml = msub.add_parser("list", help="Threads auflisten")
    ml.add_argument("--json", action="store_true")
    ml.set_defaults(func=cmd_messages_list)
    mr = msub.add_parser("read", help="Thread lesen")
    mr.add_argument("thread_id")
    mr.add_argument("--json", action="store_true")
    mr.set_defaults(func=cmd_messages_read)
    ms = msub.add_parser("send", help="Nachricht senden (nur mit --confirm)")
    ms.add_argument("--to", required=True, help="Empfänger (User-ID oder Anzeigen-ID)")
    ms.add_argument("--text", required=True, help="Nachrichtentext")
    ms.add_argument("--confirm", action="store_true", help="Explizit bestätigen")
    ms.add_argument("--json", action="store_true")
    ms.set_defaults(func=cmd_messages_send)
    return p


def main(argv: Optional[list[str]] = None) -> int:
    parser_ = _build_parser()
    args = parser_.parse_args(argv)
    if not getattr(args, "func", None):
        parser_.print_help(sys.stderr)
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
