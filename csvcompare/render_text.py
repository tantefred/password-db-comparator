"""Textausgabe auf der Konsole."""

from datetime import datetime, timezone

from .analysis import audit_entries, check_entries, stats_rows
from .columns import KEY_NAMES, MODIFIED, SECRET_NAMES
from .compare import classify
from .display import display_value
from .entries import entry_label
from .importers import FORMAT_LABELS, KEEPASS_CSV
from .values import differing_columns


def print_changed(k, diffs, delta, old, new, show_secrets, indent="  ",
                  new_k=None, header=None):
    """Gibt einen geänderten Eintrag mit Unterschieden aus.

    new_k: Key des Eintrags in der zweiten Datei, falls er sich von k unterscheidet.
    """
    nk = new_k or k
    names = [c for c in diffs if c != MODIFIED]
    print(f"{indent}{header or '~ ' + entry_label(k)}")
    if not diffs:
        print(f"{indent}    sonst keine Änderungen")
    else:
        kind = "nur Zeitstempel" if not names else "Unterschiede in: " + ", ".join(names)
        print(f"{indent}    {kind}  ({delta})")
        print(f"{indent}    Last Modified: {old[k][MODIFIED]}  |  {new[nk][MODIFIED]}")
    for c in names:
        secret = c in SECRET_NAMES
        a = display_value(old[k][c], secret, show_secrets)
        b = display_value(new[nk][c], secret, show_secrets)
        if secret and not show_secrets:
            print(f"{indent}    {c}: geändert ({a} → {b})")
        else:
            print(f"{indent}    {c}: {a}  →  {b}")


def print_move(move, compare_cols, old, new, n1, n2, show_secrets, indent="  "):
    """Gibt ein erkanntes Paar aus verschobenem/umbenanntem Eintrag aus."""
    ok, nk, confidence = move
    key_changes = [c for c, a, b in zip(KEY_NAMES, ok, nk) if a != b]
    diffs = differing_columns(old[ok], new[nk], compare_cols)
    _, delta = classify(ok, old, new, n1, n2, new_key=nk)
    header = (f"↷ {entry_label(ok)}  →  {entry_label(nk)}\n"
              f"{indent}    geändert in: {', '.join(key_changes)}  [{confidence}]")
    print_changed(ok, diffs, delta, old, new, show_secrets, indent=indent,
                  new_k=nk, header=header)


def print_stats(old, new, n1, n2):
    """Gibt die Anzahl der Einträge pro Gruppe für beide Dateien aus."""
    rows = stats_rows(old, new)
    names = [g or "(ohne Gruppe)" for g, _, _ in rows]
    w = max([len(x) for x in names] + [len("Gesamt"), len("Gruppe")])
    w1, w2 = max(len(n1), 6), max(len(n2), 6)
    print(f"{'Gruppe':<{w}}  {n1:>{w1}}  {n2:>{w2}}  Differenz")
    print("-" * (w + w1 + w2 + 15))
    for name, (_, a, b) in zip(names, rows):
        print(f"{name:<{w}}  {a:>{w1}}  {b:>{w2}}  {b - a:+d}")
    print("-" * (w + w1 + w2 + 15))
    a, b = len(old), len(new)
    print(f"{'Gesamt':<{w}}  {a:>{w1}}  {b:>{w2}}  {b - a:+d}")


def print_check(old, new, n1, n2):
    """Gibt das Prüfergebnis beider Dateien aus."""
    for name, entries in ((n1, old), (n2, new)):
        print(f"=== {name} ===")
        findings = check_entries(entries)
        if not findings:
            print("  Keine Auffälligkeiten.\n")
            continue
        for title, lines in findings:
            print(f"  {title}: {len(lines)}")
            for line in lines:
                print(f"    - {line}")
        print()


def print_password_check(old, new, n1, n2, min_length, max_age_days):
    """Gibt die Passwortqualität beider Dateien aus."""
    now = datetime.now(timezone.utc)
    for name, entries in ((n1, old), (n2, new)):
        print(f"=== {name} ===")
        findings, totp = audit_entries(entries, min_length, max_age_days, now)
        if not findings:
            print("  Keine Auffälligkeiten.")
        for title, lines in findings:
            print(f"  {title}: {len(lines)}")
            for line in lines:
                print(f"    - {line}")
        print(f"  TOTP: {totp} von {len(entries)} Einträgen haben TOTP eingerichtet\n")


