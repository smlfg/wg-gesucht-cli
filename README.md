# wg-gesucht-cli

`wggesucht` ist eine Kommandozeilen-Schnittstelle für
https://www.wg-gesucht.de, gedacht für KI-Agenten und Menschen:

- **Suche** (öffentlich, kein Login): WG-Zimmer, Wohnungen, Häuser
  nach Stadt, Größe, Miete filtern.
- **Anzeigen-Details** (öffentlich): voller Anzeigentext.
- **Login** + **Posteingang lesen** mit persistenter Session.
- **Nachricht senden** – aber **nur** mit explizitem `--confirm`,
  damit kein Agent versehentlich Spam produziert.

Unterscheidung zu bestehenden Scrapern (z. B.
`wg-gesucht-crawler-cli`, `WG-Scraper`):

- Stabile JSON-Schnittstelle (`--json`) für Agenten.
- Sicheres Login: Zugangsdaten nur aus `WG_EMAIL`/`WG_PASSWORD`,
  Session unter `$XDG_CONFIG_HOME/wg-gesucht-cli/session.json`
  (Modus 0600), Cookie-Allowlist (nur `wg-gesucht.de`).
- **Login-Erfolg braucht einen Beweis** – ein Cookie allein
  reicht nicht, der Tool ruft eine nur-für-Eingeloggte sichtbare
  Seite ab.
- **Kein Auto-Spam**: `messages send` ohne `--confirm` → Exit 5,
  es wird **nichts** abgeschickt.
- **Tests ohne Netz**: Pytest-Suite mit HTML-Fixtures, gegen
  wg-gesucht.de wird nur optional live gesmoket.

## Installation

```bash
pip install wg-gesucht-cli
# oder aus dem Repo:
pip install -e .
```

Danach steht `wggesucht` zur Verfügung.

## Auth-Setup

`wggesucht login` liest die Zugangsdaten aus den Umgebungsvariablen
`WG_EMAIL` und `WG_PASSWORD`. Im TTY fällt es auf verdeckte
Eingabe zurück, falls die Variablen leer sind. **Niemals** als
CLI-Flag übergeben.

```bash
export WG_EMAIL='max@example.org'
export WG_PASSWORD='…'
wggesucht login --json
```

Session löschen:

```bash
wggesucht logout
```

## Befehle

```text
wggesucht search --city CITY [--rooms {wg,1zimmer,wohnung,haus}]
                 [--min-rent N] [--max-rent N]
                 [--min-size N] [--max-size N] [--radius METER]
                 [--move-in-from YYYY-MM-DD] [--move-in-to YYYY-MM-DD]
                 [--rent-type 1,2,3]            # 1=befristet 2=unbefristet 3=Übernachtung
                 [--wg-gender {1,2,4,5}]        # 1=Frau 2=Mann 4=Divers 5=k.A.
                 [--wg-searched-gender {1,2,3,4}]
                 [--flatmate-age-min N] [--flatmate-age-max N]
                 [--min-flatmates N] [--max-flatmates N]
                 [--flatshare-type 1,2,6,12,16,19]   # IDs aus dem wg-gesucht-Formular
                 [--furnished {1,2}]            # 1=ja 2=nein
                 [--smoking {1,2,3,4}]          # 1=erlaubt 2=nicht 3=eigenes Zimmer 4=Balkon
                 [--pets-allowed {1,2}] [--pets-present {1,2}]
                 [--kitchen {1,2}]
                 [--district "Altstadt"] [--district-id 85215,1955]
                 [--since 1..7]                 # 1=3T 2=1W 3=2W … 7=3M
                 [--exchange {1,2}]
                 [--floor N]
                 [--handicapped] [--balcony] [--garden] [--online-tour]
                 [--images-only] [--limit N] [--json]
wggesucht show OFFER_ID_OR_URL [--json]
WG_EMAIL=… WG_PASSWORD=… wggesucht login [--json]
wggesucht logout [--json]
wggesucht messages list [--json]
wggesucht messages read THREAD_ID [--json]
wggesucht messages send --to OFFER_OR_USER --text "..." --confirm [--json]
wggesucht --version
wggesucht --help
```

Die `--flatshare-type`-IDs entsprechen der Live-Drop-down-Liste:
`0=Zweck-WG`, `1=Studenten-WG`, `2=Frauen-WG`, `6=Berufstätigen-WG`,
`11=keine Zweck-WG`, `12=gemischte WG`, `16=LGBTQIA+`,
`19=Internationals welcome`. Mehrere IDs per Komma.

## Beispiele

Suche in Berlin, max 600 €, 3 Treffer:

```bash
wggesucht search --city Berlin --max-rent 600 --limit 3 --json
```

1-Zimmer-Wohnungen in München ab 30 m²:

```bash
wggesucht search --city Muenchen --rooms 1zimmer --min-size 30 --limit 5 --json
```

