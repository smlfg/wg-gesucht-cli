# Anforderungen – wg-gesucht-cli

## Ziel

`wggesucht` ist eine Kommandozeilen-Schnittstelle für
https://www.wg-gesucht.de, gedacht für Agenten und Menschen, die
Wohnungs- und WG-Angebote suchen, Anzeigen lesen und – nach explizitem
Login – den eigenen Nachrichteneingang verwalten wollen, ohne den
Browser öffnen zu müssen.

Unterscheidung zu bestehenden Scrapern (z. B. `wg-gesucht-crawler-cli`,
`WG-Scraper`):

- **Agent-CLI mit stabilem JSON-Vertrag** (`--json`), keine CSV/Excel-Ausgabe.
- **Sicheres Login-Modell**: Zugangsdaten ausschließlich aus
  Umgebungsvariablen (`WG_EMAIL` / `WG_PASSWORD`), Session mit Modus
  `0600` in `$XDG_CONFIG_HOME/wg-gesucht-cli/session.json`,
  Cookie-Allowlist (nur `wg-gesucht.de`).
- **Login-Erfolg braucht einen Beweis** – ein Cookie allein reicht
  nicht, sondern ein Seitenaufruf, der nur eingeloggte Nutzer sehen.
- **Kein Auto-Spam**: `messages send` schickt nur, wenn `--confirm`
  mitgegeben wurde, und liefert ohne `--confirm` Exit-Code 5.
- **Reproduzierbare Tests**: Unit-Tests kommen ohne echtes Netz aus,
  Live-Tests (Suche) sind Smoke-Tests, die optional laufen.

## Use Cases

1. Suche (öffentlich): "Welche WG-Zimmer in Berlin unter 600 € gibt
   es gerade?"
2. Detail (öffentlich): "Zeig mir alles, was in Anzeige 13374505
   steht."
3. Login + Inbox: "Was hat der Vermieter auf meine letzte Anfrage
   geantwortet?"
4. Antwort: "Schreib dem Inserenten von 13374505 eine kurze Nachricht
   und frag nach Besichtigung." → verlangt explizites `--confirm`.

## Erreichbare Schnittstelle

`wg-gesucht.de` bietet **keine offizielle öffentliche API**. Die
CLI nutzt deshalb die reguläre Web-Schnittstelle:

- **Suche & Detail**: `GET` auf öffentliche URL-Listen
  (`/wg-zimmer-in-<Stadt>.<CityID>.0.1.0.html`) und
  Anzeigen-Detail-URLs (`/wg-zimmer-in-<Ort>.<AnzeigeID>.html`).
  Diese Seiten sind ohne Login erreichbar.
- **Login**: Formular-POST auf die Login-Route der Webseite
  (`/mein-wg-gesucht.html` o. ä.). Nach erfolgreichem Login
  (Cookie-Set + Beweis) wird die Session in einer JSON-Datei
  abgelegt. Für genaues Feld-Mapping siehe `INTERFACE.md`.
- **Posteingang / Senden**: HTML-Parsing der eingeloggten Routen
  (`/nachrichten.html`, `/nachrichten/send-message.html`,
  `/nachrichten/send/<id>.html` o. ä.). Diese Endpunkte sind
  nicht offiziell dokumentiert; das Tool nutzt das, was im DOM
  tatsächlich vorliegt (Stand 2026-10-13), und prüft jede Annahme
  gegen den Beweis (z. B. "Nachrichten-Header sichtbar" als
  Erfolgsbeleg).

## Auth & Sicherheit

- Zugangsdaten **nie** als CLI-Flag, **nie** loggen, **nie** in
  Ausgaben (auch nicht im JSON-Output).
- Session-Datei `$XDG_CONFIG_HOME/wg-gesucht-cli/session.json`,
  Modus `0600`, Verzeichnis `0700`. Nur wg-gesucht-Cookies
  (Allowlist über Domain-Suffix `.wg-gesucht.de`).
- **Login-Erfolg erst nach Beweis** (z. B. eine Seite, die den
  Nutzernamen oder den "Nachrichten"-Link enthält). Wenn der
  Beweis fehlt → Fehler, exit code 2, Session nicht gespeichert.
- Abgelaufene Session: HTTP 401/403 oder das Fehlen des
  Beweises beim ersten geschützten Aufruf → klare Meldung
  "Session abgelaufen, bitte `wggesucht login` erneut".
- **Senden ohne `--confirm`**: Exit 5, **nichts wird
  abgeschickt** – auch nicht teilweise.
- Keine persönlichen Daten erfinden. Im Quellcode / in
  `pyproject.toml` nur `name = "smlfg"` + die GitHub-Noreply-Mail
  als `author`/Maintainer-Kontakt.

## Fehlerklassen (Exit-Codes)

| Code | Bedeutung                                                            |
|------|----------------------------------------------------------------------|
| 0    | Erfolg                                                               |
| 1    | Usage / Validierung (fehlende Flags, unbekannter Subbefehl)          |
| 2    | Auth / Session (Login fehlgeschlagen, abgelaufen, keine Session)     |
| 3    | Netzwerk / HTTP-Fehler (Verbindung, Timeout, 5xx)                    |
| 4    | Parse-Fehler (unerwartetes HTML, erwartetes Element fehlt)           |
| 5    | Forbidden / Aktion verweigert (z. B. `send` ohne `--confirm`)        |

## Test-Strategie

- **Unit-Tests** (Pytest) verwenden HTML-Fixtures aus
  `tests/fixtures/` und patchen den HTTP-Adapter. Kein Netz.
- **Akzeptanztests** in `tests/acceptance/` starten das CLI als
  Subprozess und prüfen Exit-Codes, JSON-Shape und Idempotenz.
  Mit der `sitecustomize`-Sandbox aus
  `agent-learnings/tests/harness/sitecustomize.py` darf der
  Subprozess nur Loopback erreichen.
- **Live-Smoke** ist optional und liegt nicht in CI: `wggesucht
  search --city Berlin --limit 3 --json`.

## Out of scope

- Erinnerungs-/Benachrichtigungs-Mechanik (Cron, Watcher).
- Mehrere parallele Accounts in einem Aufruf.
- Mobile-API oder In-App-Browser-Umgehung.

## Referenzen

- `agent-learnings/rules/AGENTS.md` – allgemeine Regeln
- `agent-learnings/tests/harness/sitecustomize.py` – Netz-Sandbox
- `smlfg/ilias-cli`, `smlfg/bafoeg-cli` – Stil-Vorbilder
