# CSV Comparator

Kleines Python-3-Skript, das zwei KeePassium-CSV-Exporte vergleicht und zeigt,
was sich unterscheidet. Einträge werden über Gruppe, Titel und Username zugeordnet.

```
python3 compare_csv.py tests/alt.csv tests/neu.csv
```

| Option | Wirkung |
|---|---|
| `--show-secrets` | Passwörter/TOTP im Klartext anzeigen (sonst maskiert) |
| `-i`, `--ignore SPALTE...` | Spalten beim Vergleich ignorieren, z. B. `--ignore Icon "Last Modified"` |
| `-s`, `--search TEXT` | Nur Einträge zeigen, deren Gruppe/Titel/Username `TEXT` enthält, samt Status (nicht mit `--export-added` / `--export-merged` kombinierbar) |
| `--hide-trash` | Papierkorb-Gruppen komplett ausblenden (Vergleich, Suche und Exporte) |
| `-g`, `--group TEXT` | Nur Einträge betrachten, deren Gruppenpfad `TEXT` enthält (Groß-/Kleinschreibung egal) |
| `--stats` | Nur die Anzahl der Einträge pro Gruppe in beiden Dateien samt Differenz anzeigen (mit `--group`/`--hide-trash` kombinierbar, nicht mit `--search` oder den Exporten) |
| `--check` | Jede Datei einzeln auf Dubletten und kaputte Einträge prüfen (ohne Passwörter anzuzeigen; mit `--group`/`--hide-trash` kombinierbar, nicht mit `--search`, `--stats` oder den Exporten) |
| `--password-check` | Passwortqualität je Datei prüfen (Passwörter werden nie angezeigt; nicht kombinierbar mit `--search`, `--stats`, `--check` oder den Exporten) |
| `--min-length N` | Mindestlänge für `--password-check` (Standard: 10) |
| `--max-age-days TAGE` | Maximales Alter seit der letzten Änderung für `--password-check` (Standard: 730) |
| `--format text\|json` | Ausgabeformat (Standard: `text`). Mit `json` steht nur JSON auf stdout; Hinweise zu Exporten gehen nach stderr |
| `--ui` | Weboberfläche starten statt im Terminal zu arbeiten (siehe unten; ohne Dateiangabe) |
| `--port N` | Port für `--ui` (Standard: 8765; bei belegtem Port wird der nächste freie genommen) |
| `--no-browser` | Mit `--ui` den Browser nicht automatisch öffnen |
| `--no-detect-moves` | Verschobene/umbenannte Einträge nicht erkennen (sie erscheinen dann als „entfernt“ plus „hinzugefügt“) |
| `--export-added [DATEI]` | Neu hinzugefügte Einträge als CSV schreiben (Standard: `neue_eintraege.csv`; Papierkorb-Gruppen werden ausgelassen; verschobene Einträge zählen nicht als neu) |
| `--export-merged [DATEI]` | Zusammengeführte CSV schreiben (Standard: `merged.csv`): alle Einträge beider Dateien, bei Unterschieden die jeweils neuere Version; Papierkorb-Gruppen werden ausgelassen (nicht mit `--search` kombinierbar) |

Geänderte Einträge werden danach gruppiert, in welcher Datei die jeweils
aktuellere Version liegt.

## Filter

`--hide-trash` und `--group` filtern beide Dateien, **bevor** verglichen wird, und gelten
damit auch für Suche und Exporte. Dadurch wirkt ein Eintrag, der in den Papierkorb
oder aus der gefilterten Gruppe heraus verschoben wurde, als „nur in einer Datei“
vorhanden. Beide Filter lassen sich kombinieren.

## Prüfung (`--check`)

Prüft beide Dateien jeweils für sich und listet:

