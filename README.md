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
wggesucht search --city CITY [--max-rent N] [--min-size N]
                 [--rooms {wg,1zimmer,wohnung,haus}]
                 [--radius KM] [--limit N] [--json]
wggesucht show OFFER_ID_OR_URL [--json]
WG_EMAIL=… WG_PASSWORD=… wggesucht login [--json]
wggesucht logout [--json]
wggesucht messages list [--json]
wggesucht messages read THREAD_ID [--json]
wggesucht messages send --to OFFER_OR_USER --text "..." --confirm [--json]
wggesucht --version
wggesucht --help
```

## Beispiele

Suche in Berlin, max 600 €, 3 Treffer:

```bash
wggesucht search --city Berlin --max-rent 600 --limit 3 --json
```

1-Zimmer-Wohnungen in München ab 30 m²:

```bash
wggesucht search --city Muenchen --rooms 1zimmer --min-size 30 --limit 5 --json
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
  `beschreibung_text` in `snake_case`.
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

29 Tests (Stadt-Resolver, URL-Bau, Parser mit echten HTML-Fixtures
aus `tests/fixtures/`, Session-Storage mit Cookie-Allowlist,
Login-Beweis, Nachrichten-Endpoint-Stub, CLI-Smoke). Stand
2026-10-13.

Die Akzeptanztests in `tests/test_acceptance.py` starten das CLI
als Subprozess mit der `sitecustomize`-Sandbox aus
`agent-learnings/tests/harness/sitecustomize.py`, so dass der
CLI-Subprozess nur Loopback erreichen darf.

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
