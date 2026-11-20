"""Textausgabe auf der Konsole."""

from .analysis import audit_entries, check_entries, stats_rows
from .columns import MODIFIED, SECRET_NAMES
from .compare import CERTAIN, FRESHNESS, LIKELY, NEWER_IN_NEW, NEWER_IN_OLD, UNCLEAR
from .display import display_value
from .entries import entry_label
from .importers import FORMAT_LABELS, KEEPASS_CSV
from .search import IDENTICAL, MOVED, ONLY_IN_NEW, ONLY_IN_OLD

CONFIDENCE_LABEL = {CERTAIN: "sicher", LIKELY: "wahrscheinlich"}


def freshness_titles(cmp):
    """Abschnittsüberschriften für geänderte Einträge, mit den echten Dateinamen."""
    old, new = cmp.old_name, cmp.new_name
    return {
        NEWER_IN_NEW: f"Geändert – {new} ist aktueller ({old} muss aktualisiert werden)",
        NEWER_IN_OLD: f"Geändert – {old} ist aktueller ({new} muss aktualisiert werden)",
        UNCLEAR: "Geändert – Aktualität unklar (manuell prüfen)",
    }


def print_change(cmp, change, show_secrets, header=None, indent="  "):
    """Gibt einen Eintrag mit seinen Unterschieden aus (``header`` ersetzt die Titelzeile)."""
    old_row, new_row = cmp.old[change.key], cmp.new[change.new_key]
    shown = [column for column in change.columns if column != MODIFIED]
    print(f"{indent}{header or '~ ' + entry_label(change.key)}")
    if not change.columns:
        print(f"{indent}    sonst keine Änderungen")
    else:
        kind = "nur Zeitstempel" if not shown else "Unterschiede in: " + ", ".join(shown)
        print(f"{indent}    {kind}  ({change.note})")
        print(f"{indent}    {MODIFIED}: {old_row[MODIFIED]}  |  {new_row[MODIFIED]}")
    for column in shown:
        secret = column in SECRET_NAMES
        old_text = display_value(old_row[column], secret, show_secrets)
        new_text = display_value(new_row[column], secret, show_secrets)
        if secret and not show_secrets:
            print(f"{indent}    {column}: geändert ({old_text} → {new_text})")
        else:
            print(f"{indent}    {column}: {old_text}  →  {new_text}")


def print_move(cmp, move, show_secrets, indent="  "):
    """Gibt ein erkanntes Paar aus verschobenem oder umbenanntem Eintrag aus."""
    header = (
        f"↷ {entry_label(move.old_key)}  →  {entry_label(move.new_key)}\n"
        f"{indent}    geändert in: {', '.join(move.key_columns)}  "
        f"[{CONFIDENCE_LABEL[move.confidence]}]"
    )
    print_change(cmp, cmp.move_change(move), show_secrets, header=header, indent=indent)


def print_findings(findings):
    """Gibt die Funde einer Prüfung aus (Überschrift, Anzahl, Zeilen)."""
    if not findings:
        print("  Keine Auffälligkeiten.")
    for finding in findings:
        print(f"  {finding.title}: {len(finding.lines)}")
        for line in finding.lines:
            print(f"    - {line}")


def print_header(cmp, args):
    """Kopfzeilen: Dateien, Anzahl der Einträge, Hinweise und aktive Filter."""
    for name, entries, source in cmp.sides:
        format_label = None
        if source and source.format != KEEPASS_CSV:
            format_label = FORMAT_LABELS[source.format]
        print(f"{name}: {len(entries)} Einträge" + (f" ({format_label})" if format_label else ""))
        for note in source.notes if source else []:
            print(f"  Hinweis: {note}")
    if cmp.ignored:
        print(f"Ignorierte Spalten: {', '.join(cmp.ignored)}")
    columns_by_reason = {}
    for column, reason in cmp.auto_ignored:
        columns_by_reason.setdefault(reason, []).append(column)
    for reason, columns in columns_by_reason.items():
        print(f"Automatisch ausgelassen ({reason}): {', '.join(columns)}")
    if args.hide_trash:
        print("Papierkorb-Gruppen ausgeblendet")
    if args.group is not None:
        print(f"Gruppenfilter: '{args.group.strip()}'")


def print_stats_single(cmp):
    """Anzahl der Einträge pro Gruppe für eine einzelne Datei."""
    rows = stats_rows(cmp.old, {})
    names = [group or "(ohne Gruppe)" for group, _, _ in rows]
    width = max([len(name) for name in names] + [len("Gesamt"), len("Gruppe")])
    width_count = max(len(cmp.old_name), 6)
    rule = "-" * (width + width_count + 2)
    print(f"{'Gruppe':<{width}}  {cmp.old_name:>{width_count}}")
    print(rule)
    for name, (_, count, _) in zip(names, rows, strict=True):
        print(f"{name:<{width}}  {count:>{width_count}}")
    print(rule)
    print(f"{'Gesamt':<{width}}  {len(cmp.old):>{width_count}}")


