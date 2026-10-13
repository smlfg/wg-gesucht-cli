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
import re
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


# ---------- Datum-Parser für CLI-Argumente ----------

def _parse_date_arg(value: str) -> str:
    """Akzeptiert ISO (YYYY-MM-DD) oder deutsch (DD.MM.YYYY) und liefert ISO."""
    s = (value or "").strip()
    if not s:
        raise argparse.ArgumentTypeError("leeres Datum")
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[0:10]
    if len(s) >= 10 and s[2] == "." and s[5] == ".":
        dd, mm, yyyy = s[0:2], s[3:5], s[6:10]
        if dd.isdigit() and mm.isdigit() and yyyy.isdigit():
            return f"{yyyy}-{mm}-{dd}"
    raise argparse.ArgumentTypeError(f"unerwartetes Datumsformat: {value!r} (YYYY-MM-DD oder DD.MM.YYYY)")


def _parse_int_list(value: str) -> list[int]:
    """Komma-getrennte Liste von Integers."""
    out: list[int] = []
    for part in (value or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(int(part))
        except ValueError as e:
            raise argparse.ArgumentTypeError(f"kein int: {part!r}") from e
    return out


def _parse_str_list(value: str) -> list[str]:
    return [p.strip() for p in (value or "").split(",") if p.strip()]


# ---------- search ----------

def _client_filter(args: argparse.Namespace, offers: list[dict]) -> list[dict]:
    """Filtert bereits geparste Angebote nach clientseitigen Kriterien."""
    if args.max_rent is not None:
        offers = [o for o in offers if o["kaltmiete_euro"] is None or o["kaltmiete_euro"] <= args.max_rent]
    if args.min_rent is not None:
        offers = [o for o in offers if o["kaltmiete_euro"] is None or o["kaltmiete_euro"] >= args.min_rent]
    if args.min_size is not None:
        offers = [o for o in offers if o["groesse_qm"] is None or o["groesse_qm"] >= args.min_size]
    if args.max_size is not None:
        offers = [o for o in offers if o["groesse_qm"] is None or o["groesse_qm"] <= args.max_size]
    if args.move_in_from:
        offers = [o for o in offers if o["verfuegbar_ab"] is None or o["verfuegbar_ab"] >= args.move_in_from]
    if args.move_in_to:
        offers = [o for o in offers if o["verfuegbar_ab"] is None or o["verfuegbar_ab"] <= args.move_in_to]
    if args.furnished is not None:
        want = "ja" if args.furnished == 1 else "nein"
        offers = [o for o in offers if o["moebliert"] is None or o["moebliert"] == want]
    if args.smoking is not None:
        # wg-gesucht-IDs 1=erlaubt 2=nicht 3=eigenes 4=balkon
        sm = {1: "erlaubt", 2: "nicht_erwuenscht", 3: "eigenes_zimmer", 4: "balkon"}.get(args.smoking)
        if sm:
            offers = [o for o in offers if o["rauchen"] is None or o["rauchen"] == sm]
    if args.min_flatmates is not None:
        offers = [o for o in offers if o["mitbewohner_anzahl"] is None or o["mitbewohner_anzahl"] >= args.min_flatmates]
    if args.max_flatmates is not None:
        offers = [o for o in offers if o["mitbewohner_anzahl"] is None or o["mitbewohner_anzahl"] <= args.max_flatmates]
    if args.district:
        needle = args.district.lower()
        offers = [o for o in offers if o["stadtteil"] and needle in o["stadtteil"].lower()]
    if args.limit:
        offers = offers[: args.limit]
    return offers


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
    # Falls gar keine Filter gesetzt sind, weniger aggressiv
    url = cities.build_search_url(
        city,
        rooms=rooms,
        max_rent=args.max_rent,
        min_rent=args.min_rent,
        min_size=args.min_size,
        max_size=args.max_size,
        radius=args.radius,
        move_in_from=args.move_in_from,
        move_in_to=args.move_in_to,
        rent_types=args.rent_types or None,
        wg_gender=args.wg_gender,
        wg_searched_gender=args.wg_searched_gender,
        flatmate_age_min=args.flatmate_age_min,
        flatmate_age_max=args.flatmate_age_max,
        flatmates_min=args.min_flatmates_index,
        flatmates_max=args.max_flatmates_index,
        flatshare_types=args.flatshare_types or None,
        furnished=args.furnished,
        smoking=args.smoking,
        pets_allowed=args.pets_allowed,
        pets_present=args.pets_present,
        kitchen=args.kitchen,
        district_ids=args.district_ids or None,
        offers_since=args.since,
        exchange=args.exchange,
        floor=args.floor,
        handicapped=args.handicapped,
        balcony=args.balcony,
        garden=args.garden,
        online_tour=args.online_tour,
        images_only=args.images_only,
    )
    http = HttpClient()
    try:
        r = http.get(url)
    except HTTPError as e:
        _err(f"HTTP-Fehler: {e}", code=3, status=e.status)
    if r.status >= 400:
        _err(f"HTTP {r.status} beim Laden der Suche", code=3, status=r.status, url=url)
    try:
        offers = parser.parse_search(r.text, limit=args.limit or 20, room_type=rooms)
    except ParseError as e:
        _err(f"Parse-Fehler: {e}", code=4, url=url)
    offers = _client_filter(args, offers)
    payload = {
        "quelle": "https://www.wg-gesucht.de",
        "stadt": args.city,
        "filter": {
            "max_rent": args.max_rent,
            "min_rent": args.min_rent,
            "min_size": args.min_size,
            "max_size": args.max_size,
            "rooms": rooms,
            "radius": args.radius,
            "move_in_from": args.move_in_from,
            "move_in_to": args.move_in_to,
            "rent_types": args.rent_types or None,
            "wg_gender": args.wg_gender,
            "wg_searched_gender": args.wg_searched_gender,
            "flatmate_age_min": args.flatmate_age_min,
            "flatmate_age_max": args.flatmate_age_max,
            "min_flatmates": args.min_flatmates,
            "max_flatmates": args.max_flatmates,
            "flatshare_types": args.flatshare_types or None,
            "furnished": args.furnished,
            "smoking": args.smoking,
            "pets_allowed": args.pets_allowed,
            "pets_present": args.pets_present,
            "kitchen": args.kitchen,
            "district": args.district,
            "district_ids": args.district_ids or None,
            "since": args.since,
            "exchange": args.exchange,
            "floor": args.floor,
            "handicapped": args.handicapped,
            "balcony": args.balcony,
            "garden": args.garden,
            "online_tour": args.online_tour,
            "images_only": args.images_only,
            "limit": args.limit,
        },
        "url": url,
        "hinweis": None,
        "anzahl": len(offers),
        "angebote": offers,
    }
    _emit(payload, args.json)
    return 0


# ---------- show ----------

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


# ---------- login / logout / messages ----------

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


# ---------- Argument-Parser ----------

def _add_search_filters(s: argparse.ArgumentParser) -> None:
    """Alle Such-Filter als zusammengehörige Gruppe."""
    f = s.add_argument_group("Filter")
    f.add_argument("--max-rent", type=int, default=None, help="max. Kaltmiete in €")
    f.add_argument("--min-rent", type=int, default=None, help="min. Kaltmiete in €")
    f.add_argument("--min-size", type=int, default=None, help="min. Zimmergröße in m²")
    f.add_argument("--max-size", type=int, default=None, help="max. Zimmergröße in m²")
    f.add_argument("--radius", type=int, default=None, help="Umkreis in Metern (z. B. 1000 = 1 km)")
    f.add_argument("--move-in-from", type=_parse_date_arg, default=None,
                   help="frühestes Einzugsdatum (YYYY-MM-DD)")
    f.add_argument("--move-in-to", type=_parse_date_arg, default=None,
                   help="spätestes Einzugsdatum (YYYY-MM-DD)")
    f.add_argument("--rent-type", dest="rent_types", type=_parse_int_list, default=None,
                   help="Mietdauer 1=befristet,2=unbefristet,3=Übernachtung (komma-getrennt)")
    f.add_argument("--wg-gender", type=int, choices=[1, 2, 4, 5], default=None,
                   help="Geschlecht der Mitbewohner 1=Frau 2=Mann 4=Divers 5=keine Angabe")
    f.add_argument("--wg-searched-gender", type=int, choices=[1, 2, 3, 4], default=None,
                   help="gesuchtes Geschlecht 1=Frau 2=Mann 3=Divers 4=keine Angabe")
    f.add_argument("--flatmate-age-min", type=int, default=None,
                   help="Mindestalter der Mitbewohner")
    f.add_argument("--flatmate-age-max", type=int, default=None,
                   help="Höchstalter der Mitbewohner")
    f.add_argument("--min-flatmates", type=int, default=None,
                   help="Mindestanzahl Mitbewohner (Personen, z. B. 3 für 3er-WG)")
    f.add_argument("--max-flatmates", type=int, default=None,
                   help="Maximalanzahl Mitbewohner (Personen)")
    f.add_argument("--flatshare-type", dest="flatshare_types", type=_parse_int_list, default=None,
                   help="WG-Art: 0=Zweck,1=Studenten,2=Frauen,6=Berufstätigen,"
                        "11=keine Zweck,12=gemischte,16=LGBTQIA+,19=Internationals (komma-getrennt)")
    f.add_argument("--furnished", type=int, choices=[1, 2], default=None,
                   help="1=möbliert, 2=nicht möbliert")
    f.add_argument("--smoking", type=int, choices=[1, 2, 3, 4], default=None,
                   help="Rauchen 1=erlaubt 2=nicht erwünscht 3=eigenes Zimmer 4=Balkon")
    f.add_argument("--pets-allowed", type=int, choices=[1, 2], default=None,
                   help="Haustiere erlaubt: 1=ja 2=nein")
    f.add_argument("--pets-present", type=int, choices=[1, 2], default=None,
                   help="Haustiere vorhanden: 1=ja 2=nein")
    f.add_argument("--kitchen", type=int, choices=[1, 2], default=None,
                   help="eigene Küche: 1=ja 2=nein")
    f.add_argument("--district", default=None,
                   help="Stadtteil-Filter (Substring-Match auf stadtteil)")
    f.add_argument("--district-id", dest="district_ids", type=_parse_int_list, default=None,
                   help="Stadtteil-IDs (kommasepariert, wg-gesucht-intern)")
    f.add_argument("--since", type=int, default=None,
                   help="Anzeigen seit 1=3T, 2=1W, 3=2W, 4=3W, 5=1M, 6=2M, 7=3M")
    f.add_argument("--exchange", type=int, choices=[1, 2], default=None,
                   help="Tauschwohnung: 1=ja 2=nein")
    f.add_argument("--floor", type=int, default=None, help="Etage laut wg-gesucht-Index")
    f.add_argument("--handicapped", action="store_true", help="rollstuhlgerecht")
    f.add_argument("--balcony", action="store_true", help="Balkon / Terrasse")
    f.add_argument("--garden", action="store_true", help="Garten")
    f.add_argument("--online-tour", action="store_true", help="Online-Besichtigung")
    f.add_argument("--images-only", action="store_true", help="nur Anzeigen mit Bildern")
    # interne Hilfsfelder für die Index-→ Anzahl-Mapping
    s.add_argument("--min-flatmates-index", default=None,
                   help=argparse.SUPPRESS)
    s.add_argument("--max-flatmates-index", default=None,
                   help=argparse.SUPPRESS)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="wggesucht",
        description="wggesucht – Agent-CLI für wg-gesucht.de (Suche, Login, Nachrichten).",
    )
    p.add_argument("--version", action="version", version=f"wggesucht {__version__}")
    sub = p.add_subparsers(dest="cmd", metavar="SUBCOMMAND")
    # search
    s = sub.add_parser("search", help="WG-/Wohnungs-Angebote suchen")
    s.add_argument("--city", required=True, help="Stadt, z.B. Berlin oder Heilbronn")
    s.add_argument(
        "--rooms",
        choices=["wg", "1zimmer", "wohnung", "haus"],
        default="wg",
    )
    s.add_argument("--limit", type=int, default=20)
    s.add_argument("--json", action="store_true")
    _add_search_filters(s)
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
    # Konvertiere min/max_flatmates (Anzahl Personen) in die
    # wg-gesucht-Index-Werte (1=2er, 2=3er, …).
    if getattr(args, "min_flatmates", None) is not None and getattr(args, "min_flatmates_index", None) is None:
        # Anzahl → Index: 1=2er → -1; 2=2er → 1; 3=3er → 2; …
        args.min_flatmates_index = max(0, args.min_flatmates - 1) if args.min_flatmates > 1 else 1
    if getattr(args, "max_flatmates", None) is not None and getattr(args, "max_flatmates_index", None) is None:
        args.max_flatmates_index = max(0, args.max_flatmates - 1) if args.max_flatmates > 1 else 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