- doppelte Einträge (gleiche Gruppe, Titel und Username),
- gleichen Titel und Username in verschiedenen Gruppen,
- gleiche URL und Username in verschiedenen Einträgen,
- Einträge ohne Passwort oder ohne Titel,
- offensichtlich ungültige URLs (Leerzeichen, kein Host, Host ohne Punkt;
  `localhost`, IP-Adressen und URLs ohne Schema sind erlaubt).

Passwörter werden dabei nie ausgegeben. Beispieldaten: `tests/probleme.csv`.

## Passwortqualität (`--password-check`)

Pro Datei werden gemeldet:

- wiederverwendete Passwörter (nur die betroffenen Einträge, nie das Passwort),
- Passwörter unter `--min-length` Zeichen (mit Längenangabe),
- Einträge, deren `Last Modified` länger als `--max-age-days` Tage zurückliegt,
- wie viele Einträge TOTP eingerichtet haben (fehlendes TOTP wird nicht bemängelt,
  da nicht jeder Dienst es anbietet).

Das „Alter“ wird relativ zum heutigen Datum berechnet, die Ausgabe für
`tests/passwoerter.csv` ändert sich daher mit der Zeit.

## JSON-Ausgabe (`--format json`)

Mit `--format json` wird statt des Textes ein JSON-Objekt ausgegeben, und zwar für
das, was du sonst angefragt hättest (Vergleich, `--search`, `--stats`, `--check`
oder `--password-check`). Alle Filter und Optionen (`--group`, `--hide-trash`,
`--ignore`, `--no-detect-moves`, …) gelten unverändert und stehen unter `filters`.
Exporte (`--export-added`, `--export-merged`) lassen sich mit dem Vergleich
kombinieren; ihre Hinweise gehen dann nach stderr, damit stdout gültiges JSON bleibt.

Jedes Objekt hat `mode`, `files` (Name, Pfad, Anzahl) und `filters`. Danach folgt je Modus:

| `mode` | Inhalt |
|---|---|
| `compare` | `moved`, `only_in_old`, `only_in_new`, `changed` (`newer_in_new`, `newer_in_old`, `unclear`) und `summary` |
| `search` | `query`, `match_count` und `results` mit `status` (`moved`, `only_in_old`, `only_in_new`, `newer_in_new`, `newer_in_old`, `unclear`, `identical`); Exit-Code 1 ohne Treffer |
| `stats` | `groups` (je `old`, `new`, `difference`) und `total` |
| `check` | `results` je Datei mit `findings` (`category`, `count`, `items`) |
| `password-check` | wie `check`, dazu `totp` je Datei und `thresholds` |

Einträge werden als `{"group", "title", "username"}` ausgegeben. Passwörter und TOTP
bleiben maskiert (`"masked": true`), außer mit `--show-secrets`.

## Merge-Export

`--export-merged` schreibt eine CSV, die alle Einträge beider Dateien enthält.
Gibt es einen Eintrag in beiden Dateien, wird die Version mit dem neueren
`Last Modified` übernommen (auch bei verschobenen/umbenannten Einträgen). Ist die
Aktualität nicht bestimmbar (gleicher oder fehlender Zeitstempel) und der Inhalt
verschieden, wird die Version aus der zweiten Datei genommen und der Eintrag als
Konflikt aufgelistet. Die Datei lässt sich in KeePassium importieren; sie enthält
Passwörter im Klartext.

## Verschobene und umbenannte Einträge

Da Einträge über Gruppe, Titel und Username zugeordnet werden, würde ein
verschobener oder umbenannter Eintrag sonst als „entfernt“ plus „hinzugefügt“
erscheinen. Das Skript paart solche Einträge und zeigt sie in einem eigenen
Abschnitt „Verschoben/umbenannt“:

- **sicher:** `Created` ist identisch und nicht leer, und Passwort, URL oder
  Titel stimmen überein.
- **wahrscheinlich:** Username, Passwort und URL sind alle identisch und nicht leer.

