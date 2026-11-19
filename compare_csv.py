#!/usr/bin/env python3
"""Vergleicht zwei KeePassium-CSV-Exporte und zeigt die Unterschiede.

Aufruf: python3 compare_csv.py alt.csv neu.csv [--show-secrets] [--export-added [DATEI]]
"""
import argparse
import csv
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

KEY_COLS = ("Group", "Title", "Username")
SECRET_COLS = ("Password", "TOTP")
TIME_COL = "Last Modified"
EXPECTED = ["Group", "Title", "Username", "Password", "URL", "Notes",
            "TOTP", "Icon", "Last Modified", "Created"]
# Einträge in Gruppen, deren Pfad eines dieser Muster enthält, werden nicht exportiert
EXCLUDE_GROUP_PATTERNS = ("papierkorb",)

TS_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d.%m.%Y %H:%M:%S",
              "%d.%m.%Y %H:%M", "%d.%m.%Y", "%Y-%m-%d", "%m/%d/%Y %H:%M:%S")


def load(path):
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            missing = [c for c in EXPECTED if c not in (reader.fieldnames or [])]
            if missing:
                sys.exit(f"Fehler: In '{path}' fehlen Spalten: {', '.join(missing)}")
            rows = list(reader)
    except OSError as e:
        sys.exit(f"Fehler: '{path}' kann nicht gelesen werden: {e}")

    # Doppelte Schlüssel durchnummerieren, damit nichts verloren geht
    seen = defaultdict(int)
    entries = {}
    for row in rows:
        base = tuple(row[c] for c in KEY_COLS)
        seen[base] += 1
        entries[base + (seen[base],)] = row
    return entries


def parse_ts(s):
    """Zeitstempel -> aware datetime (UTC) oder None, wenn nicht lesbar."""
    s = (s or "").strip()
    if not s:
        return None
    dt = None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        for fmt in TS_FORMATS:
            try:
                dt = datetime.strptime(s, fmt)
                break
            except ValueError:
                pass
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def human_delta(seconds):
    seconds = int(abs(seconds))
    for unit, size in (("Tag(e)", 86400), ("Stunde(n)", 3600), ("Minute(n)", 60)):
        if seconds >= size:
            return f"{seconds // size} {unit}"
    return f"{seconds} Sekunde(n)"


def label(key):
    group, title, user, n = key
    s = f"{group or '(ohne Gruppe)'} / {title or '(ohne Titel)'}"
    if user:
        s += f"  [{user}]"
    if n > 1:
        s += f"  #{n}"
    return s


def short(value, secret, show_secrets):
    if secret and not show_secrets:
        return "(gesetzt)" if value else "(leer)"
    value = value.replace("\r", "").replace("\n", " ⏎ ")
    if len(value) > 80:
        value = value[:77] + "..."
    return repr(value) if value == "" else value


def is_excluded(row):
    g = row["Group"].lower()
    return any(p in g for p in EXCLUDE_GROUP_PATTERNS)


def display_names(path1, path2):
    """Dateinamen für die Ausgabe; bei gleichem Namen der volle Pfad."""
    n1, n2 = os.path.basename(path1), os.path.basename(path2)
    return (path1, path2) if n1 == n2 else (n1, n2)


def find_moves(old, new, removed, added, ignored):
    """Findet verschobene/umbenannte Einträge unter den nur einseitig vorhandenen Keys.

    Rückgabe: Liste (alter_key, neuer_key, sicherheit) mit sicherheit 'sicher' oder
    'wahrscheinlich'. Gepaart wird nur bei eindeutigen 1:1-Treffern.
    """
    def same(r, a, col):
        return col not in ignored and old[r][col] != "" and old[r][col] == new[a][col]

    def strong(r, a):
        return same(r, a, "Created") and any(
            same(r, a, c) for c in ("Password", "URL", "Title"))

    def likely(r, a):
        return all(same(r, a, c) for c in ("Username", "Password", "URL"))

    moves = []
    left_old, left_new = list(removed), list(added)
    for matcher, confidence in ((strong, "sicher"), (likely, "wahrscheinlich")):
        cands = {r: [a for a in left_new if matcher(r, a)] for r in left_old}
        reverse = defaultdict(list)
        for r, lst in cands.items():
            for a in lst:
                reverse[a].append(r)
        paired = [(r, lst[0]) for r, lst in cands.items()
                  if len(lst) == 1 and len(reverse[lst[0]]) == 1]
        for r, a in paired:
            moves.append((r, a, confidence))
        left_old = [r for r in left_old if r not in {m[0] for m in paired}]
        left_new = [a for a in left_new if a not in {m[1] for m in paired}]
    return sorted(moves)


def classify(key, old, new, n1, n2, new_key=None):
    """Gibt (gruppe, delta_text) zurück. gruppe: 'old_outdated' | 'new_outdated' | 'unclear'."""
    t_old = parse_ts(old[key][TIME_COL])
    t_new = parse_ts(new[new_key or key][TIME_COL])
    if t_old is None or t_new is None:
        return "unclear", "Zeitstempel nicht auswertbar"
    diff = (t_new - t_old).total_seconds()
    if diff > 0:
        return "old_outdated", f"{n2} ist {human_delta(diff)} neuer"
    if diff < 0:
        return "new_outdated", f"{n1} ist {human_delta(diff)} neuer"
    return "unclear", "gleicher Zeitstempel, Inhalt unterschiedlich"