def group_titles(n1, n2):
    """Abschnittsüberschriften für geänderte Einträge, mit den echten Dateinamen."""
    return {
        "old_outdated": f"Geändert – {n2} ist aktueller ({n1} muss aktualisiert werden)",
        "new_outdated": f"Geändert – {n1} ist aktueller ({n2} muss aktualisiert werden)",
        "unclear": "Geändert – Aktualität unklar (manuell prüfen)",
    }


def print_header(cmp, hide_trash, group):
    """Kopfzeilen: Dateien, Anzahl der Einträge und aktive Filter."""
    for name, entries, src in ((cmp.n1, cmp.old, cmp.src_old), (cmp.n2, cmp.new, cmp.src_new)):
        fmt = FORMAT_LABELS.get(src.format) if src and src.format != KEEPASS_CSV else None
        print(f"{name}: {len(entries)} Einträge" + (f" ({fmt})" if fmt else ""))
        for note in (src.notes if src else []):
            print(f"  Hinweis: {note}")
    if cmp.ignored:
        print(f"Ignorierte Spalten: {', '.join(cmp.ignored)}")
    by_reason = {}
    for col, reason in (cmp.auto_ignored or []):
        by_reason.setdefault(reason, []).append(col)
    for reason, cols in by_reason.items():
        print(f"Automatisch ausgelassen ({reason}): {', '.join(cols)}")
    if hide_trash:
        print("Papierkorb-Gruppen ausgeblendet")
    if group is not None:
        print(f"Gruppenfilter: '{group.strip()}'")


def print_search(query, n_matches, results, cmp, show_secrets):
    """Gibt die Suchtreffer samt Status aus."""
    n1, n2, old, new = cmp.n1, cmp.n2, cmp.old, cmp.new
    titles = group_titles(n1, n2)
    print(f"Suche nach '{query}': {n_matches} Treffer\n")
    for kind, data in results:
        if kind == "moved":
            print(f"  Status: verschoben/umbenannt")
            print_move(data, cmp.compare_cols, old, new, n1, n2, show_secrets)
        elif kind == "only_old":
            print(f"  - {entry_label(data)}")
            print(f"      Status: nur in {n1} (in {n2} nicht vorhanden)")
            print(f"      Last Modified: {old[data][MODIFIED]}")
        elif kind == "only_new":
            print(f"  + {entry_label(data)}")
            print(f"      Status: nur in {n2} (in {n1} nicht vorhanden)")
            print(f"      Last Modified: {new[data][MODIFIED]}")
        elif kind == "changed":
            k, grp, diffs, delta = data
            print(f"  Status: {titles[grp]}")
            print_changed(k, diffs, delta, old, new, show_secrets)
        else:
            print(f"  = {entry_label(data)}")
            print(f"      Status: identisch in beiden Dateien")
            print(f"      Last Modified: {old[data][MODIFIED]}")
        print()


def print_compare(cmp, show_secrets):
    """Gibt die Abschnitte des Vergleichs aus (verschoben, nur in einer Datei, geändert)."""
    n1, n2, old, new = cmp.n1, cmp.n2, cmp.old, cmp.new
    titles = group_titles(n1, n2)
    if cmp.moves:
        print(f"== Verschoben/umbenannt: {len(cmp.moves)} ==")
        for move in cmp.moves:
            print_move(move, cmp.compare_cols, old, new, n1, n2, show_secrets)
        print()
    if cmp.removed:
        print(f"== Nur in {n1} (in {n2} nicht vorhanden): {len(cmp.removed)} ==")
        for k in cmp.removed:
            print(f"  - {entry_label(k)}")
        print()
    if cmp.added:
        print(f"== Nur in {n2} (in {n1} nicht vorhanden): {len(cmp.added)} ==")
        for k in cmp.added:
            print(f"  + {entry_label(k)}")
        print()

    for grp in ("old_outdated", "new_outdated", "unclear"):
        items = cmp.groups[grp]
        if not items:
            continue
        print(f"== {titles[grp]}: {len(items)} ==")
        for k, diffs, delta in items:
            print_changed(k, diffs, delta, old, new, show_secrets)
        print()


def print_summary(cmp):
    """Schlusszeile des Vergleichs."""
    if cmp.identical:
        print("Keine Unterschiede.")
        return
    g = cmp.groups
    print(f"Zusammenfassung: {len(cmp.removed)} nur in {cmp.n1}, {len(cmp.added)} nur in {cmp.n2}, "
          f"{len(cmp.moves)} verschoben/umbenannt, "
          f"{cmp.n_changed} geändert "
          f"({len(g['old_outdated'])} in {cmp.n1} zu aktualisieren, "
          f"{len(g['new_outdated'])} in {cmp.n2} zu aktualisieren, "
          f"{len(g['unclear'])} manuell prüfen).")
