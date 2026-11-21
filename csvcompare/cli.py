"""Kommandozeile: Optionen einlesen, Dateien laden und das Ergebnis ausgeben."""

import argparse
import sys

from .columns import ALL_NAMES, KEY_NAMES, VALUE_NAMES
from .compare import compare_files, single_file
from .display import display_names
from .duplicates import KEY, KINDS, LOGIN
from .entries import entries_from_rows, is_trash
from .exports import export_path, pick_writer, prepare_added, prepare_clean, prepare_merged
from .importers import CsvError, read_file
from .modes import CHECK, CLEAN, DEDUPE, OVERVIEW, PASSWORD_CHECK, SEARCH, STATS, selected_mode
from .render_json import build_report, dump
from .render_text import (
    print_check,
    print_compare,
    print_dedupe,
    print_header,
    print_overview,
    print_password_check,
    print_search,
    print_stats,
    print_summary,
)
from .search import search
from .writers import WRITERS


def positive_int(text):
    """argparse-Typ: eine ganze Zahl größer als 0."""
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{text}' ist keine ganze Zahl.") from None
    if value < 1:
        raise argparse.ArgumentTypeError("muss mindestens 1 sein.")
    return value


def build_parser():
    parser = argparse.ArgumentParser(
        description="Passwort-Exporte vergleichen, auswerten und bereinigen: zwei Dateien "
        "vergleichen oder eine Datei prüfen (KeePass-CSV, Bitwarden/Vaultwarden-JSON oder -CSV)"
    )
    parser.add_argument("alt", nargs="?", help="Erste Datei (CSV oder JSON)")
    parser.add_argument(
        "neu",
        nargs="?",
        help="Zweite Datei (CSV oder JSON); ohne sie wird nur die erste ausgewertet",
    )
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
        "--overview",
        action="store_true",
        help="Statistik, Prüfung und Passwortqualität in einem Bericht; bei nur einer Datei "
        "der Standard (nicht kombinierbar mit --search, --stats, --check, --password-check)",
    )
    parser.add_argument(
        "--dedupe",
        action="store_true",
        help="Dublettengruppen einer Datei auflisten (nicht kombinierbar mit anderen Modi)",
    )
    parser.add_argument(
        "--dedupe-kinds",
        default=",".join(KINDS),
        metavar="ARTEN",
        help="Arten für --dedupe, kommagetrennt: key (gleicher Schlüssel), login (gleiche URL "
        "und Username), title (gleicher Titel in anderen Gruppen); Standard: alle",
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
        type=positive_int,
        default=10,
        metavar="N",
        help="Mindestlänge für --password-check (Standard: 10)",
    )
    parser.add_argument(
        "--max-age-days",
        type=positive_int,
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
        const=True,
        metavar="DATEI",
        help="Neu hinzugefügte Einträge schreiben (Standard: neue_eintraege.csv bzw. .json, "
        "je nach --export-format). Enthält Passwörter im Klartext! "
        "Einträge aus Papierkorb-Gruppen werden ausgelassen.",
    )
    parser.add_argument(
        "--export-merged",
        nargs="?",
        const=True,
        metavar="DATEI",
        help="Zusammengeführte Datei schreiben: alle Einträge beider Dateien, bei "
        "Unterschieden die jeweils neuere Version (Standard: merged.csv bzw. .json, "
        "je nach --export-format). Enthält Passwörter im Klartext! "
        "Papierkorb-Gruppen werden ausgelassen. Nicht kombinierbar mit --search.",
    )
    parser.add_argument(
        "--export-clean",
        nargs="?",
        const=True,
        metavar="DATEI",
        help="Eine einzelne Datei ohne Dubletten schreiben (Standard: bereinigt.csv bzw. .json). "
        "Ohne Rückfragen: Gruppen der Arten aus --clean-kinds werden zusammengeführt, der "
        "zuletzt geänderte Eintrag gewinnt. Enthält Passwörter im Klartext!",
    )
    parser.add_argument(
        "--clean-kinds",
        default="key",
        metavar="ARTEN",
        help="Arten, die --export-clean zusammenführt (key, login; Standard: key). "
        "„title“ wird nie automatisch zusammengeführt.",
    )
    parser.add_argument(
        "--export-format",
        choices=tuple(WRITERS),
        help="Format der Exporte: keepass-csv (Standard) oder bitwarden-json "
        "(unverschlüsselt, zum Import in Bitwarden/Vaultwarden).",
    )
    return parser


