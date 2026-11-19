"""Auswertung ohne Dateipfade: CSV-Texte und Optionen hinein, Bericht und Exporte heraus.

Wird von der Weboberfläche genutzt. Optionen werden in genau die Kommandozeilen-Argumente
übersetzt und vom selben Parser geprüft wie im Terminal, damit beide Wege gleich
funktionieren.
"""

import shlex

from .cli import build_comparison, build_parser, validate_args
from .exports import prepare_added, prepare_merged
from .importers import CsvError, load_any
from .render_json import build_report, entry_ref

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


def filter_arguments(options):
    """Argumente für Filter, Spalten und Anzeige."""
    ignore = options.get("ignore") or []
    if not isinstance(ignore, list) or not all(isinstance(name, str) for name in ignore):
        raise UsageError("'ignore' muss eine Liste von Spaltennamen sein.")
    argv = []
    if ignore:
        argv.append("--ignore=" + ",".join(ignore))
    group = options.get("group")
    if isinstance(group, str) and group.strip():
        argv.append("--group=" + group)
    for key, flag in (
        ("hide_trash", "--hide-trash"),
        ("keep_db_name", "--keep-db-name"),
        ("show_secrets", "--show-secrets"),
    ):
        if options.get(key):
            argv.append(flag)
    if options.get("detect_moves") is False:
        argv.append("--no-detect-moves")
    return argv


def mode_arguments(options, mode):
    """Argumente für den gewählten Auswertungsmodus."""
    if mode == "search":
        query = options.get("search")
        if not isinstance(query, str) or not query.strip():
            raise UsageError("Für die Suche fehlt der Suchbegriff.")
        return ["--search=" + query]
    if mode == "password-check":
        return [
            "--password-check",
            f"--min-length={_as_int(options, 'min_length', 10)}",
            f"--max-age-days={_as_int(options, 'max_age_days', 730)}",
        ]
    return {"stats": ["--stats"], "check": ["--check"]}.get(mode, [])


def export_arguments(options):
    """Exporte kommen zuletzt: ihre Optionen ohne Wert dürfen kein Argument verschlucken."""
    return [
        flag
        for key, flag in (("export_added", "--export-added"), ("export_merged", "--export-merged"))
        if options.get(key)
    ]


def options_to_argv(options):
    """Übersetzt UI-Optionen (Dict) in Kommandozeilen-Argumente."""
    mode = options.get("mode", "compare")
    if mode not in MODES:
        raise UsageError(f"Unbekannter Modus '{mode}'.")
    return filter_arguments(options) + mode_arguments(options, mode) + export_arguments(options)


def export_payload(export, filename):
    """Ein Export als Antwort für die Weboberfläche (der Inhalt wird dort zum Download)."""
    return {
        "filename": filename,
        "content": export.writer.text(export.rows),
        "mime": export.writer.mime,
        "entries": len(export.rows),
        "lines": export.lines,
        "lost": export.lost,
        "target": export.writer.label,
        "conflicts": [entry_ref(key) for key in export.conflicts],
    }


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
        old_source = load_any(old_name, old_text, keep_db_name=args.keep_db_name)
        new_source = load_any(new_name, new_text, keep_db_name=args.keep_db_name)
    except CsvError as e:
        raise UsageError(str(e)) from None

    shown_old, shown_new = old_name, new_name
    if shown_old == shown_new:  # gleicher Dateiname: im Bericht unterscheidbar machen
        shown_old, shown_new = f"{old_name} (1)", f"{new_name} (2)"
    cmp = build_comparison(parser, args, ignored, old_source, new_source, shown_old, shown_new)
    report, status = build_report(args, cmp)

    exports = {}
    if args.export_added:
        exports["added"] = export_payload(prepare_added(cmp, args.export_added), args.export_added)
    if args.export_merged:
        exports["merged"] = export_payload(
            prepare_merged(cmp, args.export_merged), args.export_merged
        )

    command = shlex.join(["python3", "compare_csv.py", old_name, new_name, *argv])
    return {"report": report, "status": status, "command": command, "exports": exports}