def print_stats(cmp):
    """Gibt die Anzahl der Einträge pro Gruppe für beide Dateien aus."""
    if cmp.single:
        return print_stats_single(cmp)
    rows = stats_rows(cmp.old, cmp.new)
    names = [group or "(ohne Gruppe)" for group, _, _ in rows]
    width = max([len(name) for name in names] + [len("Gesamt"), len("Gruppe")])
    width_old, width_new = max(len(cmp.old_name), 6), max(len(cmp.new_name), 6)
    rule = "-" * (width + width_old + width_new + 15)
    print(
        f"{'Gruppe':<{width}}  {cmp.old_name:>{width_old}}  {cmp.new_name:>{width_new}}  Differenz"
    )
    print(rule)
    for name, (_, count_old, count_new) in zip(names, rows, strict=True):
        print(
            f"{name:<{width}}  {count_old:>{width_old}}  {count_new:>{width_new}}  "
            f"{count_new - count_old:+d}"
        )
    print(rule)
    total_old, total_new = len(cmp.old), len(cmp.new)
    print(
        f"{'Gesamt':<{width}}  {total_old:>{width_old}}  {total_new:>{width_new}}  "
        f"{total_new - total_old:+d}"
    )


def print_check(cmp):
    """Gibt das Prüfergebnis beider Dateien aus."""
    for name, entries, _ in cmp.sides:
        print(f"=== {name} ===")
        print_findings(check_entries(entries))
        print()


def print_password_check(cmp, min_length, max_age_days):
    """Gibt die Passwortqualität beider Dateien aus."""
    for name, entries, _ in cmp.sides:
        print(f"=== {name} ===")
        findings, totp_count = audit_entries(entries, min_length, max_age_days)
        print_findings(findings)
        print(f"  TOTP: {totp_count} von {len(entries)} Einträgen haben TOTP eingerichtet\n")


def print_search(cmp, query, hits, show_secrets):
    """Gibt die Suchtreffer samt Status aus."""
    titles = freshness_titles(cmp)
    print(f"Suche nach '{query}': {len(hits)} Treffer\n")
    for hit in hits:
        if hit.status == MOVED:
            print("  Status: verschoben/umbenannt")
            print_move(cmp, hit.item, show_secrets)
        elif hit.status == ONLY_IN_OLD:
            print(f"  - {entry_label(hit.item)}")
            print(f"      Status: nur in {cmp.old_name} (in {cmp.new_name} nicht vorhanden)")
            print(f"      {MODIFIED}: {cmp.old[hit.item][MODIFIED]}")
        elif hit.status == ONLY_IN_NEW:
            print(f"  + {entry_label(hit.item)}")
            print(f"      Status: nur in {cmp.new_name} (in {cmp.old_name} nicht vorhanden)")
            print(f"      {MODIFIED}: {cmp.new[hit.item][MODIFIED]}")
        elif hit.status == IDENTICAL:
            print(f"  = {entry_label(hit.item)}")
            print("      Status: identisch in beiden Dateien")
            print(f"      {MODIFIED}: {cmp.old[hit.item][MODIFIED]}")
        else:
            print(f"  Status: {titles[hit.status]}")
            print_change(cmp, hit.item, show_secrets)
        print()


def print_compare(cmp, show_secrets):
    """Gibt die Abschnitte des Vergleichs aus (verschoben, nur in einer Datei, geändert)."""
    if cmp.moves:
        print(f"== Verschoben/umbenannt: {len(cmp.moves)} ==")
        for move in cmp.moves:
            print_move(cmp, move, show_secrets)
        print()
    if cmp.only_old:
        print(
            f"== Nur in {cmp.old_name} (in {cmp.new_name} nicht vorhanden): {len(cmp.only_old)} =="
        )
        for key in cmp.only_old:
            print(f"  - {entry_label(key)}")
        print()
    if cmp.only_new:
        print(
            f"== Nur in {cmp.new_name} (in {cmp.old_name} nicht vorhanden): {len(cmp.only_new)} =="
        )
        for key in cmp.only_new:
            print(f"  + {entry_label(key)}")
        print()

    titles = freshness_titles(cmp)
    for freshness in FRESHNESS:
        changes = cmp.changes[freshness]
        if not changes:
            continue
        print(f"== {titles[freshness]}: {len(changes)} ==")
        for change in changes:
            print_change(cmp, change, show_secrets)
        print()


def print_summary(cmp):
    """Schlusszeile des Vergleichs."""
    if cmp.identical:
        print("Keine Unterschiede.")
        return
    count = {freshness: len(cmp.changes[freshness]) for freshness in FRESHNESS}
    print(
        f"Zusammenfassung: {len(cmp.only_old)} nur in {cmp.old_name}, "
        f"{len(cmp.only_new)} nur in {cmp.new_name}, "
        f"{len(cmp.moves)} verschoben/umbenannt, "
        f"{cmp.n_changed} geändert "
        f"({count[NEWER_IN_NEW]} in {cmp.old_name} zu aktualisieren, "
        f"{count[NEWER_IN_OLD]} in {cmp.new_name} zu aktualisieren, "
        f"{count[UNCLEAR]} manuell prüfen)."
    )
