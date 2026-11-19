"""Auswertung ohne Dateipfade: CSV-Texte und Optionen hinein, Bericht und Exporte heraus.

Wird von der Weboberfläche genutzt. Optionen werden in genau die Kommandozeilen-Argumente
übersetzt und vom selben Parser geprüft wie im Terminal, damit beide Wege gleich
funktionieren.
"""

import shlex

from .cli import build_parser, filter_entries, validate_args
from .compare import compare_files
from .csvio import CsvError, csv_text, entries_from_rows, read_text
from .exports import added_export, merged_export
from .render_json import base_report, entry_ref
from .report import build_report

MODES = ("compare", "search", "stats", "check", "password-check")


class UsageError(Exception):
    """Ungültige Eingabe oder Optionskombination; die Meldung ist für Nutzer gedacht."""


def _as_int(options, key, default):
    value = options.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise UsageError(f"'{key}' muss eine ganze Zahl sein.")
    try:
        return int(value)
    except ValueError:
        raise UsageError(f"'{key}' muss eine ganze Zahl sein.") from None


def options_to_argv(options):
    """Übersetzt UI-Optionen (Dict) in Kommandozeilen-Argumente."""
    mode = options.get("mode", "compare")
    if mode not in MODES:
        raise UsageError(f"Unbekannter Modus '{mode}'.")
    argv = []
    ignore = options.get("ignore") or []
    if not isinstance(ignore, list) or not all(isinstance(x, str) for x in ignore):
        raise UsageError("'ignore' muss eine Liste von Spaltennamen sein.")
    if ignore:
        argv.append("--ignore=" + ",".join(ignore))
    group = options.get("group")
    if isinstance(group, str) and group.strip():
        argv.append("--group=" + group)
    if options.get("hide_trash"):
        argv.append("--hide-trash")
    if options.get("detect_moves") is False:
        argv.append("--no-detect-moves")
    if options.get("keep_db_name"):
        argv.append("--keep-db-name")
    if options.get("show_secrets"):
        argv.append("--show-secrets")

    if mode == "search":
        query = options.get("search")
        if not isinstance(query, str) or not query.strip():
            raise UsageError("Für die Suche fehlt der Suchbegriff.")
        argv.append("--search=" + query)
    elif mode == "stats":
        argv.append("--stats")
    elif mode == "check":
        argv.append("--check")
    elif mode == "password-check":
        argv.append("--password-check")
        argv.append(f"--min-length={_as_int(options, 'min_length', 10)}")
        argv.append(f"--max-age-days={_as_int(options, 'max_age_days', 730)}")

    # Exporte zuletzt: die Optionen ohne Wert dürfen kein Argument verschlucken
    if options.get("export_added"):
        argv.append("--export-added")
    if options.get("export_merged"):
        argv.append("--export-merged")
    return argv


def analyze(old_name, old_text, new_name, new_text, options):
    """Vergleicht zwei CSV-Inhalte und gibt das Ergebnis als Dict zurück.

    Rückgabe: {"report", "status", "command", "exports"}; status 1 heißt „Suche ohne Treffer“.
    Wirft UsageError bei ungültigen Eingaben.
    """
    argv = options_to_argv(options)

    def fail(message):
        raise UsageError(message)

    parser = build_parser()
    parser.error = fail  # statt Programmabbruch eine Ausnahme auslösen
    args = parser.parse_args(["alt", "neu", *argv])
    ignored = validate_args(parser, args)

    try:
        src_old = read_text(old_text, old_name, keep_db_name=args.keep_db_name)
        src_new = read_text(new_text, new_name, keep_db_name=args.keep_db_name)
    except CsvError as e:
        raise UsageError(str(e)) from None
    old, new = filter_entries(parser, args, entries_from_rows(src_old.rows),
                              entries_from_rows(src_new.rows))

    n1, n2 = old_name, new_name
    if n1 == n2:  # gleicher Dateiname: im Bericht unterscheidbar machen
        n1, n2 = f"{old_name} (1)", f"{new_name} (2)"
    cmp = compare_files(old, new, n1, n2, ignored, detect_moves=not args.no_detect_moves,
                        src_old=src_old, src_new=src_new)
    base = base_report(cmp, old_name, new_name, args.hide_trash, args.group,
                       not args.no_detect_moves)
    report, status = build_report(args, cmp, base)

    exports = {}
    if args.export_added:
        rows, message = added_export(cmp)
        exports["added"] = {"filename": args.export_added, "csv": csv_text(rows),
                            "entries": len(rows),
                            "lines": [message.format(path=args.export_added).strip()]}
    if args.export_merged:
        rows, lines, conflicts = merged_export(cmp)
        exports["merged"] = {"filename": args.export_merged, "csv": csv_text(rows),
                             "entries": len(rows),
                             "lines": [ln.format(path=args.export_merged) for ln in lines],
                             "conflicts": [entry_ref(k) for k in conflicts]}

    command = shlex.join(["python3", "compare_csv.py", old_name, new_name, *argv])
    return {"report": report, "status": status, "command": command, "exports": exports}
