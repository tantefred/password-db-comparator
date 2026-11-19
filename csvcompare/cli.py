"""Kommandozeile: Optionen einlesen, Dateien laden und das Ergebnis ausgeben."""

import argparse
import sys

from .columns import ALL_NAMES, KEY_NAMES, VALUE_NAMES
from .compare import compare_files
from .display import display_names
from .entries import entries_from_rows, is_trash
from .exports import prepare_added, prepare_merged
from .importers import CsvError, read_file
from .render_json import build_report, dump
from .render_text import (print_check, print_compare, print_header,
                          print_password_check, print_search, print_stats,
                          print_summary)
from .search import search
from .writers import DEFAULT_WRITER


IGNORABLE = VALUE_NAMES


def build_parser():
    p = argparse.ArgumentParser(description="KeePassium-CSV-Exporte vergleichen")
    p.add_argument("alt", nargs="?", help="Erste CSV-Datei")
    p.add_argument("neu", nargs="?", help="Zweite CSV-Datei")
    p.add_argument("--ui", action="store_true",
                   help="Statt im Terminal in einer lokalen Weboberfläche arbeiten "
                        "(Dateien werden dort ausgewählt; alle anderen Optionen entfallen)")
    p.add_argument("--port", type=int, default=8765, metavar="N",
                   help="Port für --ui (Standard: 8765; bei belegtem Port wird der nächste freie genommen)")
    p.add_argument("--no-browser", action="store_true",
                   help="Mit --ui den Browser nicht automatisch öffnen")
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
    p.add_argument("--keep-db-name", action="store_true",
                   help="Den Datenbanknamen am Anfang der Gruppenpfade (KeePassium-Export, "
                        "z. B. DB1/Web) nicht entfernen")
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

    by_lower = {c.lower(): c for c in ALL_NAMES}
    ignored = []
    for part in (s.strip() for item in args.ignore for s in item.split(",")):
        if not part:
            continue
        col = by_lower.get(part.lower())
        if col is None:
            p.error(f"Unbekannte Spalte '{part}'. Gültig: {', '.join(IGNORABLE)}")
        if col in KEY_NAMES:
            p.error(f"Die Spalte '{col}' identifiziert die Einträge und kann nicht ignoriert werden.")
        if col not in ignored:
            ignored.append(col)
    return ignored


def filter_entries(p, args, old, new):
    """Wendet --hide-trash und --group auf beide Dateien an."""
    if args.hide_trash:
        old = {k: r for k, r in old.items() if not is_trash(r)}
        new = {k: r for k, r in new.items() if not is_trash(r)}
    if args.group is not None:
        needle = args.group.strip().lower()
        if not needle:
            p.error("--group benötigt einen nicht-leeren Suchbegriff.")
        old = {k: r for k, r in old.items() if needle in r["Group"].lower()}
        new = {k: r for k, r in new.items() if needle in r["Group"].lower()}
    return old, new


def load_filtered(p, args):
    """Lädt beide Dateien und wendet die Filter an. Rückgabe: (alt, neu, quelle_alt, quelle_neu)."""
    try:
        src_old = read_file(args.alt, keep_db_name=args.keep_db_name)
        src_new = read_file(args.neu, keep_db_name=args.keep_db_name)
    except CsvError as e:
        sys.exit(f"Fehler: {e}")
    old, new = filter_entries(p, args, entries_from_rows(src_old.rows),
                              entries_from_rows(src_new.rows))
    return old, new, src_old, src_new


def run_search(args, cmp):
    hits = search(cmp, args.search)
    if not hits:
        sys.exit(f"Kein Eintrag gefunden, dessen Gruppe, Titel oder Username "
                 f"'{args.search}' enthält.")
    print_search(cmp, args.search, hits, args.show_secrets)


def run_exports(args, cmp, log):
    """Schreibt die angeforderten Exporte und meldet, was dabei passiert ist."""
    requested = ((args.export_added, prepare_added), (args.export_merged, prepare_merged))
    for path, prepare in requested:
        if not path:
            continue
        export = prepare(cmp, path)
        try:
            DEFAULT_WRITER.write(path, export.rows)
        except OSError as e:
            sys.exit(f"Fehler: '{path}' kann nicht geschrieben werden: {e}")
        for line in export.lines:
            log(line)
        log()


def main():
    p = build_parser()
    args = p.parse_args()
    if args.ui:
        if args.alt or args.neu:
            p.error("--ui braucht keine Dateien; wähle sie in der Oberfläche aus.")
        from .webui import serve  # nur laden, wenn die Oberfläche gebraucht wird
        serve(args.port, open_browser=not args.no_browser)
        return
    if not (args.alt and args.neu):
        p.error("the following arguments are required: alt, neu")
    ignored = validate_args(p, args)
    as_json = args.format == "json"
    # Im JSON-Modus bleibt stdout dem JSON vorbehalten
    log = (lambda *a, **k: print(*a, file=sys.stderr, **k)) if as_json else print

    old, new, src_old, src_new = load_filtered(p, args)
    old_name, new_name = display_names(args.alt, args.neu)
    cmp = compare_files(old, new, old_name, new_name, ignored,
                        detect_moves=not args.no_detect_moves,
                        old_source=src_old, new_source=src_new)

    if as_json:
        run_exports(args, cmp, log)
        report, status = build_report(args, cmp)
        dump(report)
        sys.exit(status)

    print_header(cmp, args)
    print()
    if args.stats:
        print_stats(cmp)
    elif args.check:
        print_check(cmp)
    elif args.password_check:
        print_password_check(cmp, args.min_length, args.max_age_days)
    elif args.search is not None:
        run_search(args, cmp)
    else:
        print_compare(cmp, args.show_secrets)
        run_exports(args, cmp, log)
        print_summary(cmp)