def print_changed(k, diffs, delta, old, new, show_secrets, indent="  ",
                  new_k=None, header=None):
    """Gibt einen geänderten Eintrag mit Unterschieden aus.

    new_k: Key des Eintrags in der zweiten Datei, falls er sich von k unterscheidet.
    """
    nk = new_k or k
    names = [c for c in diffs if c != TIME_COL]
    print(f"{indent}{header or '~ ' + label(k)}")
    if not diffs:
        print(f"{indent}    sonst keine Änderungen")
    else:
        kind = "nur Zeitstempel" if not names else "Unterschiede in: " + ", ".join(names)
        print(f"{indent}    {kind}  ({delta})")
        print(f"{indent}    Last Modified: {old[k][TIME_COL]}  |  {new[nk][TIME_COL]}")
    for c in names:
        secret = c in SECRET_COLS
        a = short(old[k][c], secret, show_secrets)
        b = short(new[nk][c], secret, show_secrets)
        if secret and not show_secrets:
            print(f"{indent}    {c}: geändert ({a} → {b})")
        else:
            print(f"{indent}    {c}: {a}  →  {b}")


def print_move(move, compare_cols, old, new, n1, n2, show_secrets, indent="  "):
    """Gibt ein erkanntes Paar aus verschobenem/umbenanntem Eintrag aus."""
    ok, nk, confidence = move
    key_changes = [c for c, a, b in zip(KEY_COLS, ok, nk) if a != b]
    diffs = [c for c in compare_cols if old[ok][c] != new[nk][c]]
    _, delta = classify(ok, old, new, n1, n2, new_key=nk)
    header = (f"↷ {label(ok)}  →  {label(nk)}\n"
              f"{indent}    geändert in: {', '.join(key_changes)}  [{confidence}]")
    print_changed(ok, diffs, delta, old, new, show_secrets, indent=indent,
                  new_k=nk, header=header)


