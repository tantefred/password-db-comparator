"""Auswertung ohne Dateipfade: CSV-Texte und Optionen hinein, Bericht und Exporte heraus.

Wird von der Weboberfläche genutzt. Optionen werden in genau die Kommandozeilen-Argumente
übersetzt und vom selben Parser geprüft wie im Terminal, damit beide Wege gleich
funktionieren.
"""

import shlex

from .cli import build_parser, filter_entries, validate_args
from .compare import compare_files
from .entries import entries_from_rows
from .exports import added_export, loss_report, merged_export
from .importers import CsvError, load_any
from .render_json import build_report, entry_ref
from .writers import DEFAULT_WRITER


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
    args.alt, args.neu = old_name, new_name  # im Bericht als Pfade ausgewiesen
    ignored = validate_args(parser, args)

    try:
        src_old = load_any(old_name, old_text, keep_db_name=args.keep_db_name)
        src_new = load_any(new_name, new_text, keep_db_name=args.keep_db_name)
    except CsvError as e:
        raise UsageError(str(e)) from None
    old, new = filter_entries(parser, args, entries_from_rows(src_old.rows),
                              entries_from_rows(src_new.rows))

    shown_old, shown_new = old_name, new_name
    if shown_old == shown_new:  # gleicher Dateiname: im Bericht unterscheidbar machen
        shown_old, shown_new = f"{old_name} (1)", f"{new_name} (2)"
    cmp = compare_files(old, new, shown_old, shown_new, ignored,
                        detect_moves=not args.no_detect_moves,
                        old_source=src_old, new_source=src_new)
    report, status = build_report(args, cmp)

    exports = {}
    if args.export_added:
        rows, message = added_export(cmp)
        loss_lines, lost = loss_report(rows)
        exports["added"] = {"filename": args.export_added, "csv": DEFAULT_WRITER.text(rows),
                            "entries": len(rows),
                            "lines": [message.format(path=args.export_added).strip()] + loss_lines,
                            "lost": lost, "target": DEFAULT_WRITER.label}
    if args.export_merged:
        rows, lines, conflicts = merged_export(cmp)
        loss_lines, lost = loss_report(rows)
        exports["merged"] = {"filename": args.export_merged, "csv": DEFAULT_WRITER.text(rows),
                             "entries": len(rows),
                             "lines": [ln.format(path=args.export_merged)
                                       for ln in lines + loss_lines],
                             "conflicts": [entry_ref(k) for k in conflicts],
                             "lost": lost, "target": DEFAULT_WRITER.label}

    command = shlex.join(["python3", "compare_csv.py", old_name, new_name, *argv])
    return {"report": report, "status": status, "command": command, "exports": exports}
