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
from .render_text import (
    print_check,
    print_compare,
    print_header,
    print_password_check,
    print_search,
    print_stats,
    print_summary,
)
from .search import search
from .writers import DEFAULT_WRITER


def build_parser():
    parser = argparse.ArgumentParser(
        description="Zwei Passwort-Exporte vergleichen "
        "(KeePass-CSV, Bitwarden/Vaultwarden-JSON oder -CSV)"
    )
    parser.add_argument("alt", nargs="?", help="Erste Datei (CSV oder JSON)")
    parser.add_argument("neu", nargs="?", help="Zweite Datei (CSV oder JSON)")
    parser.add_argument(
        "--ui",
        action="store_true",
        help="Statt im Terminal in einer lokalen Weboberfläche arbeiten "
        "(Dateien werden dort ausgewählt; alle anderen Optionen entfallen)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        metavar="N",
        help="Port für --ui (Standard: 8765; bei belegtem Port wird der nächste freie genommen)",
    )
    parser.add_argument(
        "--no-browser", action="store_true", help="Mit --ui den Browser nicht automatisch öffnen"
    )
    parser.add_argument(
        "--show-secrets", action="store_true", help="Passwörter/TOTP im Klartext anzeigen"
    )
    parser.add_argument(
        "-i",
        "--ignore",
        nargs="+",
        default=[],
        metavar="SPALTE",
        help="Spalten, die beim Vergleich ignoriert werden "
        '(z. B. --ignore Icon "Last Modified" oder --ignore Icon,Notes). '
        f"Mögliche Werte: {', '.join(VALUE_NAMES)}",
    )
    parser.add_argument(
        "-s",
        "--search",
        metavar="TEXT",
        help="Nur Einträge anzeigen, deren Gruppe, Titel oder Username TEXT enthält "
        "(Groß-/Kleinschreibung egal), samt Status. "
        "Nicht kombinierbar mit --export-added.",
    )
    parser.add_argument(
        "--hide-trash",
        action="store_true",
        help="Einträge aus Papierkorb-Gruppen komplett ausblenden (Vergleich, Suche und Exporte)",
    )
    parser.add_argument(
        "-g",
        "--group",
        metavar="TEXT",
        help="Nur Einträge betrachten, deren Gruppenpfad TEXT enthält "
        "(Groß-/Kleinschreibung egal), z. B. --group Privat. "
        "Gilt für Vergleich, Suche und Exporte.",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Nur die Anzahl der Einträge pro Gruppe in beiden Dateien anzeigen "
        "(nicht kombinierbar mit --search, --export-added, --export-merged)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Jede Datei einzeln auf Dubletten und kaputte Einträge prüfen "
        "(ohne Passwörter anzuzeigen; nicht kombinierbar mit --search, "
        "--stats und den Exporten)",
    )
    parser.add_argument(
        "--password-check",
        action="store_true",
        help="Passwortqualität je Datei prüfen: wiederverwendete und kurze "
        "Passwörter, lange nicht geänderte Einträge, TOTP-Anzahl (Passwörter "
        "werden nie angezeigt; nicht kombinierbar mit --search, --stats, "
        "--check, Exporten)",
    )
    parser.add_argument(
        "--min-length",
        type=int,
        default=10,
        metavar="N",
        help="Mindestlänge für --password-check (Standard: 10)",
    )
    parser.add_argument(
        "--max-age-days",
        type=int,
        default=730,
        metavar="TAGE",
        help="Maximales Alter seit der letzten Änderung für --password-check (Standard: 730)",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Ausgabeformat (Standard: text). Bei json steht nur das JSON auf stdout; "
        "Hinweise zu Exporten gehen nach stderr. Passwörter bleiben maskiert, "
        "außer mit --show-secrets.",
    )
    parser.add_argument(
        "--keep-db-name",
        action="store_true",
        help="Den Datenbanknamen am Anfang der Gruppenpfade (KeePassium-Export, "
        "z. B. DB1/Web) nicht entfernen",
    )
    parser.add_argument(
        "--no-detect-moves",
        action="store_true",
        help="Verschobene/umbenannte Einträge nicht erkennen "
        "(sie erscheinen dann als 'entfernt' plus 'hinzugefügt')",
    )
    parser.add_argument(
        "--export-added",
        nargs="?",
        const="neue_eintraege.csv",
        metavar="DATEI",
        help="Neu hinzugefügte Einträge als CSV schreiben "
        "(Standard: neue_eintraege.csv). Enthält Passwörter im Klartext! "
        "Einträge aus Papierkorb-Gruppen werden ausgelassen.",
    )
    parser.add_argument(
        "--export-merged",
        nargs="?",
        const="merged.csv",
        metavar="DATEI",
        help="Zusammengeführte CSV schreiben: alle Einträge beider Dateien, bei "
        "Unterschieden die jeweils neuere Version (Standard: merged.csv). "
        "Enthält Passwörter im Klartext! Papierkorb-Gruppen werden ausgelassen. "
        "Nicht kombinierbar mit --search.",
    )
    return parser


