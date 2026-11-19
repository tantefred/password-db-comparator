"""Kommandozeile: Optionen einlesen, Dateien laden und das Ergebnis ausgeben."""

import argparse
import sys

from .common import display_names, is_excluded
from .compare import compare_files, search_matches
from .constants import EXPECTED, KEY_COLS
from .csvio import load
from .exports import export_added, export_merged
from .render_json import (base_report, check_report, compare_report, dump,
                          password_report, search_report, stats_report)
from .render_text import (print_check, print_compare, print_header,
                          print_password_check, print_search, print_stats,
                          print_summary)

IGNORABLE = [c for c in EXPECTED if c not in KEY_COLS]


def build_parser():
    p = argparse.ArgumentParser(description="KeePassium-CSV-Exporte vergleichen")
    p.add_argument("alt", help="Erste CSV-Datei")
    p.add_argument("neu", help="Zweite CSV-Datei")
    p.add_argument("--show-secrets", action="store_true",
                   help="Passwörter/TOTP im Klartext anzeigen")
    p.add_argument("-i", "--ignore", nargs="+", default=[], metavar="SPALTE",
                   help="Spalten, die beim Vergleich ignoriert werden "
                        "(z. B. --ignore Icon \"Last Modified\" oder --ignore Icon,Notes). "
                        f"Mögliche Werte: {', '.join(IGNORABLE)}")
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
    return p


def validate_args(p, args):
    """Prüft Optionskombinationen und gibt die kanonischen Namen der ignorierten Spalten zurück."""
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

    by_lower = {c.lower(): c for c in EXPECTED}
    ignored = []
    for part in (s.strip() for item in args.ignore for s in item.split(",")):
        if not part:
            continue
        col = by_lower.get(part.lower())
        if col is None:
            p.error(f"Unbekannte Spalte '{part}'. Gültig: {', '.join(IGNORABLE)}")
        if col in KEY_COLS:
            p.error(f"Die Spalte '{col}' identifiziert die Einträge und kann nicht ignoriert werden.")
        if col not in ignored:
            ignored.append(col)
    return ignored


def load_filtered(p, args):
    """Lädt beide Dateien und wendet --hide-trash und --group an."""
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
    return old, new


def run_search(args, cmp, base, as_json):
    n_matches, results = search_matches(args.search, cmp.old, cmp.new, cmp.removed,
                                        cmp.added, cmp.moves, cmp.groups)
    if as_json:
        dump(search_report(base, cmp, args.search, n_matches, results, args.show_secrets))
        sys.exit(0 if n_matches else 1)
    if not n_matches:
        sys.exit(f"Kein Eintrag gefunden, dessen Gruppe, Titel oder Username "
                 f"'{args.search}' enthält.")
    print_search(args.search, n_matches, results, cmp, args.show_secrets)


def run_compare(args, cmp, base, as_json, log):
    if not as_json:
        print_compare(cmp, args.show_secrets)
    if args.export_added:
        export_added(cmp, args.export_added, log)
    if args.export_merged:
        export_merged(cmp, args.export_merged, log)
    if as_json:
        dump(compare_report(base, cmp, args.show_secrets))
    else:
        print_summary(cmp)


def main():
    p = build_parser()
    args = p.parse_args()
    ignored = validate_args(p, args)
    as_json = args.format == "json"
    # Im JSON-Modus bleibt stdout dem JSON vorbehalten
    log = (lambda *a, **k: print(*a, file=sys.stderr, **k)) if as_json else print

    old, new = load_filtered(p, args)
    n1, n2 = display_names(args.alt, args.neu)
    cmp = compare_files(old, new, n1, n2, ignored, detect_moves=not args.no_detect_moves)
    base = base_report(cmp, args.alt, args.neu, args.hide_trash, args.group,
                       not args.no_detect_moves)

    if not as_json:
        print_header(cmp, args.hide_trash, args.group)
        print()

    if args.stats:
        dump(stats_report(base, cmp)) if as_json else print_stats(old, new, n1, n2)
    elif args.check:
        dump(check_report(base, cmp)) if as_json else print_check(old, new, n1, n2)
    elif args.password_check:
        if as_json:
            dump(password_report(base, cmp, args.min_length, args.max_age_days))
        else:
            print_password_check(old, new, n1, n2, args.min_length, args.max_age_days)
    elif args.search is not None:
        run_search(args, cmp, base, as_json)
    else:
        run_compare(args, cmp, base, as_json, log)
