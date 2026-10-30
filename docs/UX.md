# UX-Spezifikation – wggesucht

Diese Datei beschreibt die Bedienung von `wggesucht` so, wie sie heute
implementiert ist. Sie ist zugleich Eingabe für das UX-Gate
(`scratch/harness/ux_spec.py`).

Wichtige Abweichung zum interaktiven Gate-Format: Die schreibende
Aktion (`wggesucht messages send`) bestätigt **nicht** interaktiv mit
`[j/N]`, sondern über das explizite Flag `--confirm`. Ohne `--confirm`
endet der Befehl mit Exit 5, bevor irgendein Request rausgeht. Das ist
eine bewusste Agenten-Sicherheit und kein fehlender
Bestätigungsschritt. Das Gate erkennt das Flag über
`ux-meta.confirm_flag` als gleichwertige explizite Bestätigung an und
prüft im N-Lauf, dass der Befehl ohne Flag nichts schreibt (siehe
`scratch/harness/FORMAT.md`).

Ein weiterer Befund: Die CLI hatte **keinen Base-URL-Override**. Alle
URLs waren in `src/wggesucht_cli/{cities,auth,messages,parser}.py` fest
auf `https://www.wg-gesucht.de` verdrahtet. Seit dem Testbarkeits-Fix
lesen alle Requests `WGG_BASE_URL` (Default
`https://www.wg-gesucht.de`), sodass der Fake-Server angesprochen werden
kann.

## Meta

```ux-meta
{
  "tool": "wggesucht",
  "install": "pipx install git+https://github.com/smlfg/wg-gesucht-cli",
  "base_url_env": "WGG_BASE_URL",
  "required_options_ok": ["--to", "--text"],
  "credential_env": ["WG_EMAIL", "WG_PASSWORD"]
}
```

`--to` und `--text` sind Pflichtoptionen der schreibenden Aktion
(`messages send`), keine Suchbegriffe. Sie stehen deshalb auf der
Allowlist begründeter Pflicht-Optionen.

## Sitzung 1: Installation, Login und Posteingang

Die Zugangsdaten werden im Terminal abgefragt, weil `WG_EMAIL` und
`WG_PASSWORD` hier absichtlich nicht gesetzt sind. Die Passworteingabe
erfolgt verdeckt über `getpass`.

```ux-session
$ pipx install git+https://github.com/smlfg/wg-gesucht-cli
$ wggesucht login
< WG-Gesucht E-Mail:
> test@example.org
< WG-Gesucht Passwort:
> dummy-passwort
< "ok": true
! exit 0
$ wggesucht messages list
< Posteingang (3 Thread(s))
< Lisa M.
! exit 0
```

## Sitzung 2: Suche nach Stadtnamen

Die Stadt wird positional übergeben (seit dem UX-Umbau). Der Befehl
entspricht wörtlich dem README-Schnellstart.

```ux-session
$ wggesucht search heilbronn --max-rent 500
< 1 Angebot(e) in heilbronn
< 500 €
< ID 9000002
! exit 0
```

## Sitzung 3: Nachricht an einen Anbieter senden

Gewünschte Bedienung für Menschen: Im Terminal fragt der Befehl
`[j/N]`; `--confirm` bleibt nur für Agenten ohne TTY. Der Befehl setzt
eine gültige Session aus Sitzung 1 voraus (gleiches `XDG_CONFIG_HOME`).

```ux-session
$ wggesucht messages send --to 9000002 --text "Hallo, ist das Zimmer noch frei?"
< [j/N]
> j
< 9000002
! exit 0
```

## Fake-Server-Routen (lesend, plus Login-POST)

Die Such-Fixture wurde aus einer echten Heilbronn-Suche (GET) erzeugt
und von personenbezogenen Daten befreit (Namen, Straßen, Bild-URLs,
echte Anzeigen-IDs ersetzt). Login- und Posteingangs-Fixtures sind
bereits vorhanden und werden wiederverwendet. Der Login-POST ist kein
Lesen, wird aber als Route modelliert, weil das Format für
Nicht-Schreib-Aktionen keinen eigenen Block vorsieht.

```ux-routes
[
  {
    "method": "GET",
    "path": "/",
    "query_contains": "modal=sign_in",
    "response": "tests/fixtures/login_page.html",
    "status": 200,
    "content_type": "text/html; charset=utf-8"
  },
  {
    "method": "POST",
    "path": "/ajax/sessions.php",
    "query_contains": "action=login",
    "response": "tests/fixtures/ux/login_ok.json",
    "status": 200,
    "content_type": "application/json; charset=utf-8"
  },
  {
    "method": "GET",
    "path": "/nachrichten.html",
    "response": "tests/fixtures/nachrichten_logged_in.html",
    "status": 200,
    "content_type": "text/html; charset=utf-8"
  },
  {
    "method": "GET",
    "path": "/wg-zimmer-in-Heilbronn.60.0.1.0.html",
    "query_contains": "rMax=500",
    "response": "tests/fixtures/ux/search_heilbronn.html",
    "status": 200,
    "content_type": "text/html; charset=utf-8"
  }
]
```

## Formularschritte der schreibenden Aktion

Live ist nur der öffentliche Teil des Kontaktformulars lesbar: Die
Anzeige verlinkt auf `/nachricht-senden/<slug>.<id>.html`, zeigt ohne
Login aber nur den Login-Dialog. Die konkreten Formularfelder sind
deshalb **synthetisch aus dem CLI-Code** abgeleitet (`messages.py`):
`message_text` und `user_id`. Der GET auf das Formular ist ein
gefahrloser Lese-Schritt vor der eigentlichen Bestätigung; der POST
ist der einzige schreibende Request.

```ux-formsteps
[
  {
    "id": "kontaktformular",
    "method": "GET",
    "path": "/nachrichten/send-message.html",
    "sends": [],
    "response": "tests/fixtures/ux/contact_send_form.html",
    "before_confirm": true,
    "live": "synthetisch"
  },
  {
    "id": "nachricht_senden",
    "method": "POST",
    "path": "/nachrichten/send-message.html",
    "sends": ["message_text", "user_id"],
    "response": "tests/fixtures/ux/send_confirmed.html",
    "final": true,
    "live": "synthetisch"
  }
]
```
