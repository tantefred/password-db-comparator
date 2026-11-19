"""CSV-Exporte: neu hinzugefügte und zusammengeführte Einträge."""

from .common import is_excluded, label
from .compare import build_merged
from .csvio import write_csv


def export_added(cmp, path, log):
    """Schreibt die nur in der zweiten Datei vorhandenen Einträge (ohne Papierkorb)."""
    export = [k for k in cmp.added if not is_excluded(cmp.new[k])]
    skipped = len(cmp.added) - len(export)
    write_csv(path, [cmp.new[k] for k in export])
    log(f"{len(export)} neue Einträge nach '{path}' exportiert "
        f"({skipped} aus Papierkorb ausgelassen; Datei enthält Passwörter im Klartext).\n")


def export_merged(cmp, path, log):
    """Schreibt alle Einträge beider Dateien; bei Unterschieden gewinnt die neuere Version."""
    rows, stats, conflicts = build_merged(cmp.old, cmp.new, cmp.removed, cmp.added,
                                          cmp.moves, cmp.compare_cols)
    export = [r for r in rows if not is_excluded(r)]
    write_csv(path, export)
    log(f"{len(export)} Einträge nach '{path}' exportiert "
        f"({len(rows) - len(export)} aus Papierkorb ausgelassen; "
        f"Datei enthält Passwörter im Klartext).")
    log(f"  nur in {cmp.n1}: {stats['nur_alt']}, nur in {cmp.n2}: {stats['nur_neu']}, "
        f"neuere Version aus {cmp.n1}: {stats['alt_neuer']}, "
        f"aus {cmp.n2}: {stats['neu_neuer']}, unverändert: {stats['gleich']}")
    if conflicts:
        log(f"  {len(conflicts)} Konflikt(e) mit unklarer Aktualität – "
            f"Version aus {cmp.n2} übernommen, bitte prüfen:")
        for k in conflicts:
            log(f"    ! {label(k)}")
    log()
