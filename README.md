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
