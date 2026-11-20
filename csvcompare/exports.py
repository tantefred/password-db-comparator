"""Exporte: die neu hinzugefügten und die zusammengeführten Einträge.

``prepare_added`` und ``prepare_merged`` wählen die Einträge aus und formulieren die Meldungen;
geschrieben wird erst anschließend (Terminal: in eine Datei, Weboberfläche: als Download).
"""

from dataclasses import dataclass, field

from .columns import MODIFIED
from .display import plural
from .duplicates import find_duplicates
from .entries import entry_label, is_trash
from .merge import KEEP_ONE, clean_entries
from .values import differing_columns, parse_time
from .writers import DEFAULT_WRITER, WRITERS, loss_lines, lost_data


@dataclass
class Export:
    rows: list  # die Einträge, wie sie geschrieben werden
    lines: list  # Meldungen, einschließlich dessen, was das Zielformat nicht speichert
    lost: dict  # {"columns": …, "source": …}, siehe ``writers.lost_data``
    writer: object  # das Zielformat, in dem die Einträge geschrieben werden
    conflicts: list = field(default_factory=list)  # Schlüssel mit unklarer Aktualität (nur Merge)


def merge_entries(cmp):
    """Vereinigt beide Dateien; bei Unterschieden gewinnt die jeweils neuere Version.

    Rückgabe: (zeilen, statistik, konflikte). Konflikte sind Einträge mit unterschiedlichem
    Inhalt, bei denen die Aktualität nicht bestimmbar ist (gleicher oder fehlender
    Zeitstempel); dort wird die Version aus der zweiten Datei genommen.
    """
    stats = {
        "only_old": len(cmp.only_old),
        "only_new": len(cmp.only_new),
        "newer_old": 0,
        "newer_new": 0,
        "same": 0,
    }
    rows, conflicts = [], []

    pairs = [(key, key) for key in sorted(set(cmp.old) & set(cmp.new))]
    pairs += [(move.old_key, move.new_key) for move in cmp.moves]
    for old_key, new_key in pairs:
        old_row, new_row = cmp.old[old_key], cmp.new[new_key]
        old_time, new_time = parse_time(old_row[MODIFIED]), parse_time(new_row[MODIFIED])
        if old_time and new_time and old_time > new_time:
            rows.append(old_row)
            stats["newer_old"] += 1
        elif old_time and new_time and new_time > old_time:
            rows.append(new_row)
            stats["newer_new"] += 1
        else:
            rows.append(new_row)
            if differing_columns(old_row, new_row, cmp.columns):
                conflicts.append(new_key)
            else:
                stats["same"] += 1
    rows += [cmp.old[key] for key in cmp.only_old]
    rows += [cmp.new[key] for key in cmp.only_new]

    rows.sort(key=lambda row: (row["Group"], row["Title"], row["Username"]))
    return rows, stats, conflicts


# Dateinamen, wenn bei --export-added/--export-merged kein Pfad angegeben ist
DEFAULT_NAMES = {"added": "neue_eintraege", "merged": "merged", "clean": "bereinigt"}


def pick_writer(format_id=None):
    """Der Writer zur Kennung (z. B. ``bitwarden-json``); ohne Angabe das KeePass-CSV."""
    return WRITERS[format_id or DEFAULT_WRITER.format]


def export_path(requested, kind, writer):
    """Zieldatei: der angegebene Pfad, sonst ein Standardname mit passender Endung."""
    return requested if isinstance(requested, str) else DEFAULT_NAMES[kind] + writer.extension


def db_prefix_for_export(cmp):
    """Datenbankname für Exporte: der aus der zweiten Datei, sonst der aus der ersten."""
    for source in (cmp.new_source, cmp.old_source):
        if source is not None and source.db_prefix:
            return source.db_prefix
    return None


def restore_db_prefix(rows, prefix):
    """Kopien der Zeilen mit vorangestelltem Datenbanknamen im Gruppenpfad (wie im Original)."""
    if not prefix:
        return list(rows)
    restored = []
    for row in rows:
        row = dict(row)
        row["Group"] = f"{prefix}/{row['Group']}" if row["Group"] else prefix
        restored.append(row)
    return restored


def prefix_rows(cmp, rows, writer):
    """Setzt bei Zielformaten, die das brauchen, den Datenbanknamen vor die Gruppenpfade."""
    return restore_db_prefix(rows, db_prefix_for_export(cmp) if writer.prefix_groups else None)