def check_combinations(parser, args):
    """Auswertungsmodi ersetzen die normale Ausgabe; sie schließen sich gegenseitig aus."""
    modes = [
        name
        for name, active in (
            ("--search", args.search is not None),
            ("--stats", args.stats),
            ("--check", args.check),
            ("--password-check", args.password_check),
        )
        if active
    ]
    exports = [
        name
        for name, active in (
            ("--export-added", args.export_added),
            ("--export-merged", args.export_merged),
        )
        if active
    ]
    if len(modes) > 1:
        parser.error(f"{modes[0]} und {modes[1]} können nicht kombiniert werden.")
    if modes and exports:
        parser.error(f"{modes[0]} und {exports[0]} können nicht kombiniert werden.")
    if args.search is not None and not args.search.strip():
        parser.error("--search benötigt einen nicht-leeren Suchbegriff.")


def parse_ignored(parser, args):
    """Die Namen der per --ignore genannten Spalten in kanonischer Schreibweise."""
    canonical = {name.lower(): name for name in ALL_NAMES}
    ignored = []
    for item in args.ignore:
        for part in (piece.strip() for piece in item.split(",")):
            if not part:
                continue
            column = canonical.get(part.lower())
            if column is None:
                parser.error(f"Unbekannte Spalte '{part}'. Gültig: {', '.join(VALUE_NAMES)}")
            if column in KEY_NAMES:
                parser.error(
                    f"Die Spalte '{column}' identifiziert die Einträge und kann nicht "
                    f"ignoriert werden."
                )
            if column not in ignored:
                ignored.append(column)
    return ignored


def validate_args(parser, args):
    """Prüft die Optionen und gibt die ignorierten Spalten zurück."""
    check_combinations(parser, args)
    return parse_ignored(parser, args)


def filter_entries(parser, args, old, new):
    """Wendet --hide-trash und --group auf beide Dateien an."""
    if args.hide_trash:
        old = {key: row for key, row in old.items() if not is_trash(row)}
        new = {key: row for key, row in new.items() if not is_trash(row)}
    if args.group is not None:
        needle = args.group.strip().lower()
        if not needle:
            parser.error("--group benötigt einen nicht-leeren Suchbegriff.")
        old = {key: row for key, row in old.items() if needle in row["Group"].lower()}
        new = {key: row for key, row in new.items() if needle in row["Group"].lower()}
    return old, new


def build_comparison(parser, args, ignored, old_source, new_source, old_name, new_name):
    """Vergleicht zwei gelesene Dateien unter Beachtung der Filter-Optionen.

    Gemeinsamer Weg für Terminal und Weboberfläche.
    """
    old, new = filter_entries(
        parser, args, entries_from_rows(old_source.rows), entries_from_rows(new_source.rows)
    )
    return compare_files(
        old,
        new,
        old_name,
        new_name,
        ignored,
        detect_moves=not args.no_detect_moves,
        old_source=old_source,
        new_source=new_source,
    )


def log_to_stderr(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


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


def run_search(args, cmp):
    hits = search(cmp, args.search)
    if not hits:
        sys.exit(
            f"Kein Eintrag gefunden, dessen Gruppe, Titel oder Username '{args.search}' enthält."
        )
    print_search(cmp, args.search, hits, args.show_secrets)


def run_json(args, cmp):
    """JSON-Ausgabe: stdout bleibt dem JSON vorbehalten, Hinweise zu Exporten gehen nach stderr."""
    run_exports(args, cmp, log_to_stderr)
    report, status = build_report(args, cmp)
    dump(report)
    sys.exit(status)


def run_text(args, cmp):
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
        run_exports(args, cmp, print)
        print_summary(cmp)


def run_ui(parser, args):
    if args.alt or args.neu:
        parser.error("--ui braucht keine Dateien; wähle sie in der Oberfläche aus.")
    from .webui import serve  # nur laden, wenn die Oberfläche gebraucht wird

    serve(args.port, open_browser=not args.no_browser)


def main():
    parser = build_parser()
    args = parser.parse_args()
    if args.ui:
        return run_ui(parser, args)
    if not (args.alt and args.neu):
        parser.error("the following arguments are required: alt, neu")
    ignored = validate_args(parser, args)

    try:
        old_source = read_file(args.alt, keep_db_name=args.keep_db_name)
        new_source = read_file(args.neu, keep_db_name=args.keep_db_name)
    except CsvError as e:
        sys.exit(f"Fehler: {e}")
    old_name, new_name = display_names(args.alt, args.neu)
    cmp = build_comparison(parser, args, ignored, old_source, new_source, old_name, new_name)

    if args.format == "json":
        run_json(args, cmp)
    else:
        run_text(args, cmp)