def check_combinations(parser, args):
    """Auswertungsmodi ersetzen die normale Ausgabe; sie schließen sich gegenseitig aus."""
    modes = [
        name
        for name, active in (
            ("--search", args.search is not None),
            ("--overview", args.overview),
            ("--dedupe", args.dedupe),
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
    if args.export_clean and args.neu:
        parser.error("--export-clean wertet eine einzelne Datei aus; zweite Datei weglassen.")
    if args.export_clean and exports:
        parser.error(f"--export-clean und {exports[0]} können nicht kombiniert werden.")
    if args.export_clean and modes and modes != ["--dedupe"]:
        parser.error(f"{modes[0]} und --export-clean können nicht kombiniert werden.")
    if args.dedupe and args.neu:
        parser.error("--dedupe wertet eine einzelne Datei aus; zweite Datei weglassen.")
    if args.export_format and not exports and not args.export_clean:
        parser.error("--export-format braucht --export-added, --export-merged oder --export-clean.")
    if not args.neu and exports:
        parser.error(f"{exports[0]} braucht zwei Dateien (alt und neu).")


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


def parse_kinds(parser, args):
    """Macht aus ``--dedupe-kinds`` ein Tupel gültiger Arten (in fester Reihenfolge)."""
    wanted = [part.strip().lower() for part in args.dedupe_kinds.split(",") if part.strip()]
    unknown = [part for part in wanted if part not in KINDS]
    if unknown or not wanted:
        parser.error(
            f"Unbekannte Dublettenart '{(unknown or [''])[0]}'. Gültig: {', '.join(KINDS)}"
        )
    args.dedupe_kinds = tuple(kind for kind in KINDS if kind in wanted)


def parse_clean_kinds(parser, args):
    """Macht aus ``--clean-kinds`` ein Tupel der Arten, die automatisch zusammengeführt werden."""
    wanted = [part.strip().lower() for part in args.clean_kinds.split(",") if part.strip()]
    allowed = (KEY, LOGIN)
    bad = [part for part in wanted if part not in allowed]
    if bad or not wanted:
        shown = bad[0] if bad else ""
        parser.error(
            f"Ungültige Art '{shown}' für --clean-kinds. Gültig: {', '.join(allowed)} "
            f"(„title“ wird nie automatisch zusammengeführt)."
        )
    args.clean_kinds = tuple(kind for kind in allowed if kind in wanted)


def validate_args(parser, args):
    """Prüft die Optionen und gibt die ignorierten Spalten zurück."""
    check_combinations(parser, args)
    parse_kinds(parser, args)
    parse_clean_kinds(parser, args)
    return parse_ignored(parser, args)


def filter_entries(parser, args, entries):
    """Wendet --hide-trash und --group auf die Einträge einer Datei an."""
    if args.hide_trash:
        entries = {key: row for key, row in entries.items() if not is_trash(row)}
    if args.group is not None:
        needle = args.group.strip().lower()
        if not needle:
            parser.error("--group benötigt einen nicht-leeren Suchbegriff.")
        entries = {key: row for key, row in entries.items() if needle in row["Group"].lower()}
    return entries


def build_comparison(parser, args, ignored, old_source, new_source, old_name, new_name):
    """Vergleicht zwei gelesene Dateien unter Beachtung der Filter-Optionen.

    Ohne zweite Datei (``new_source=None``) entsteht eine Auswertung nur der ersten.
    Gemeinsamer Weg für Terminal und Weboberfläche.
    """
    old = filter_entries(parser, args, entries_from_rows(old_source.rows))
    if new_source is None:
        return single_file(old, old_name, ignored, old_source)
    new = filter_entries(parser, args, entries_from_rows(new_source.rows))
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

    def prepare_clean_export(cmp, path, writer):
        return prepare_clean(cmp, path, writer, auto_kinds=args.clean_kinds)

    writer = pick_writer(args.export_format)
    requested = (
        (args.export_added, "added", prepare_added),
        (args.export_merged, "merged", prepare_merged),
        (args.export_clean, "clean", prepare_clean_export),
    )
    for value, kind, prepare in requested:
        if not value:
            continue
        path = export_path(value, kind, writer)
        export = prepare(cmp, path, writer)
        try:
            export.writer.write(path, export.rows)
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
    mode = selected_mode(args, cmp.single)
    if mode == STATS:
        print_stats(cmp)
    elif mode == CHECK:
        print_check(cmp)
    elif mode == PASSWORD_CHECK:
        print_password_check(cmp, args.min_length, args.max_age_days)
    elif mode == OVERVIEW:
        print_overview(cmp, args.min_length, args.max_age_days)
    elif mode == DEDUPE:
        print_dedupe(cmp, args.dedupe_kinds, args.show_secrets)
        if args.export_clean:
            print()
            run_exports(args, cmp, print)
    elif mode == SEARCH:
        run_search(args, cmp)
    elif mode == CLEAN:
        run_exports(args, cmp, print)
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
    if not args.alt:
        parser.error("Es wird mindestens eine Datei benötigt (alt, optional neu).")
    ignored = validate_args(parser, args)

    try:
        old_source = read_file(args.alt, keep_db_name=args.keep_db_name)
        new_source = read_file(args.neu, keep_db_name=args.keep_db_name) if args.neu else None
    except CsvError as e:
        sys.exit(f"Fehler: {e}")
    old_name, new_name = display_names(args.alt, args.neu)
    cmp = build_comparison(parser, args, ignored, old_source, new_source, old_name, new_name)

    if args.format == "json":
        run_json(args, cmp)
    else:
        run_text(args, cmp)
