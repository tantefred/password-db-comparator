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
