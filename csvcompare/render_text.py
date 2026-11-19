"""Textausgabe auf der Konsole."""

from datetime import datetime, timezone

from .analysis import audit_entries, check_entries, stats_rows
from .common import label, short
from .compare import classify
from .constants import KEY_COLS, SECRET_COLS, TIME_COL


def print_changed(k, diffs, delta, old, new, show_secrets, indent="  ",
                  new_k=None, header=None):
    """Gibt einen geänderten Eintrag mit Unterschieden aus.

    new_k: Key des Eintrags in der zweiten Datei, falls er sich von k unterscheidet.
    """
    nk = new_k or k
    names = [c for c in diffs if c != TIME_COL]
    print(f"{indent}{header or '~ ' + label(k)}")
    if not diffs:
        print(f"{indent}    sonst keine Änderungen")
    else:
        kind = "nur Zeitstempel" if not names else "Unterschiede in: " + ", ".join(names)
        print(f"{indent}    {kind}  ({delta})")
        print(f"{indent}    Last Modified: {old[k][TIME_COL]}  |  {new[nk][TIME_COL]}")
    for c in names:
        secret = c in SECRET_COLS
        a = short(old[k][c], secret, show_secrets)
        b = short(new[nk][c], secret, show_secrets)
        if secret and not show_secrets:
            print(f"{indent}    {c}: geändert ({a} → {b})")
        else:
            print(f"{indent}    {c}: {a}  →  {b}")


def print_move(move, compare_cols, old, new, n1, n2, show_secrets, indent="  "):
    """Gibt ein erkanntes Paar aus verschobenem/umbenanntem Eintrag aus."""
    ok, nk, confidence = move
    key_changes = [c for c, a, b in zip(KEY_COLS, ok, nk) if a != b]
    diffs = [c for c in compare_cols if old[ok][c] != new[nk][c]]
    _, delta = classify(ok, old, new, n1, n2, new_key=nk)
    header = (f"↷ {label(ok)}  →  {label(nk)}\n"
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