def with_losses(rows, lines, writer, **extra):
    """Hängt an die Meldungen an, was das Zielformat nicht speichern kann."""
    lost = lost_data(rows, writer)
    lines = lines + writer.notes(rows) + loss_lines(lost, writer)
    return Export(rows, lines, lost, writer, **extra)


def prepare_added(cmp, path, writer=DEFAULT_WRITER):
    """Die nur in der zweiten Datei vorhandenen Einträge (ohne Papierkorb)."""
    wanted = [cmp.new[key] for key in cmp.only_new if not is_trash(cmp.new[key])]
    rows = prefix_rows(cmp, wanted, writer)
    skipped = len(cmp.only_new) - len(rows)
    count = plural(len(rows), "neuer Eintrag", "neue Einträge")
    lines = [
        f"{count} nach '{path}' exportiert ({skipped} aus Papierkorb ausgelassen; "
        f"Datei enthält Passwörter im Klartext)."
    ]
    return with_losses(rows, lines, writer)


def prepare_merged(cmp, path, writer=DEFAULT_WRITER):
    """Alle Einträge beider Dateien; bei Unterschieden gewinnt die neuere Version."""
    merged, stats, conflicts = merge_entries(cmp)
    wanted = [row for row in merged if not is_trash(row)]
    rows = prefix_rows(cmp, wanted, writer)
    lines = [
        f"{plural(len(rows), 'Eintrag', 'Einträge')} nach '{path}' exportiert "
        f"({len(merged) - len(rows)} aus Papierkorb ausgelassen; "
        f"Datei enthält Passwörter im Klartext).",
        f"  nur in {cmp.old_name}: {stats['only_old']}, "
        f"nur in {cmp.new_name}: {stats['only_new']}, "
        f"neuere Version aus {cmp.old_name}: {stats['newer_old']}, "
        f"aus {cmp.new_name}: {stats['newer_new']}, unverändert: {stats['same']}",
    ]
    if conflicts:
        lines.append(
            f"  {len(conflicts)} Konflikt(e) mit unklarer Aktualität – "
            f"Version aus {cmp.new_name} übernommen, bitte prüfen:"
        )
        lines += [f"    ! {entry_label(key)}" for key in conflicts]
    return with_losses(rows, lines, writer, conflicts=conflicts)


def prepare_clean(
    cmp, path, writer=DEFAULT_WRITER, kinds=None, auto_kinds=("key",), decisions=None
):
    """Die Datei ohne Dubletten (nur eine Datei).

    Zusammengeführt wird nach ``decisions``; Gruppen ohne Entscheidung nur, wenn ihre Art in
    ``auto_kinds`` steht. Konflikte werden zugunsten des zuletzt geänderten Eintrags gelöst
    und in den Meldungen genannt.
    """
    groups = find_duplicates(cmp.old, kinds) if kinds else find_duplicates(cmp.old)
    cleaned = clean_entries(cmp.old, groups, decisions, auto_kinds)
    rows = prefix_rows(cmp, cleaned.rows, writer)
    lines = [
        f"{plural(len(rows), 'Eintrag', 'Einträge')} nach '{path}' exportiert "
        f"({plural(len(cleaned.merged), 'Gruppe', 'Gruppen')} bearbeitet, "
        f"{plural(cleaned.removed, 'Eintrag', 'Einträge')} entfernt, "
        f"{cleaned.trash} aus Papierkorb ausgelassen; Datei enthält Passwörter im Klartext)."
    ]
    conflicted = [merged for merged in cleaned.merged if merged.conflicts]
    if conflicted:
        lines.append(
            f"  {plural(len(conflicted), 'Konflikt', 'Konflikte')} – der zuletzt geänderte "
            f"Eintrag hat sich durchgesetzt (außer bei eigener Wahl), bitte prüfen:"
        )
        for merged in conflicted:
            first = merged.group.keys[0]
            lines.append(f"    ! {entry_label(first)}: {', '.join(merged.conflicts)}")
    kept_one = sum(1 for merged in cleaned.merged if merged.action == KEEP_ONE)
    if kept_one:
        lines.append(f"  {plural(kept_one, 'Gruppe', 'Gruppen')}: nur ein Eintrag behalten.")
    conflicts = [merged.group.keys[0] for merged in conflicted]
    return with_losses(rows, lines, writer, conflicts=conflicts)
