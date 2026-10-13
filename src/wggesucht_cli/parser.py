"""HTML-Parser für wg-gesucht.de.

Nur lesen, nichts klicken. Die hier implementierten Strategien
basieren auf Live-Smoke gegen wg-gesucht.de (Stand 2026-10-13).
Wenn die Seite ihre Struktur ändert, liefern die Parser
ParseError – der Aufrufer entscheidet, ob das ein Fehler ist.
"""

from __future__ import annotations

import re
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .http_client import ParseError, Response

BASE = "https://www.wg-gesucht.de"

# Akzeptanz für das Datum
_DATE_PATTERNS = [
    "%d.%m.%Y",
]


def _norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _text(node) -> str:
    if node is None:
        return ""
    return _norm_ws(node.get_text(" "))


def _parse_date(s: str) -> Optional[str]:
    """Liefert ISO-Datum (YYYY-MM-DD) oder None."""
    s = (s or "").strip()
    if not s:
        return None
    from datetime import datetime
    for pat in _DATE_PATTERNS:
        try:
            return datetime.strptime(s, pat).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _eur_to_int(s: str) -> Optional[int]:
    if s is None:
        return None
    m = re.search(r"(\d[\d.,]*)", s)
    if not m:
        return None
    raw = m.group(1).replace(".", "").replace(",", "")
    try:
        return int(raw)
    except ValueError:
        return None


def _qm_to_int(s: str) -> Optional[int]:
    if s is None:
        return None
    m = re.search(r"(\d[\d.,]*)", s)
    if not m:
        return None
    raw = m.group(1).replace(".", "").replace(",", "")
    try:
        return int(raw)
    except ValueError:
        return None


