# INTERFACE – wg-gesucht-cli

Vertrag, den die Akzeptanztests prüfen. Alle Befehle kennen
`--json`. Bei `--json` schreibt das Tool **genau ein**
JSON-Objekt auf stdout, alles andere (Status, Hinweise, Fehler)
geht auf stderr.

## Globales

- CLI-Name: `wggesucht`
- Paketname: `wg-gesucht-cli`
- Python: ≥ 3.10
- Abhängigkeiten: `requests`, `beautifulsoup4` (und indirekt `lxml`)
- Konfiguration: `WG_EMAIL`, `WG_PASSWORD` (nur für `login`).
  `XDG_CONFIG_HOME` zur Sitzungslokation (Default
  `$HOME/.config/wg-gesucht-cli/session.json`).
- User-Agent: `wg-gesucht-cli/<Version> (+https://github.com/smlfg/wg-gesucht-cli)`

## Exit-Codes

| Code | Bedeutung                                                            |
|------|----------------------------------------------------------------------|
| 0    | OK                                                                   |
| 1    | Usage / Validierung                                                  |
| 2    | Auth / Session                                                       |
| 3    | Netzwerk / HTTP-Fehler                                               |
| 4    | Parse-Fehler (unerwartetes HTML)                                     |
| 5    | Aktion verweigert (z. B. `send` ohne `--confirm`)                    |

## Befehle

### `wggesucht search`

```
wggesucht search --city CITY [--max-rent N] [--min-size N]
                 [--rooms {wg,1zimmer,wohnung,haus}]
                 [--radius KM] [--limit N] [--json]
```

- `--city` (Pflicht): Stadt, z. B. `Berlin`, `Muenchen`,
  `Frankfurt`. Umsetzung intern: city_id-Lookup über die
  Startseite oder eine kleine eingebaute Mapping-Tabelle
  (siehe `cities.py`).
- `--max-rent` (optional): maximale Gesamtmiete in € (entspricht
  WG-Gesucht-Filter `rMax` / Kartenpreis).
- `--min-size` (optional): Mindest-Zimmergröße in m².
- `--rooms` (optional): `wg` (WG-Zimmer), `1zimmer` (1-Zimmer-Wohnung),
  `wohnung` (2/3/4-Zimmer), `haus` (Haus). Wirkt über
  URL-Pfadkomponente.
- `--radius` (optional): Kilometer; nur für Städte mit Umkreis-
  Unterstützung sinnvoll (Hinweis im JSON, falls ignoriert).
- `--limit` (optional, Default 20, Cap 100).
- `--json`: ein JSON-Objekt:

```json
{
  "quelle": "https://www.wg-gesucht.de",
  "stadt": "Berlin",
  "filter": {"max_rent": 600, "min_size": null, "rooms": "wg", "radius": null, "limit": 3},
  "hinweis": null,
  "anzahl": 3,
  "angebote": [
    {
      "id": "13374505",
      "url": "https://www.wg-gesucht.de/wg-zimmer-in-Berlin-Friedrichshagen.13374505.html",
      "titel": "S-Bahn & Müggelsee | near HTW/HU Adlershof/IGB",
      "stadt": "Berlin",
      "stadtteil": "Friedrichshagen",
      "strasse": "Ahornallee",
      "gesamtmiete_euro": 680,
      "groesse_qm": 18,
      "verfuegbar_ab": "2026-10-15",
      "verfuegbar_bis": "2027-04-15",
      "typ": "wg"
    }
  ]
}
```

`hinweis` ist ein String, falls etwas nicht angewendet werden
konnte (z. B. `--radius` ohne Stadtteil-ID). `angebote` ist
immer ein Array; bei Netz-/Parse-Fehler ist es `[]` und
`exit_code` ≠ 0.

### `wggesucht show`

```
wggesucht show OFFER_ID_OR_URL [--json]
```

- `OFFER_ID_OR_URL`: numerische ID (`13374505`) oder volle URL
  (`https://www.wg-gesucht.de/.../1234567.html`).
- Ohne Login: nur die öffentlichen Felder.
- JSON-Shape:

