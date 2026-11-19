"""CSV-Exporte: neu hinzugefügte und zusammengeführte Einträge."""

from .columns import MODIFIED
from .entries import entry_label, is_trash
from .values import differing_columns, parse_time
from .writers import DEFAULT_WRITER, loss_lines, lost_data


def build_merged(cmp):
    """Vereinigt beide Dateien; bei Unterschieden gewinnt die jeweils neuere Version.

    Rückgabe: (zeilen, statistik, konflikte). Konflikte sind Einträge mit unterschiedlichem
    Inhalt, bei denen die Aktualität nicht bestimmbar ist (gleicher oder fehlender
    Zeitstempel); dort wird die Version aus der zweiten Datei genommen.
    """
    stats = {"nur_alt": 0, "nur_neu": 0, "alt_neuer": 0, "neu_neuer": 0, "gleich": 0}
    conflicts, rows = [], []

    pairs = [(key, key) for key in sorted(set(cmp.old) & set(cmp.new))]
    pairs += [(move.old_key, move.new_key) for move in cmp.moves]
    for old_key, new_key in pairs:
        old_row, new_row = cmp.old[old_key], cmp.new[new_key]
        old_time, new_time = parse_time(old_row[MODIFIED]), parse_time(new_row[MODIFIED])
        if old_time and new_time and old_time > new_time:
            rows.append(old_row)
            stats["alt_neuer"] += 1
        elif old_time and new_time and new_time > old_time:
            rows.append(new_row)
            stats["neu_neuer"] += 1
        else:
            rows.append(new_row)
            if differing_columns(old_row, new_row, cmp.columns):
                conflicts.append(new_key)
            else:
                stats["gleich"] += 1
    rows += [cmp.old[key] for key in cmp.only_old]
    stats["nur_alt"] = len(cmp.only_old)
    rows += [cmp.new[key] for key in cmp.only_new]
    stats["nur_neu"] = len(cmp.only_new)

    rows.sort(key=lambda row: (row["Group"], row["Title"], row["Username"]))
    return rows, stats, conflicts


def restore_db_prefix(rows, prefix):
    """Kopien der Zeilen mit vorangestelltem Datenbanknamen im Gruppenpfad (wie im Original)."""
    if not prefix:
        return list(rows)
    out = []
    for row in rows:
        row = dict(row)
        row["Group"] = f"{prefix}/{row['Group']}" if row["Group"] else prefix
        out.append(row)
    return out


def export_prefix(cmp):
    """Datenbankname für Exporte: der aus der zweiten Datei, sonst der aus der ersten."""
    for source in (cmp.new_source, cmp.old_source):
        if source is not None and source.db_prefix:
            return source.db_prefix
    return None


def added_export(cmp):
    """Nur in der zweiten Datei vorhandene Einträge (ohne Papierkorb).

    Rückgabe: (zeilen, meldung); in der Meldung steht {path} für den Zielpfad.
    """
    rows = restore_db_prefix([cmp.new[key] for key in cmp.only_new if not is_trash(cmp.new[key])],
                             export_prefix(cmp))
    skipped = len(cmp.only_new) - len(rows)
    n = len(rows)
    message = (f"{'1 neuer Eintrag' if n == 1 else f'{n} neue Einträge'} nach '{{path}}' exportiert "
               f"({skipped} aus Papierkorb ausgelassen; Datei enthält Passwörter im Klartext).\n")
    return rows, message


def merged_export(cmp):
    """Alle Einträge beider Dateien; bei Unterschieden gewinnt die neuere Version.

    Rückgabe: (zeilen, meldung, konflikte); in der Meldung steht {path} für den Zielpfad.
    """
    rows, stats, conflicts = build_merged(cmp)
    export = restore_db_prefix([r for r in rows if not is_trash(r)], export_prefix(cmp))
    lines = [
        f"{'1 Eintrag' if len(export) == 1 else f'{len(export)} Einträge'} nach '{{path}}' exportiert "
        f"({len(rows) - len(export)} aus Papierkorb ausgelassen; "
        f"Datei enthält Passwörter im Klartext).",
        f"  nur in {cmp.old_name}: {stats['nur_alt']}, nur in {cmp.new_name}: {stats['nur_neu']}, "
        f"neuere Version aus {cmp.old_name}: {stats['alt_neuer']}, "
        f"aus {cmp.new_name}: {stats['neu_neuer']}, unverändert: {stats['gleich']}",
    ]
    if conflicts:
        lines.append(f"  {len(conflicts)} Konflikt(e) mit unklarer Aktualität – "
                     f"Version aus {cmp.new_name} übernommen, bitte prüfen:")
        lines += [f"    ! {entry_label(k)}" for k in conflicts]
    return export, lines, conflicts


def loss_report(rows, writer=DEFAULT_WRITER):
    """Was das Zielformat bei diesen Einträgen nicht speichern kann: (zeilen, daten)."""
    lost = lost_data(rows, writer)
    return loss_lines(lost, writer), lost


def export_added(cmp, path, log, writer=DEFAULT_WRITER):
    """Schreibt die nur in der zweiten Datei vorhandenen Einträge in eine Datei."""
    rows, message = added_export(cmp)
    writer.write(path, rows)
    log(message.format(path=path).rstrip("\n"))
    for line in loss_report(rows, writer)[0]:
        log(line)
    log()


def export_merged(cmp, path, log, writer=DEFAULT_WRITER):
    """Schreibt die zusammengeführten Einträge in eine Datei."""
    rows, lines, _ = merged_export(cmp)
    writer.write(path, rows)
    for line in lines + loss_report(rows, writer)[0]:
        log(line.format(path=path))
    log()
