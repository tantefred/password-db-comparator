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
| `-s`, `--search TEXT` | Nur Einträge zeigen, deren Gruppe/Titel/Username `TEXT` enthält, samt Status (nicht mit `--export-added` kombinierbar) |
| `--export-added [DATEI]` | Neu hinzugefügte Einträge als CSV schreiben (Standard: `neue_eintraege.csv`; Papierkorb-Gruppen werden ausgelassen) |

Geänderte Einträge werden danach gruppiert, in welcher Datei die jeweils
aktuellere Version liegt.

**Achtung:** Echte Exporte und `--export-added`-Dateien enthalten Passwörter im
Klartext. Alle `*.csv` außer `tests/*.csv` sind per `.gitignore` ausgeschlossen.