```json
{
  "quelle": "https://www.wg-gesucht.de",
  "angebot": {
    "id": "13374505",
    "url": "https://www.wg-gesucht.de/wg-zimmer-in-Berlin-Friedrichshagen.13374505.html",
    "titel": "S-Bahn & Müggelsee | near HTW/HU Adlershof/IGB",
    "stadt": "Berlin",
    "stadtteil": "Friedrichshagen",
    "strasse": "Ahornallee",
    "kaltmiete_euro": 480,
    "groesse_qm": 18,
    "verfuegbar_ab": "2026-10-15",
    "verfuegbar_bis": "2027-04-15",
    "typ": "wg",
    "beschreibung_text": "..."
  }
}
```

### `wggesucht login`

```
WG_EMAIL=… WG_PASSWORD=… wggesucht login [--headed] [--json]
```

- Liest `WG_EMAIL` und `WG_PASSWORD` aus der Umgebung
  (`getpass`-Prompt im TTY, falls env leer – niemals
  echo).
- POSTet gegen den Login-Endpunkt, prüft mit einem
  Folge-GET (Beweis), dass eine nur-für-Eingeloggte
  sichtbare Seite erscheint.
- Speichert Session unter
  `$XDG_CONFIG_HOME/wg-gesucht-cli/session.json` (Modus
  `0600`).
- Cookie-Allowlist: nur `.wg-gesucht.de`.
- JSON:

```json
{
  "ok": true,
  "user": "max@example.org",
  "session_file": "/home/box/.config/wg-gesucht-cli/session.json",
  "cookie_anzahl": 3
}
```

### `wggesucht messages list`

```
wggesucht messages list [--json]
```

- Verlangt gültige Session (sonst Exit 2).
- JSON:

```json
{
  "quelle": "https://www.wg-gesucht.de/nachrichten.html",
  "anzahl": 7,
  "threads": [
    {
      "thread_id": "9123456",
      "subject": "WG-Zimmer in Berlin-Friedrichshagen",
      "absender": "Lisa M.",
      "datum": "2026-10-12T10:34:00+02:00",
      "gelesen": false,
      "vorschau": "Hi, wann könntest du …"
    }
  ]
}
```

### `wggesucht messages read`

```
wggesucht messages read THREAD_ID [--json]
```

- Lädt den Thread, gibt den Verlauf + Header zurück.
- JSON:

```json
{
  "quelle": "https://www.wg-gesucht.de/nachrichten/...",
  "thread": {
    "thread_id": "9123456",
    "subject": "WG-Zimmer in Berlin-Friedrichshagen",
    "teilnehmer": ["max@example.org", "Lisa M."],
    "nachrichten": [
      {"von": "max@example.org", "datum": "...", "text": "..."},
      {"von": "Lisa M.", "datum": "...", "text": "..."}
    ]
  }
}
```

### `wggesucht messages send`

```
wggesucht messages send --to OFFER_OR_USER --text "..." --confirm
```

- **Ohne** `--confirm` → Exit 5, **nichts wird abgeschickt**.
  Es gibt auch keine Vorschau-Anzeige, die das Senden
  initiiert.
- `--to`: Anzeigen-ID/URL oder Nutzername.
- JSON:

```json
{
  "ok": true,
  "an": "Lisa M. (Anzeige 13374505)",
  "thread_id": "9123456",
  "gesendet_am": "2026-10-13T15:21:00+02:00"
}
```

### `wggesucht logout`

```
wggesucht logout
```

- Löscht die Session-Datei. **Idempotent**: wenn keine
  Datei da ist, Exit 0, JSON `{ "ok": true }`.

### `wggesucht --version` / `wggesucht --help`

Standard argparse-Verhalten.

## Konfiguration

- `WG_EMAIL`, `WG_PASSWORD`: nur für `login`.
- `XDG_CONFIG_HOME`: Sitzungsdatei unter
  `<XDG_CONFIG_HOME>/wg-gesucht-cli/session.json`.

## Beweis-Anforderungen (intern)

- `login` ist erst erfolgreich, wenn der GET auf
  `/nachrichten.html` eine Seite liefert, die das Wort
  "Nachrichten" **und** entweder einen Logout-Link oder
  den eigenen Nutzernamen enthält.
- `messages list` / `messages read` ohne gültige Session:
  Exit 2 mit JSON `{ "error": "no_session", "hint":
  "wggesucht login" }`.
- `messages send` ohne `--confirm`: Exit 5, JSON
  `{ "error": "confirm_required", "hint": "..." }`.