def _slug_from_url(url: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Liefert (stadt, stadtteil, slug) aus einer Anzeigen-URL.

    Beispiel: /wg-zimmer-in-Berlin-Friedrichshagen.13374505.html
    """
    path = urlparse(url).path.lstrip("/")
    m = re.match(r"(?P<slug>[^.]+)\.(?P<id>\d+)\.html$", path)
    if not m:
        return None, None, None
    slug = m.group("slug")
    # /wg-zimmer-in-<Stadt>-<Stadtteil>  / 1-zimmer-wohnungen-in-<Stadt>
    parts = slug.split("-in-", 1)
    if len(parts) != 2:
        return None, None, slug
    rest = parts[1]
    # Wenn die URL keinen Bindestrich im Rest hat, ist stadt == rest, kein stadtteil
    if "-" not in rest:
        return rest, None, slug
    # Stadt ist der erste Bindestrich-getrennte Block, danach stadtteil
    stadt, _, stadtteil = rest.partition("-")
    return stadt, stadtteil, slug


def parse_search(html: str, *, limit: int = 20, room_type: str = "wg") -> list[dict]:
    """Parst die Liste der Anzeigen."""
    soup = BeautifulSoup(html, "lxml")
    cards = soup.find_all("div", class_=re.compile(r"offer_list_item"))
    results: list[dict] = []
    for card in cards:
        oid = card.get("data-id")
        if not oid:
            # Anzeigenkarten haben immer eine data-id. Werbung/Ad-Container nicht.
            continue
        link = card.find("a", href=re.compile(r"/(wg-zimmer|1-zimmer-wohnungen|wohnungen|haeuser)-in-"))
        if not link or not link.get("href"):
            continue
        href = urljoin(BASE, link["href"])
        title_node = card.find("h2", class_=re.compile(r"truncate_title"))
        title = _text(title_node) if title_node else None
        stadt, stadtteil, _slug = _slug_from_url(href)
        # Ort/Stadtteil/Straße – ein <span> enthält "Xer WG | Berlin Stadtteil | Straße"
        ort_text = None
        for span in card.find_all("span"):
            txt = span.get_text(" ", strip=True)
            if "er WG" in txt and "|" in txt:
                ort_text = txt
                break
        ort_parts = [p.strip(" |") for p in ort_text.split("|")] if ort_text else []
        stadt_text = stadt
        stadtteil_text = stadtteil
        strasse = None
        if len(ort_parts) >= 2:
            ort2 = ort_parts[1].strip()
            # "Berlin Friedrichshagen" → stadt="Berlin", stadtteil="Friedrichshagen"
            tokens = ort2.split()
            if stadt and stadt.lower() in ort2.lower():
                # Stadt am Anfang
                if len(tokens) >= 2 and tokens[0].lower() == stadt.lower():
                    stadtteil_text = " ".join(tokens[1:]) or None
            else:
                # stadt ist None (URL-only hatte kein Ort)
                stadt_text = tokens[0] if tokens else None
                if len(tokens) > 1:
                    stadtteil_text = " ".join(tokens[1:])
        if len(ort_parts) >= 3:
            strasse = ort_parts[2].strip() or None
        # Miete / Größe / Verfügbarkeit. Wir betrachten nur die direkten
        # Kinder des Cards mit class="row" (Titel/Adresse/Mitte/Unten),
        # keine rekursiv verschachtelten divs, damit z. B. "0m" aus
        # "title=2er WG (0w,0m,…)" oder "mdi-20px" nicht als Größe
        # erkannt werden.
        rent = None
        size = None
        avail_from = None
        avail_to = None
        for div in card.find_all("div", class_=re.compile(r"\brow\b"), recursive=False):
            inner_html = div.decode_contents()
            if rent is None and ("&euro;" in inner_html or "€" in inner_html):
                m = re.search(r"(\d[\d.,]*)\s*(?:&euro;|€)", inner_html)
                if m:
                    rent = _eur_to_int(m.group(1))
            if size is None and ("m&sup2;" in inner_html or "m²" in inner_html):
                m = re.search(r"(\d[\d.,]*)\s*(?:m&sup2;|m²)", inner_html)
                if m:
                    size = _qm_to_int(m.group(1))
            dates = re.findall(r"(\d{2}\.\d{2}\.\d{4})", inner_html)
            if len(dates) >= 2 and ("-" in inner_html or "–" in inner_html or "&ndash;" in inner_html):
                if avail_from is None:
                    avail_from = _parse_date(dates[0])
                avail_to = _parse_date(dates[1])
            elif len(dates) == 1 and "ab" in inner_html.lower() and avail_from is None:
                avail_from = _parse_date(dates[0])
        # Fallback für Größe: aus dem "noprint title"-Attribut
        if size is None:
            for span in card.find_all("span", attrs={"title": True}):
                t = span.get("title", "")
                if "m²" in t or "m&sup2;" in t:
                    size = _qm_to_int(t)
                    if size is not None:
                        break
        # Mitbewohner-Infos: Anzahl, Geschlecht, Alter – werden in
        # <span class="noprint">…</span> oder direkt im Body angezeigt,
        # z. B. "3er WG | Frau | 24 Jahre" oder "2er WG | 2 Männer, 1 Frau".
        flatmates_total = None
        flatmates_male = None
        flatmates_female = None
        flatmates_diverse = None
        flatmate_age_text = None
        furnished_flag = None
        smoking_flag = None
        for tag in card.find_all(["span", "div"], class_=re.compile(r"noprint|row|vis-title|key_fact")):
            txt = _text(tag)
            if not txt:
                continue
            m = re.search(r"(\d+)\s*er\s*WG", txt)
            if m and flatmates_total is None:
                try:
                    flatmates_total = int(m.group(1))
                except ValueError:
                    pass
            mm = re.search(r"(\d+)\s*M[äa]nn(?:er)?", txt)
            if mm and flatmates_male is None:
                flatmates_male = int(mm.group(1))
            mf = re.search(r"(\d+)\s*Frau(?:en)?", txt)
            if mf and flatmates_female is None:
                flatmates_female = int(mf.group(1))
            md = re.search(r"(\d+)\s*Divers", txt, re.I)
            if md and flatmates_diverse is None:
                flatmates_diverse = int(md.group(1))
            age_m = re.search(r"(\d{2})\s*(?:Jahre|J\.)\b", txt)
            if age_m and flatmate_age_text is None:
                flatmate_age_text = age_m.group(1)
            if "möbliert" in txt.lower() and furnished_flag is None:
                furnished_flag = "ja" if "möbliert" in txt.lower() and "nicht" not in txt.lower() else "nein"
            if "rauchen" in txt.lower() and smoking_flag is None:
                if "nicht" in txt.lower():
                    smoking_flag = "nicht_erwuenscht"
                elif "eigenen" in txt.lower() or "eigenes" in txt.lower():
                    smoking_flag = "eigenes_zimmer"
                elif "balkon" in txt.lower():
                    smoking_flag = "balkon"
                else:
                    smoking_flag = "erlaubt"
        # Fallback: "Xer WG" aus dem Ort-Text (z. B. "3er WG | …")
        if flatmates_total is None and ort_text:
            m = re.search(r"(\d+)\s*er\s*WG", ort_text)
            if m:
                try:
                    flatmates_total = int(m.group(1))
                except ValueError:
                    pass
        results.append({
            "id": str(oid),
            "url": href,
            "titel": title,
            "stadt": stadt_text,
            "stadtteil": stadtteil_text,
            "strasse": strasse,
            "kaltmiete_euro": rent,
            "groesse_qm": size,
            "verfuegbar_ab": avail_from,
            "verfuegbar_bis": avail_to,
            "typ": room_type,
            "mitbewohner_anzahl": flatmates_total,
            "mitbewohner_maennlich": flatmates_male,
            "mitbewohner_weiblich": flatmates_female,
            "mitbewohner_divers": flatmates_diverse,
            "mitbewohner_alter_text": flatmate_age_text,
            "moebliert": furnished_flag,
            "rauchen": smoking_flag,
        })
        if len(results) >= limit:
            break
    return results


def parse_detail(html: str) -> dict:
    """Parst eine Anzeigen-Detailseite."""
    soup = BeautifulSoup(html, "lxml")
    # data-ad_id oder URL mit ID
    ad_id = None
    m = re.search(r'data-ad_id="(\d+)"', html)
    if m:
        ad_id = m.group(1)
    h1 = soup.find("h1", class_=re.compile(r"detailed-view-title"))
    if h1 is None:
        h1 = soup.find("h1")
    title = _norm_ws(h1.get_text(" ")) if h1 else None
    # URL/Ort
    canonical = soup.find("link", rel="canonical")
    url = canonical["href"] if canonical and canonical.get("href") else None
    if not ad_id and url:
        mm = re.search(r"/(\d+)\.html$", url)
        if mm:
            ad_id = mm.group(1)
    stadt, stadtteil, _slug = _slug_from_url(url or "")
    # Straße / Adresse
    strasse = None
    address_label = soup.find(string=re.compile(r"^\s*Adresse\s*$"))
    if address_label:
        parent = address_label.find_parent("div")
        if parent:
            nxt = parent.find_next("span", class_=re.compile(r"section_panel_detail"))
            if nxt:
                strasse = _text(nxt)
    # Felder werden zeilenweise geparst. Strategie: suche nach Labels und
    # ermittle den Wert im gleichen key_fact-Block oder in der gleichen row.
    avail_from = None
    avail_to = None
    rent = None
    size = None
    def _find_value(label_regex: re.Pattern) -> Optional[str]:
        # 1) Strategie: <span class="key_fact_detail">LABEL</span> ... <b class="key_fact_value">WERT</b>
        m = re.search(
            r'class="key_fact_detail"[^>]*>\s*' + label_regex.pattern + r'\s*</span>'
            r'.*?class="key_fact_value"[^>]*>(.*?)</b>',
            html, re.DOTALL,
        )
        if m:
            return m.group(1)
        # 2) Strategie: <span class="section_panel_detail">LABEL:</span> ... <span class="section_panel_value">WERT</span>
        m = re.search(
            r'class="section_panel_detail"[^>]*>\s*' + label_regex.pattern + r':?\s*</span>'
            r'.*?class="section_panel_value"[^>]*>(.*?)</span>',
            html, re.DOTALL,
        )
        if m:
            return m.group(1)
        return None

    for label_pat, var_name in [
        (re.compile(r"frei\s+ab", re.I), "avail_from"),
        (re.compile(r"frei\s+bis", re.I), "avail_to"),
        (re.compile(r"Gesamtmiete", re.I), "rent"),
        (re.compile(r"Zimmergröße", re.I), "size"),
    ]:
        val = _find_value(label_pat)
        if not val:
            continue
        text = _norm_ws(val)
        if var_name in ("avail_from", "avail_to"):
            d = _parse_date(text)
            if var_name == "avail_from":
                avail_from = d
            else:
                avail_to = d
        elif var_name == "rent":
            rent = _eur_to_int(text)
        elif var_name == "size":
            size = _qm_to_int(text)
    # Beschreibung: längster description_text-Block
    beschreibung = None
    for node in soup.find_all("div", class_=re.compile(r"description_text|detail_description")):
        t = _norm_ws(node.get_text("\n"))
        if len(t) > 200:
            beschreibung = t
            break
    if not beschreibung:
        candidates = soup.find_all("div", class_=re.compile(r"section_panel_detail"))
        if candidates:
            beschreibung = _norm_ws(max((c.get_text("\n") for c in candidates), key=len))
    return {
        "id": ad_id,
        "url": url,
        "titel": title,
        "stadt": stadt,
        "stadtteil": stadtteil,
        "strasse": strasse,
        "kaltmiete_euro": rent,
        "groesse_qm": size,
        "verfuegbar_ab": avail_from,
        "verfuegbar_bis": avail_to,
        "typ": "wg",
        "beschreibung_text": beschreibung,
    }


def detail_url(offer_id: str) -> str:
    """Baut eine URL, die wg-gesucht.de auf die Anzeige umleitet."""
    return f"{BASE}/{offer_id}.html"


def normalize_offer_input(s: str) -> str:
    """Akzeptiert numerische ID, /...-Pfad oder volle URL → numerische ID."""
    s = (s or "").strip()
    if not s:
        raise ValueError("empty offer id")
    if s.isdigit():
        return s
    # URL oder Pfad
    path = s
    if "://" in s:
        from urllib.parse import urlparse
        path = urlparse(s).path
    # 1) Klassisch: /<slug>.<ID>.html
    m = re.search(r"\.(\d+)\.html$", path or "")
    if m:
        return m.group(1)
    # 2) query offer_id=
    m = re.search(r"offer_id=(\d+)", s)
    if m:
        return m.group(1)
    # 3) Fallback: jede Ziffernfolge
    m = re.search(r"(\d{4,})", s)
    if m:
        return m.group(1)
    raise ValueError(f"konnte keine Anzeigen-ID aus {s!r} ableiten")


def parse_login_form(html: str) -> dict:
    """Extrahiert versteckte Felder (z. B. csrf-Token) aus dem Login-Formular."""
    soup = BeautifulSoup(html, "lxml")
    form = soup.find("form", id=re.compile(r"login|signin", re.I))
    if form is None:
        form = soup.find("form", action=re.compile(r"login|signin|authent", re.I))
    fields: dict[str, str] = {}
    if form is not None:
        for inp in form.find_all("input"):
            name = inp.get("name")
            if not name:
                continue
            t = (inp.get("type") or "").lower()
            value = inp.get("value", "")
            if t == "submit":
                continue
            fields[name] = value
    return {
        "action": form.get("action") if form else None,
        "fields": fields,
    }


def looks_logged_in(html: str) -> bool:
    """Prüft auf den Beweis, dass wir eingeloggt sind.

    Akzeptanz: die Seite enthält entweder einen Link zu "Nachrichten"
    oder "Abmelden" / "Logout", oder den eigenen Nutzernamen in
    einem typischen User-Menü-Bereich.
    """
    if not html:
        return False
    soup = BeautifulSoup(html, "lxml")
    # 1) Link "Nachrichten" oder "/nachrichten.html"
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/nachrichten" in href or href.endswith("nachrichten.html"):
            return True
        if a.get_text(strip=True) and "nachricht" in a.get_text(strip=True).lower():
            return True
    # 2) "Abmelden" / "Logout"
    txt = soup.get_text(" ").lower()
    if "abmelden" in txt or "logout" in txt or "log out" in txt:
        return True
    # 3) Mein Konto / Mein WG-Gesucht
    if "mein konto" in txt or "mein-wg-gesucht" in txt:
        return True
    return False


def parse_messages_list(html: str) -> list[dict]:
    """Parst den Posteingang. Sehr robust, da Layout sich oft ändert."""
    soup = BeautifulSoup(html, "lxml")
    threads: list[dict] = []
    # Strategie 1: typische Tabellen-Struktur
    for row in soup.find_all("tr"):
        a = row.find("a", href=re.compile(r"/nachrichten/.*\d"))
        if not a:
            continue
        href = a.get("href", "")
        # Anzeigen-/Thread-IDs sind typisch am Pfad-Ende: /nachrichten/<ID>.html
        m = re.search(r"/(\d+)(?:\.html)?(?:/|$|\?|#)", href)
        if not m:
            # Fallback: erste Ziffernfolge im Pfad
            m = re.search(r"/nachrichten/(\d+)", href)
        thread_id = m.group(1) if m else None
        if not thread_id:
            continue
        cells = [_text(td) for td in row.find_all("td")]
        subject = a.get_text(strip=True) or (cells[1] if len(cells) > 1 else None)
        absender = cells[0] if cells else None
        datum_txt = cells[2] if len(cells) > 2 else None
        # Versuche Datum zu parsen
        datum = None
        if datum_txt:
            dm = re.search(r"(\d{2}\.\d{2}\.\d{4})(?:[ T](\d{2}:\d{2}))?", datum_txt)
            if dm:
                datum = _parse_date(dm.group(1))
                if dm.group(2):
                    datum = datum + "T" + dm.group(2) + ":00+02:00"
        vorschau = cells[3] if len(cells) > 3 else None
        gelesen = "unread" in (row.get("class") or [])
        threads.append({
            "thread_id": thread_id,
            "subject": subject,
            "absender": absender,
            "datum": datum,
            "gelesen": gelesen,
            "vorschau": vorschau,
        })
    if threads:
        return threads
    # Strategie 2: Cards / div-Container
    for card in soup.find_all("div", class_=re.compile(r"message_thread|nachrichten|message-list")):
        a = card.find("a", href=True)
        if not a:
            continue
        m = re.search(r"/nachrichten(?:/.*?)?/(\d+)", a["href"])
        if not m:
            continue
        threads.append({
            "thread_id": m.group(1),
            "subject": _text(card.find(["h3", "h4", "span", "strong"])) or None,
            "absender": _text(card.find(class_=re.compile(r"sender|absender|from"))),
            "datum": None,
            "gelesen": False,
            "vorschau": _text(card.find("p")),
        })
    return threads
