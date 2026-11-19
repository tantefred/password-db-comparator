"""Kommandozeile: Optionen einlesen und Ergebnis ausgeben."""

import argparse
from datetime import datetime, timezone
import json
import sys

from .analysis import audit_entries, check_entries, stats_rows
from .common import display_names, is_excluded, label
from .compare import build_merged, classify, find_moves, search_matches
from .constants import EXPECTED, KEY_COLS, TIME_COL
from .csvio import load, write_csv
from .render_json import changed_json, entry_ref, move_json
from .render_text import print_changed, print_check, print_move, print_password_check, print_stats


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
    p.add_argument("--hide-trash", action="store_true",
                   help="Einträge aus Papierkorb-Gruppen komplett ausblenden "
                        "(Vergleich, Suche und Exporte)")
    p.add_argument("-g", "--group", metavar="TEXT",
                   help="Nur Einträge betrachten, deren Gruppenpfad TEXT enthält "
                        "(Groß-/Kleinschreibung egal), z. B. --group Privat. "
                        "Gilt für Vergleich, Suche und Exporte.")
    p.add_argument("--stats", action="store_true",
                   help="Nur die Anzahl der Einträge pro Gruppe in beiden Dateien anzeigen "
                        "(nicht kombinierbar mit --search, --export-added, --export-merged)")
    p.add_argument("--check", action="store_true",
                   help="Jede Datei einzeln auf Dubletten und kaputte Einträge prüfen "
                        "(ohne Passwörter anzuzeigen; nicht kombinierbar mit --search, "
                        "--stats und den Exporten)")
    p.add_argument("--password-check", action="store_true",
                   help="Passwortqualität je Datei prüfen: wiederverwendete und kurze Passwörter, "
                        "lange nicht geänderte Einträge, TOTP-Anzahl (Passwörter werden nie "
                        "angezeigt; nicht kombinierbar mit --search, --stats, --check, Exporten)")
    p.add_argument("--min-length", type=int, default=10, metavar="N",
                   help="Mindestlänge für --password-check (Standard: 10)")
    p.add_argument("--max-age-days", type=int, default=730, metavar="TAGE",
                   help="Maximales Alter seit der letzten Änderung für --password-check "
                        "(Standard: 730)")
    p.add_argument("--format", choices=("text", "json"), default="text",
                   help="Ausgabeformat (Standard: text). Bei json steht nur das JSON auf stdout; "
                        "Hinweise zu Exporten gehen nach stderr. Passwörter bleiben maskiert, "
                        "außer mit --show-secrets.")
    p.add_argument("--no-detect-moves", action="store_true",
                   help="Verschobene/umbenannte Einträge nicht erkennen "
                        "(sie erscheinen dann als 'entfernt' plus 'hinzugefügt')")
    p.add_argument("--export-added", nargs="?", const="neue_eintraege.csv",
                   metavar="DATEI",
                   help="Neu hinzugefügte Einträge als CSV schreiben "
                        "(Standard: neue_eintraege.csv). Enthält Passwörter im Klartext! "
                        "Einträge aus Papierkorb-Gruppen werden ausgelassen.")
    p.add_argument("--export-merged", nargs="?", const="merged.csv", metavar="DATEI",
                   help="Zusammengeführte CSV schreiben: alle Einträge beider Dateien, bei "
                        "Unterschieden die jeweils neuere Version (Standard: merged.csv). "
                        "Enthält Passwörter im Klartext! Papierkorb-Gruppen werden ausgelassen. "
                        "Nicht kombinierbar mit --search.")
    args = p.parse_args()

    # Auswertungsmodi ersetzen die normale Ausgabe und schließen sich gegenseitig
    # sowie die Exporte aus.
    modes = [name for name, active in (("--search", args.search is not None),
                                       ("--stats", args.stats),
                                       ("--check", args.check),
                                       ("--password-check", args.password_check)) if active]
    exports = [name for name, active in (("--export-added", args.export_added),
                                         ("--export-merged", args.export_merged)) if active]
    if len(modes) > 1:
        p.error(f"{modes[0]} und {modes[1]} können nicht kombiniert werden.")
    if modes and exports:
        p.error(f"{modes[0]} und {exports[0]} können nicht kombiniert werden.")
    if args.search is not None and not args.search.strip():
        p.error("--search benötigt einen nicht-leeren Suchbegriff.")
    as_json = args.format == "json"
    # Im JSON-Modus bleibt stdout dem JSON vorbehalten
    log = (lambda *a, **k: print(*a, file=sys.stderr, **k)) if as_json else print

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
    if args.hide_trash:
        old = {k: r for k, r in old.items() if not is_excluded(r)}
        new = {k: r for k, r in new.items() if not is_excluded(r)}
    if args.group is not None:
        needle = args.group.strip().lower()
        if not needle:
            p.error("--group benötigt einen nicht-leeren Suchbegriff.")
        old = {k: r for k, r in old.items() if needle in r["Group"].lower()}
        new = {k: r for k, r in new.items() if needle in r["Group"].lower()}
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

    if not as_json:
        print(f"{n1}: {len(old)} Einträge")
        print(f"{n2}: {len(new)} Einträge")
        if ignored:
            print(f"Ignorierte Spalten: {', '.join(ignored)}")
        if args.hide_trash:
            print("Papierkorb-Gruppen ausgeblendet")
        if args.group is not None:
            print(f"Gruppenfilter: '{args.group.strip()}'")
    base = {
        "files": {
            "old": {"name": n1, "path": args.alt, "entries": len(old)},
            "new": {"name": n2, "path": args.neu, "entries": len(new)},
        },
        "filters": {
            "ignored_columns": ignored,
            "hide_trash": args.hide_trash,
            "group": args.group.strip() if args.group is not None else None,
            "detect_moves": not args.no_detect_moves,
        },
    }
    if args.stats:
        if as_json:
            rows = stats_rows(old, new)
            report = {"mode": "stats", **base,
                      "groups": [{"group": g, "old": a, "new": b, "difference": b - a}
                                 for g, a, b in rows],
                      "total": {"old": len(old), "new": len(new),
                                "difference": len(new) - len(old)}}
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return
        print()
        print_stats(old, new, n1, n2)
        return
    if args.check:
        if as_json:
            report = {"mode": "check", **base,
                      "results": [{"file": name, "findings": [
                          {"category": t, "count": len(ls), "items": ls}
                          for t, ls in check_entries(entries)]}
                          for name, entries in ((n1, old), (n2, new))]}
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return
        print()
        print_check(old, new, n1, n2)
        return
    if args.password_check:
        if as_json:
            now = datetime.now(timezone.utc)
            results = []
            for name, entries in ((n1, old), (n2, new)):
                findings, totp = audit_entries(entries, args.min_length, args.max_age_days, now)
                results.append({"file": name,
                                "findings": [{"category": t, "count": len(ls), "items": ls}
                                             for t, ls in findings],
                                "totp": {"with_totp": totp, "entries": len(entries)}})
            report = {"mode": "password-check", **base,
                      "thresholds": {"min_length": args.min_length,
                                     "max_age_days": args.max_age_days},
                      "results": results}
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return
        print()
        print_password_check(old, new, n1, n2, args.min_length, args.max_age_days)
        return
    if not as_json:
        print()

    titles = {
        "old_outdated": f"Geändert – {n2} ist aktueller ({n1} muss aktualisiert werden)",
        "new_outdated": f"Geändert – {n1} ist aktueller ({n2} muss aktualisiert werden)",
        "unclear": "Geändert – Aktualität unklar (manuell prüfen)",
    }

    if args.search is not None:
        n_matches, results = search_matches(args.search, old, new, removed, added,
                                            moves, groups)
        if as_json:
            status_of = {"old_outdated": "newer_in_new", "new_outdated": "newer_in_old",
                         "unclear": "unclear"}
            items = []
            for kind, data in results:
                if kind == "moved":
                    items.append({"status": "moved", **move_json(
                        data, compare_cols, old, new, n1, n2, args.show_secrets)})
                elif kind == "changed":
                    k, grp, diffs, delta = data
                    items.append({"status": status_of[grp], **changed_json(
                        k, k, diffs, delta, old, new, args.show_secrets)})
                elif kind == "only_old":
                    items.append({"status": "only_in_old", "entry": entry_ref(data),
                                  "last_modified": old[data][TIME_COL]})
                elif kind == "only_new":
                    items.append({"status": "only_in_new", "entry": entry_ref(data),
                                  "last_modified": new[data][TIME_COL]})
                else:
                    items.append({"status": "identical", "entry": entry_ref(data),
                                  "last_modified": old[data][TIME_COL]})
            print(json.dumps({"mode": "search", **base, "query": args.search,
                              "match_count": n_matches, "results": items},
                             ensure_ascii=False, indent=2))
            sys.exit(0 if n_matches else 1)
        if not n_matches:
            sys.exit(f"Kein Eintrag gefunden, dessen Gruppe, Titel oder Username "
                     f"'{args.search}' enthält.")
        print(f"Suche nach '{args.search}': {n_matches} Treffer\n")
        for kind, data in results:
            if kind == "moved":
                print(f"  Status: verschoben/umbenannt")
                print_move(data, compare_cols, old, new, n1, n2, args.show_secrets)
            elif kind == "only_old":
                print(f"  - {label(data)}")
                print(f"      Status: nur in {n1} (in {n2} nicht vorhanden)")
                print(f"      Last Modified: {old[data][TIME_COL]}")
            elif kind == "only_new":
                print(f"  + {label(data)}")
                print(f"      Status: nur in {n2} (in {n1} nicht vorhanden)")
                print(f"      Last Modified: {new[data][TIME_COL]}")
            elif kind == "changed":
                k, grp, diffs, delta = data
                print(f"  Status: {titles[grp]}")
                print_changed(k, diffs, delta, old, new, args.show_secrets)
            else:
                print(f"  = {label(data)}")
                print(f"      Status: identisch in beiden Dateien")
                print(f"      Last Modified: {old[data][TIME_COL]}")
            print()
        return

    if not as_json:
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
        write_csv(args.export_added, [new[k] for k in export])
        log(f"{len(export)} neue Einträge nach '{args.export_added}' exportiert "
              f"({skipped} aus Papierkorb ausgelassen; Datei enthält Passwörter im Klartext).\n")

    if args.export_merged:
        rows, stats, conflicts = build_merged(old, new, removed, added, moves, compare_cols)
        export = [r for r in rows if not is_excluded(r)]
        write_csv(args.export_merged, export)
        log(f"{len(export)} Einträge nach '{args.export_merged}' exportiert "
              f"({len(rows) - len(export)} aus Papierkorb ausgelassen; "
              f"Datei enthält Passwörter im Klartext).")
        log(f"  nur in {n1}: {stats['nur_alt']}, nur in {n2}: {stats['nur_neu']}, "
              f"neuere Version aus {n1}: {stats['alt_neuer']}, "
              f"aus {n2}: {stats['neu_neuer']}, unverändert: {stats['gleich']}")
        if conflicts:
            log(f"  {len(conflicts)} Konflikt(e) mit unklarer Aktualität – "
                  f"Version aus {n2} übernommen, bitte prüfen:")
            for k in conflicts:
                log(f"    ! {label(k)}")
        log()

    if as_json:
        report = {
            "mode": "compare",
            **base,
            "moved": [move_json(m, compare_cols, old, new, n1, n2, args.show_secrets)
                      for m in moves],
            "only_in_old": [entry_ref(k) for k in removed],
            "only_in_new": [entry_ref(k) for k in added],
            "changed": {
                "newer_in_new": [changed_json(k, k, d, dl, old, new, args.show_secrets)
                                 for k, d, dl in groups["old_outdated"]],
                "newer_in_old": [changed_json(k, k, d, dl, old, new, args.show_secrets)
                                 for k, d, dl in groups["new_outdated"]],
                "unclear": [changed_json(k, k, d, dl, old, new, args.show_secrets)
                            for k, d, dl in groups["unclear"]],
            },
            "summary": {
                "only_in_old": len(removed), "only_in_new": len(added),
                "moved": len(moves), "changed": n_changed,
                "newer_in_new": len(groups["old_outdated"]),
                "newer_in_old": len(groups["new_outdated"]),
                "unclear": len(groups["unclear"]),
                "identical": not (removed or added or n_changed or moves),
            },
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    if not (removed or added or n_changed or moves):
        print("Keine Unterschiede.")
    else:
        print(f"Zusammenfassung: {len(removed)} nur in {n1}, {len(added)} nur in {n2}, "
              f"{len(moves)} verschoben/umbenannt, "
              f"{n_changed} geändert "
              f"({len(groups['old_outdated'])} in {n1} zu aktualisieren, "
              f"{len(groups['new_outdated'])} in {n2} zu aktualisieren, "
              f"{len(groups['unclear'])} manuell prüfen).")