Heilbronn, möbliert, Einzug November 2026 – Januar 2027, mind. 3 Mitbewohner:

```bash
wggesucht search --city Heilbronn --furnished 1 \
  --move-in-from 2026-11-01 --move-in-to 2027-01-31 \
  --min-flatmates 3 --json
```

Studenten-WG in Frankfurt, Rauchen nicht erwünscht, 22–30 Jahre:

```bash
wggesucht search --city Frankfurt --flatshare-type 1 \
  --smoking 2 --flatmate-age-min 22 --flatmate-age-max 30 --json
```

WG in Köln-Altstadt (Stadtteil-ID via Form, Substring-Filter ohne ID):

```bash
wggesucht search --city Koeln --district "Altstadt" --json
```

Befristet, Tauschwohnung ausgeschlossen, nur Anzeigen mit Bildern:

```bash
wggesucht search --city Berlin --rent-type 1 --exchange 2 --images-only --json
```

Anzeige 4668942 ansehen:

```bash
wggesucht show 4668942 --json
```

Posteingang listen:

```bash
wggesucht messages list --json
```

Thread lesen:

```bash
wggesucht messages read 9123456 --json
```

Antwort senden (verlangt `--confirm`):

```bash
wggesucht messages send --to 4668942 \
  --text "Hi, ist das Zimmer noch frei? Wann könnte ich vorbeikommen?" \
  --confirm --json
```

Ohne `--confirm` → Exit 5, **nichts** wird abgeschickt:

```bash
wggesucht messages send --to 4668942 --text "…"
# echo "Exit: $?"   → 5
```

## JSON-Konvention

- `--json` schreibt **genau ein** JSON-Objekt auf stdout.
  Prompts/Status gehen auf stderr.
- `id`/`url`/`stadt`/`stadtteil`/`strasse`/`kaltmiete_euro`/
  `groesse_qm`/`verfuegbar_ab`/`verfuegbar_bis`/`typ`/
  `beschreibung_text` in `snake_case`. Bei Listen-Treffern
  zusätzlich pro Angebot: `mitbewohner_anzahl`,
  `mitbewohner_maennlich`/`_weiblich`/`_divers`,
  `mitbewohner_alter_text`, `moebliert`, `rauchen`.
- Beträge in Euro als Integer; Größe in m² als Integer.
- Datumsangaben ISO-8601 (`YYYY-MM-DD`).
- Fehler: `{"error": "...", "kind": "...", ...}` auf stderr,
  Exit-Code ungleich 0.

## Exit-Codes

| Code | Bedeutung                                                            |
|------|----------------------------------------------------------------------|
| 0    | OK                                                                   |
| 1    | Usage / Validierung                                                  |
| 2    | Auth / Session                                                       |
| 3    | Netzwerk / HTTP-Fehler                                               |
| 4    | Parse-Fehler                                                         |
| 5    | Aktion verweigert (z. B. `send` ohne `--confirm`)                    |

## Sicherheits-Modell

- Passwörter werden **nie** persistiert, **nie** geloggt, **nie**
  in JSON-Ausgaben geschrieben.
- Session-Cookies: Modus `0600`, Cookie-Allowlist
  `.wg-gesucht.de` (kein Identity-Provider).
- `messages send` ohne `--confirm`: Exit 5, keine Vorschau-Aktion
  wird ausgelöst.
- Persistente Daten (außer der Session) bleiben auf dem Gerät.

## Tests

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest tests/ -ra
```

57 Tests (Stadt-Resolver, URL-Bau mit 19 echten wg-gesucht-Formular-
Parametern, Parser mit echten HTML-Fixtures + synthetischer Suche,
Session-Storage mit Cookie-Allowlist, Login-Beweis,
Nachrichten-Endpoint-Stub, CLI-Smoke, alle Filter-Clients). Stand
2026-10-13.

Die Akzeptanztests in `tests/test_acceptance.py` starten das CLI
als Subprozess mit der `sitecustomize`-Sandbox in
`tests/harness/sitecustomize.py`, so dass der CLI-Subprozess nur
Loopback erreichen darf.

## Bekannte Einschränkungen

- `messages send` / `messages read` wurde **nicht** live
  verifiziert (kein Test-Account gegen wg-gesucht.de vorhanden).
  Die Endpunkt-URLs sind aus dem öffentlichen HTML abgeleitet;
  falls wg-gesucht die Pfade ändert, schlägt der Aufruf mit
  Exit 3 (HTTP) oder 4 (Parse) fehl.
- Stadtteil-IDs für `--radius` sind **nicht** implementiert
  (würden einen zusätzlichen Stadtteil-Resolver brauchen).
- 2FA / SMS-Codes werden nicht unterstützt – das ist Absicht
  und analog zu den Regeln in `agent-learnings/rules/AGENTS.md`.

## Lizenz

MIT – siehe [LICENSE](LICENSE).
