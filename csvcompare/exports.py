"""CSV-Exporte: neu hinzugefügte und zusammengeführte Einträge."""

from .compare import build_merged
from .entries import entry_label, is_trash
from .writers import DEFAULT_WRITER, loss_lines, lost_data


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
    for src in (cmp.src_new, cmp.src_old):
        if src is not None and src.db_prefix:
            return src.db_prefix
    return None


def added_export(cmp):
    """Nur in der zweiten Datei vorhandene Einträge (ohne Papierkorb).

    Rückgabe: (zeilen, meldung); in der Meldung steht {path} für den Zielpfad.
    """
    rows = restore_db_prefix([cmp.new[k] for k in cmp.added if not is_trash(cmp.new[k])],
                             export_prefix(cmp))
    skipped = len(cmp.added) - len(rows)
    n = len(rows)
    message = (f"{'1 neuer Eintrag' if n == 1 else f'{n} neue Einträge'} nach '{{path}}' exportiert "
               f"({skipped} aus Papierkorb ausgelassen; Datei enthält Passwörter im Klartext).\n")
    return rows, message


def merged_export(cmp):
    """Alle Einträge beider Dateien; bei Unterschieden gewinnt die neuere Version.

    Rückgabe: (zeilen, meldung, konflikte); in der Meldung steht {path} für den Zielpfad.
    """
    rows, stats, conflicts = build_merged(cmp.old, cmp.new, cmp.removed, cmp.added,
                                          cmp.moves, cmp.compare_cols)
    export = restore_db_prefix([r for r in rows if not is_trash(r)], export_prefix(cmp))
    lines = [
        f"{'1 Eintrag' if len(export) == 1 else f'{len(export)} Einträge'} nach '{{path}}' exportiert "
        f"({len(rows) - len(export)} aus Papierkorb ausgelassen; "
        f"Datei enthält Passwörter im Klartext).",
        f"  nur in {cmp.n1}: {stats['nur_alt']}, nur in {cmp.n2}: {stats['nur_neu']}, "
        f"neuere Version aus {cmp.n1}: {stats['alt_neuer']}, "
        f"aus {cmp.n2}: {stats['neu_neuer']}, unverändert: {stats['gleich']}",
    ]
    if conflicts:
        lines.append(f"  {len(conflicts)} Konflikt(e) mit unklarer Aktualität – "
                     f"Version aus {cmp.n2} übernommen, bitte prüfen:")
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