def main():
    p = argparse.ArgumentParser(description="KeePassium-CSV-Exporte vergleichen")
    p.add_argument("alt", help="Erste CSV-Datei")
    p.add_argument("neu", help="Zweite CSV-Datei")
    p.add_argument("--show-secrets", action="store_true",
                   help="Passwörter/TOTP im Klartext anzeigen")
    p.add_argument("-i", "--ignore", nargs="+", default=[], metavar="SPALTE",
                   help="Spalten, die beim Vergleich ignoriert werden "
                        "(z. B. --ignore Icon \"Last Modified\" oder --ignore Icon,Notes). "
                        f"Mögliche Werte: {', '.join(c for c in EXPECTED if c not in KEY_COLS)}")
    p.add_argument("-s", "--search", metavar="TEXT",
                   help="Nur Einträge anzeigen, deren Gruppe, Titel oder Username TEXT enthält "
                        "(Groß-/Kleinschreibung egal), samt Status. "
                        "Nicht kombinierbar mit --export-added.")
    p.add_argument("--no-detect-moves", action="store_true",
                   help="Verschobene/umbenannte Einträge nicht erkennen "
                        "(sie erscheinen dann als 'entfernt' plus 'hinzugefügt')")
    p.add_argument("--export-added", nargs="?", const="neue_eintraege.csv",
                   metavar="DATEI",
                   help="Neu hinzugefügte Einträge als CSV schreiben "
                        "(Standard: neue_eintraege.csv). Enthält Passwörter im Klartext! "
                        "Einträge aus Papierkorb-Gruppen werden ausgelassen.")
    args = p.parse_args()

    if args.search is not None and args.export_added:
        p.error("--search und --export-added können nicht kombiniert werden.")
    if args.search is not None and not args.search.strip():
        p.error("--search benötigt einen nicht-leeren Suchbegriff.")

    by_lower = {c.lower(): c for c in EXPECTED}
    ignored = []
    for part in (s.strip() for item in args.ignore for s in item.split(",")):
        if not part:
            continue
        col = by_lower.get(part.lower())
        if col is None:
            p.error(f"Unbekannte Spalte '{part}'. Gültig: "
                    f"{', '.join(c for c in EXPECTED if c not in KEY_COLS)}")
        if col in KEY_COLS:
            p.error(f"Die Spalte '{col}' identifiziert die Einträge und kann nicht ignoriert werden.")
        if col not in ignored:
            ignored.append(col)

    old, new = load(args.alt), load(args.neu)
    n1, n2 = display_names(args.alt, args.neu)
    removed = sorted(set(old) - set(new))
    added = sorted(set(new) - set(old))

    compare_cols = [c for c in EXPECTED if c not in KEY_COLS and c not in ignored]

    # Verschobene/umbenannte Einträge aus removed/added herauslösen
    moves = [] if args.no_detect_moves else find_moves(old, new, removed, added, ignored)
    moved_old = {m[0] for m in moves}
    moved_new = {m[1] for m in moves}
    removed = [k for k in removed if k not in moved_old]
    added = [k for k in added if k not in moved_new]

    groups = {"old_outdated": [], "new_outdated": [], "unclear": []}
    for key in sorted(set(old) & set(new)):
        diffs = [c for c in compare_cols if old[key][c] != new[key][c]]
        if diffs:
            grp, delta = classify(key, old, new, n1, n2)
            groups[grp].append((key, diffs, delta))
    n_changed = sum(len(v) for v in groups.values())

    print(f"{n1}: {len(old)} Einträge")
    print(f"{n2}: {len(new)} Einträge")
    if ignored:
        print(f"Ignorierte Spalten: {', '.join(ignored)}")
    print()

    titles = {
        "old_outdated": f"Geändert – {n2} ist aktueller ({n1} muss aktualisiert werden)",
        "new_outdated": f"Geändert – {n1} ist aktueller ({n2} muss aktualisiert werden)",
        "unclear": "Geändert – Aktualität unklar (manuell prüfen)",
    }

    if args.search is not None:
        needle = args.search.strip().lower()
        changed_by_key = {k: (grp, diffs, delta)
                          for grp, items in groups.items() for k, diffs, delta in items}
        matches = sorted(k for k in set(old) | set(new)
                         if needle in " / ".join(k[:3]).lower())
        if not matches:
            sys.exit(f"Kein Eintrag gefunden, dessen Gruppe, Titel oder Username "
                     f"'{args.search}' enthält.")
        print(f"Suche nach '{args.search}': {len(matches)} Treffer\n")
        removed_set, added_set = set(removed), set(added)
        moved_by_key = {k: m for m in moves for k in m[:2]}
        shown_moves = set()
        for k in matches:
            if k in moved_by_key:
                move = moved_by_key[k]
                if move in shown_moves:
                    continue  # Paar wurde schon über den anderen Key ausgegeben
                shown_moves.add(move)
                print(f"  Status: verschoben/umbenannt")
                print_move(move, compare_cols, old, new, n1, n2, args.show_secrets)
            elif k in removed_set:
                print(f"  - {label(k)}")
                print(f"      Status: nur in {n1} (in {n2} nicht vorhanden)")
                print(f"      Last Modified: {old[k][TIME_COL]}")
            elif k in added_set:
                print(f"  + {label(k)}")
                print(f"      Status: nur in {n2} (in {n1} nicht vorhanden)")
                print(f"      Last Modified: {new[k][TIME_COL]}")
            elif k in changed_by_key:
                grp, diffs, delta = changed_by_key[k]
                print(f"  Status: {titles[grp]}")
                print_changed(k, diffs, delta, old, new, args.show_secrets)
            else:
                print(f"  = {label(k)}")
                print(f"      Status: identisch in beiden Dateien")
                print(f"      Last Modified: {old[k][TIME_COL]}")
            print()
        return

    if moves:
        print(f"== Verschoben/umbenannt: {len(moves)} ==")
        for move in moves:
            print_move(move, compare_cols, old, new, n1, n2, args.show_secrets)
        print()
    if removed:
        print(f"== Nur in {n1} (in {n2} nicht vorhanden): {len(removed)} ==")
        for k in removed:
            print(f"  - {label(k)}")
        print()
    if added:
        print(f"== Nur in {n2} (in {n1} nicht vorhanden): {len(added)} ==")
        for k in added:
            print(f"  + {label(k)}")
        print()

    for grp in ("old_outdated", "new_outdated", "unclear"):
        items = groups[grp]
        if not items:
            continue
        print(f"== {titles[grp]}: {len(items)} ==")
        for k, diffs, delta in items:
            print_changed(k, diffs, delta, old, new, args.show_secrets)
        print()

    if args.export_added:
        export = [k for k in added if not is_excluded(new[k])]
        skipped = len(added) - len(export)
        try:
            with open(args.export_added, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=EXPECTED, extrasaction="ignore")
                w.writeheader()
                for k in export:
                    w.writerow(new[k])
        except OSError as e:
            sys.exit(f"Fehler: '{args.export_added}' kann nicht geschrieben werden: {e}")
        print(f"{len(export)} neue Einträge nach '{args.export_added}' exportiert "
              f"({skipped} aus Papierkorb ausgelassen; Datei enthält Passwörter im Klartext).\n")

    if not (removed or added or n_changed or moves):
        print("Keine Unterschiede.")
    else:
        print(f"Zusammenfassung: {len(removed)} nur in {n1}, {len(added)} nur in {n2}, "
              f"{len(moves)} verschoben/umbenannt, "
              f"{n_changed} geändert "
              f"({len(groups['old_outdated'])} in {n1} zu aktualisieren, "
              f"{len(groups['new_outdated'])} in {n2} zu aktualisieren, "
              f"{len(groups['unclear'])} manuell prüfen).")


if __name__ == "__main__":
    main()