Gepaart wird nur bei eindeutigen 1:1-Treffern; mehrdeutige Fälle bleiben bei
„entfernt“/„hinzugefügt“. Wird ein Eintrag gleichzeitig umbenannt und bekommt
ein neues Passwort, wird er nicht erkannt. Per `--ignore` ignorierte Spalten
zählen beim Paaren nicht mit (ohne `Created` entfällt die Stufe „sicher“).

**Achtung:** Echte Exporte und `--export-added`-Dateien enthalten Passwörter im
Klartext. Alle `*.csv` außer `tests/*.csv` sind per `.gitignore` ausgeschlossen.

## Weboberfläche (`--ui`)

```
python3 compare_csv.py --ui
```

Das öffnet im Browser eine schlichte Oberfläche, die alles kann, was das Terminal kann:
Vergleich, Suche, Statistik, Dubletten-Prüfung und Passwortqualität, dazu alle Filter,
das Ignorieren von Spalten und beide Exporte als Download. Die Ergebnisse erscheinen
übersichtlich statt als Text: jede Datei hat ihre feste Farbe, ein Balken zeigt die
Verteilung (identisch, geändert, verschoben, nur in einer Datei), und bei jedem Unterschied
steht der Wert aus Datei 1 neben dem aus Datei 2. Unter dem Ergebnis steht, wie du dasselbe
im Terminal aufrufst, und der JSON-Bericht lässt sich speichern.

Beide Wege nutzen dieselbe Logik und dieselbe Optionsprüfung. Ein Test stellt sicher, dass
die Oberfläche für gleiche Einstellungen exakt den Bericht der Kommandozeile liefert.

**Datenschutz und Sicherheit**

- Der Server lauscht nur auf `127.0.0.1` und ist von anderen Rechnern nicht erreichbar.
- Die Dateien werden nur im Arbeitsspeicher ausgewertet; es wird nichts gespeichert,
  protokolliert oder nachgeladen. Die Seite funktioniert ohne Internetzugang.
- Anfragen brauchen ein zufälliges Token, das nur die ausgelieferte Seite kennt, und der
  `Host`-Header wird geprüft. Das schützt davor, dass eine andere Webseite im Browser den
  lokalen Server anspricht.
- Inhalte aus den CSV-Dateien werden nie als HTML eingesetzt.
- Passwörter und TOTP bleiben verborgen, außer du aktivierst „Passwörter im Klartext zeigen“.
  Die exportierten CSV-Dateien enthalten Passwörter im Klartext.
- Eine Anfrage darf höchstens 64 MiB groß sein.

Mit Strg+C im Terminal beendest du die Oberfläche.

## Projektaufbau

`compare_csv.py` ist nur der Einstiegspunkt; die Logik liegt im Paket `csvcompare/`:

| Modul | Aufgabe |
|---|---|
| `cli.py` | Optionen, Validierung, Ablauf |
| `csvio.py` | CSV lesen und schreiben |
| `compare.py` | Vergleich (`compare_files`), Verschoben-Erkennung, Aktualität, Merge, Suche |
| `analysis.py` | Statistik, Prüfung (`--check`), Passwortqualität |
| `exports.py` | `--export-added` und `--export-merged` |
| `report.py` | wählt den JSON-Bericht zum gewählten Modus (Terminal und Oberfläche) |
| `service.py` | Auswertung aus CSV-Text und Optionen, ohne Dateipfade (für die Oberfläche) |
| `webui.py`, `web/index.html` | lokaler Server und die Oberfläche selbst |
| `render_text.py` / `render_json.py` | Textausgabe bzw. JSON-Berichte |
| `common.py`, `constants.py` | Hilfsfunktionen, Spaltendefinitionen und Konfiguration |

## Tests

```
python3 -m unittest discover -s tests -v
```

Die Tests starten das Skript wie ein Nutzer über die Kommandozeile und verwenden
die Beispieldaten in `tests/` (nur Standardbibliothek, kein Netzwerk).
