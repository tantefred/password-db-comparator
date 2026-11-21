"""Auswertung ohne Dateipfade: CSV-Texte und Optionen hinein, Bericht und Exporte heraus.

Wird von der Weboberfläche genutzt. Optionen werden in genau die Kommandozeilen-Argumente
übersetzt und vom selben Parser geprüft wie im Terminal, damit beide Wege gleich
funktionieren.
"""

import shlex

from .cli import build_comparison, build_parser, validate_args
from .exports import export_path, pick_writer, prepare_added, prepare_clean, prepare_merged
from .importers import CsvError, load_any
from .merge import Decision
from .modes import CLEAN, COMPARE, DEDUPE, OVERVIEW, PASSWORD_CHECK, SEARCH, UI_MODES
from .render_json import build_report, entry_ref
from .writers import WRITERS


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
    if mode == SEARCH:
        query = options.get("search")
        if not isinstance(query, str) or not query.strip():
            raise UsageError("Für die Suche fehlt der Suchbegriff.")
        return ["--search=" + query]
    if mode in (DEDUPE, CLEAN):
        return ["--dedupe"]  # „Bereinigen“ beginnt mit der Liste der Dublettengruppen
    if mode in (PASSWORD_CHECK, OVERVIEW):
        return [
            "--password-check" if mode == PASSWORD_CHECK else "--overview",
            f"--min-length={_as_int(options, 'min_length', 10)}",
            f"--max-age-days={_as_int(options, 'max_age_days', 730)}",
        ]
    return {"stats": ["--stats"], "check": ["--check"]}.get(mode, [])


def export_arguments(options):
    """Exporte kommen zuletzt: ihre Optionen ohne Wert dürfen kein Argument verschlucken."""
    flags = [
        flag
        for key, flag in (("export_added", "--export-added"), ("export_merged", "--export-merged"))
        if options.get(key)
    ]
    export_format = options.get("export_format")
    if flags and export_format:
        flags.insert(0, f"--export-format={export_format}")
    return flags


def options_to_argv(options, single=False):
    """Übersetzt UI-Optionen (Dict) in Kommandozeilen-Argumente.

    ``single``: Es liegt nur eine Datei vor; ohne Modus gilt dann der Überblick.
    """
    mode = options.get("mode") or (OVERVIEW if single else COMPARE)
    if mode not in UI_MODES:
        raise UsageError(f"Unbekannter Modus '{mode}'.")
    if single and mode == COMPARE:
        raise UsageError("Der Vergleich braucht zwei Dateien.")
    return filter_arguments(options) + mode_arguments(options, mode) + export_arguments(options)


def is_count(value, limit):
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value < limit


def parse_decisions(options):
    """Die Entscheidungen der Oberfläche als ``{gruppen_id: Decision}``; prüft nur die Form."""
    raw = options.get("decisions")
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise UsageError("'decisions' muss ein Objekt sein.")
    decisions = {}
    for group_id, item in raw.items():
        if not isinstance(item, dict) or not isinstance(item.get("action"), str):
            raise UsageError("Ungültige Entscheidung.")
        keep, picks = item.get("keep", 0), item.get("picks") or {}
        if not is_count(keep, 10**6) or not isinstance(picks, dict):
            raise UsageError("Ungültige Entscheidung.")
        decisions[group_id] = Decision(item["action"], keep, picks)
    return decisions


def clean_export(cmp, args, options):
    """Die bereinigte Datei nach den Entscheidungen der Oberfläche (als Antwort-Inhalt)."""
    export_format = options.get("export_format")
    if export_format is not None and export_format not in WRITERS:
        raise UsageError(f"Unbekanntes Exportformat '{export_format}'.")
    writer = pick_writer(export_format)
    path = export_path(True, "clean", writer)
    try:
        export = prepare_clean(
            cmp,
            path,
            writer,
            kinds=args.dedupe_kinds,
            auto_kinds=(),
            decisions=parse_decisions(options),
        )
    except ValueError as e:
        raise UsageError(str(e)) from None
    return export_payload(export, path)


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
    """Wertet einen oder zwei Dateiinhalte aus und gibt das Ergebnis als Dict zurück.

    Ohne zweite Datei (``new_name=None``) gibt es keinen Vergleich, sondern die Auswertung der
    ersten (Überblick, Statistik, Prüfung, Passwörter, Suche).

    Rückgabe: {"report", "status", "command", "exports"}; status 1 heißt „Suche ohne Treffer“.
    Wirft UsageError bei ungültigen Eingaben.
    """
    single = new_name is None
    argv = options_to_argv(options, single=single)

    def fail(message):
        raise UsageError(message)

    parser = build_parser()
    parser.error = fail  # statt Programmabbruch eine Ausnahme auslösen
    args = parser.parse_args(["alt"] + ([] if single else ["neu"]) + argv)
    args.alt, args.neu = old_name, new_name  # im Bericht als Pfade ausgewiesen
    ignored = validate_args(parser, args)

    try:
        old_source = load_any(old_name, old_text, keep_db_name=args.keep_db_name)
        new_source = (
            None if single else load_any(new_name, new_text, keep_db_name=args.keep_db_name)
        )
    except CsvError as e:
        raise UsageError(str(e)) from None

    shown_old, shown_new = old_name, new_name
    if (
        not single and shown_old == shown_new
    ):  # gleicher Dateiname: im Bericht unterscheidbar machen
        shown_old, shown_new = f"{old_name} (1)", f"{new_name} (2)"
    cmp = build_comparison(parser, args, ignored, old_source, new_source, shown_old, shown_new)
    report, status = build_report(args, cmp)

    exports = {}
    writer = pick_writer(args.export_format)
    for value, kind, prepare in (
        (args.export_added, "added", prepare_added),
        (args.export_merged, "merged", prepare_merged),
    ):
        if value:
            path = export_path(value, kind, writer)
            exports[kind] = export_payload(prepare(cmp, path, writer), path)

    if options.get("export_clean"):
        if not (single and args.dedupe):
            raise UsageError("Bereinigen braucht genau eine Datei und den Modus „Bereinigen“.")
        exports["clean"] = clean_export(cmp, args, options)

    files = [old_name] if single else [old_name, new_name]
    command = shlex.join(["python3", "compare_csv.py", *files, *argv])
    return {"report": report, "status": status, "command": command, "exports": exports}
