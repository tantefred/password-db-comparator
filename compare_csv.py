#!/usr/bin/env python3
"""Vergleicht zwei KeePassium-CSV-Exporte und zeigt die Unterschiede.

Aufruf: python3 compare_csv.py alt.csv neu.csv [--show-secrets] [--export-added [DATEI]]
"""
import argparse
import csv
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from urllib.parse import urlsplit

KEY_COLS = ("Group", "Title", "Username")
SECRET_COLS = ("Password", "TOTP")
TIME_COL = "Last Modified"
EXPECTED = ["Group", "Title", "Username", "Password", "URL", "Notes",
            "TOTP", "Icon", "Last Modified", "Created"]
# Einträge in Gruppen, deren Pfad eines dieser Muster enthält, werden nicht exportiert
EXCLUDE_GROUP_PATTERNS = ("papierkorb",)

TS_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d.%m.%Y %H:%M:%S",
              "%d.%m.%Y %H:%M", "%d.%m.%Y", "%Y-%m-%d", "%m/%d/%Y %H:%M:%S")


def load(path):
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            missing = [c for c in EXPECTED if c not in (reader.fieldnames or [])]
            if missing:
                sys.exit(f"Fehler: In '{path}' fehlen Spalten: {', '.join(missing)}")
            rows = list(reader)
    except OSError as e:
        sys.exit(f"Fehler: '{path}' kann nicht gelesen werden: {e}")

    # Doppelte Schlüssel durchnummerieren, damit nichts verloren geht
    seen = defaultdict(int)
    entries = {}
    for row in rows:
        base = tuple(row[c] for c in KEY_COLS)
        seen[base] += 1
        entries[base + (seen[base],)] = row
    return entries


def parse_ts(s):
    """Zeitstempel -> aware datetime (UTC) oder None, wenn nicht lesbar."""
    s = (s or "").strip()
    if not s:
        return None
    dt = None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        for fmt in TS_FORMATS:
            try:
                dt = datetime.strptime(s, fmt)
                break
            except ValueError:
                pass
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def human_delta(seconds):
    seconds = int(abs(seconds))
    for unit, size in (("Tag(e)", 86400), ("Stunde(n)", 3600), ("Minute(n)", 60)):
        if seconds >= size:
            return f"{seconds // size} {unit}"
    return f"{seconds} Sekunde(n)"


def label(key):
    group, title, user, n = key
    s = f"{group or '(ohne Gruppe)'} / {title or '(ohne Titel)'}"
    if user:
        s += f"  [{user}]"
    if n > 1:
        s += f"  #{n}"
    return s


def short(value, secret, show_secrets):
    if secret and not show_secrets:
        return "(gesetzt)" if value else "(leer)"
    value = value.replace("\r", "").replace("\n", " ⏎ ")
    if len(value) > 80:
        value = value[:77] + "..."
    return repr(value) if value == "" else value


def is_excluded(row):
    g = row["Group"].lower()
    return any(p in g for p in EXCLUDE_GROUP_PATTERNS)


def write_csv(path, rows):
    """Schreibt Einträge im KeePassium-Spaltenformat (wieder importierbar)."""
    try:
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=EXPECTED, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
    except OSError as e:
        sys.exit(f"Fehler: '{path}' kann nicht geschrieben werden: {e}")


def build_merged(old, new, removed, added, moves, compare_cols):
    """Vereinigt beide Dateien; bei Unterschieden gewinnt die jeweils neuere Version.

    Rückgabe: (zeilen, statistik, konflikte). Konflikte sind Einträge mit
    unterschiedlichem Inhalt, bei denen die Aktualität nicht bestimmbar ist
    (gleicher/fehlender Zeitstempel); dort wird die Version aus Datei 2 genommen.
    """
    stats = {"nur_alt": 0, "nur_neu": 0, "alt_neuer": 0, "neu_neuer": 0, "gleich": 0}
    conflicts = []
    rows = []

    pairs = [(k, k) for k in sorted(set(old) & set(new))]
    pairs += [(ok, nk) for ok, nk, _ in moves]
    for ok, nk in pairs:
        t_old = parse_ts(old[ok][TIME_COL])
        t_new = parse_ts(new[nk][TIME_COL])
        differs = any(old[ok][c] != new[nk][c] for c in compare_cols)
        if t_old and t_new and t_old > t_new:
            rows.append(old[ok])
            stats["alt_neuer"] += 1
        elif t_old and t_new and t_new > t_old:
            rows.append(new[nk])
            stats["neu_neuer"] += 1
        else:
            rows.append(new[nk])
            if differs:
                conflicts.append(nk)
            else:
                stats["gleich"] += 1
    for k in removed:
        rows.append(old[k])
        stats["nur_alt"] += 1
    for k in added:
        rows.append(new[k])
        stats["nur_neu"] += 1

    rows.sort(key=lambda r: (r["Group"], r["Title"], r["Username"]))
    return rows, stats, conflicts


def print_stats(old, new, n1, n2):
    """Gibt die Anzahl der Einträge pro Gruppe für beide Dateien aus."""
    c_old = Counter(r["Group"] for r in old.values())
    c_new = Counter(r["Group"] for r in new.values())
    groups = sorted(set(c_old) | set(c_new))
    names = [g or "(ohne Gruppe)" for g in groups]
    w = max([len(x) for x in names] + [len("Gesamt"), len("Gruppe")])
    w1, w2 = max(len(n1), 6), max(len(n2), 6)
    print(f"{'Gruppe':<{w}}  {n1:>{w1}}  {n2:>{w2}}  Differenz")
    print("-" * (w + w1 + w2 + 15))
    for g, name in zip(groups, names):
        a, b = c_old[g], c_new[g]
        print(f"{name:<{w}}  {a:>{w1}}  {b:>{w2}}  {b - a:+d}")
    print("-" * (w + w1 + w2 + 15))
    a, b = len(old), len(new)
    print(f"{'Gesamt':<{w}}  {a:>{w1}}  {b:>{w2}}  {b - a:+d}")


def url_problem(url):
    """Gibt einen Grund zurück, falls die URL offensichtlich ungültig ist, sonst None."""
    url = url.strip()
    if not url:
        return None
    if any(ch.isspace() for ch in url):
        return "enthält Leerzeichen"
    host = urlsplit(url if "://" in url else "//" + url).hostname or ""
    if not host:
        return "kein Host erkennbar"
    if "." not in host and host != "localhost" and ":" not in host:
        return "Host ohne Punkt"
    return None


def check_entries(entries):
    """Prüft eine Datei auf Dubletten und kaputte Einträge.

    Rückgabe: Liste (überschrift, [zeilen]) – nur Kategorien mit Funden.
    Passwörter werden nie ausgegeben.
    """
    findings = []

    exact = defaultdict(list)
    for k in entries:
        exact[k[:3]].append(k)
    lines = [f"{label(ks[0])}  ({len(ks)}×)" for ks in exact.values() if len(ks) > 1]
    findings.append(("Doppelte Einträge (gleiche Gruppe, Titel und Username)", sorted(lines)))

    by_title = defaultdict(list)
    for k in entries:
        if k[1] and k[2]:
            by_title[(k[1].lower(), k[2].lower())].append(k)
    lines = []
    for ks in by_title.values():
        if len({k[0] for k in ks}) > 1:
            lines.append(f"{ks[0][1]} [{ks[0][2]}] in: " + ", ".join(sorted({k[0] or '(ohne Gruppe)' for k in ks})))
    findings.append(("Gleicher Titel und Username in verschiedenen Gruppen", sorted(lines)))

    by_url = defaultdict(list)
    for k, r in entries.items():
        url = r["URL"].strip().lower().rstrip("/")
        if url and k[2]:
            by_url[(url, k[2].lower())].append(k)
    lines = []
    for (url, user), ks in by_url.items():
        if len({k[:3] for k in ks}) > 1:
            lines.append(f"{url} [{user}]: " + "; ".join(label(k) for k in ks))
    findings.append(("Gleiche URL und Username in verschiedenen Einträgen", sorted(lines)))

    findings.append(("Einträge ohne Passwort",
                     sorted(label(k) for k, r in entries.items() if not r["Password"])))
    findings.append(("Einträge ohne Titel",
                     sorted(label(k) for k in entries if not k[1])))
    lines = []
    for k, r in sorted(entries.items()):
        reason = url_problem(r["URL"])
        if reason:
            lines.append(f"{label(k)}: '{r['URL'].strip()}' ({reason})")
    findings.append(("Ungültige URLs", lines))

    return [(title, lines) for title, lines in findings if lines]


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


def audit_entries(entries, min_length, max_age_days, now):
    """Bewertet die Passwortqualität einer Datei. Passwörter werden nie ausgegeben.

    Rückgabe: (funde, totp_anzahl) mit funde = Liste (überschrift, [zeilen]).
    """
    findings = []

    by_pw = defaultdict(list)
    for k, r in entries.items():
        if r["Password"]:
            by_pw[r["Password"]].append(k)
    lines = sorted(f"{len(ks)} Einträge teilen ein Passwort: " + "; ".join(label(k) for k in sorted(ks))
                   for ks in by_pw.values() if len(ks) > 1)
    findings.append(("Wiederverwendete Passwörter", lines))

    lines = [f"{label(k)}  ({len(r['Password'])} Zeichen)"
             for k, r in sorted(entries.items()) if r["Password"] and len(r["Password"]) < min_length]
    findings.append((f"Kurze Passwörter (< {min_length} Zeichen)", lines))

    lines = []
    for k, r in sorted(entries.items()):
        ts = parse_ts(r[TIME_COL])
        if ts is not None and (now - ts).days > max_age_days:
            lines.append(f"{label(k)}  (zuletzt geändert {ts.date().isoformat()}, "
                         f"vor {(now - ts).days} Tagen)")
    findings.append((f"Lange nicht geändert (> {max_age_days} Tage)", lines))

    totp = sum(1 for r in entries.values() if r["TOTP"].strip())
    return [(t, ls) for t, ls in findings if ls], totp


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


def search_matches(needle, old, new, removed, added, moves, groups):
    """Sucht needle in Gruppe/Titel/Username beider Dateien.

    Rückgabe: (anzahl_treffer, ergebnisse) mit ergebnisse = Liste (art, daten):
    'moved' -> move, 'only_old'/'only_new'/'identical' -> key,
    'changed' -> (key, gruppe, diffs, delta). Ein verschobenes Paar erscheint nur einmal.
    """
    needle = needle.strip().lower()
    changed_by_key = {k: (grp, diffs, delta)
                      for grp, items in groups.items() for k, diffs, delta in items}
    matches = sorted(k for k in set(old) | set(new)
                     if needle in " / ".join(k[:3]).lower())
    removed_set, added_set = set(removed), set(added)
    moved_by_key = {k: m for m in moves for k in m[:2]}
    shown_moves = set()
    results = []
    for k in matches:
        if k in moved_by_key:
            move = moved_by_key[k]
            if move not in shown_moves:
                shown_moves.add(move)
                results.append(("moved", move))
        elif k in removed_set:
            results.append(("only_old", k))
        elif k in added_set:
            results.append(("only_new", k))
        elif k in changed_by_key:
            grp, diffs, delta = changed_by_key[k]
            results.append(("changed", (k, grp, diffs, delta)))
        else:
            results.append(("identical", k))
    return len(matches), results


def display_names(path1, path2):
    """Dateinamen für die Ausgabe; bei gleichem Namen der volle Pfad."""
    n1, n2 = os.path.basename(path1), os.path.basename(path2)
    return (path1, path2) if n1 == n2 else (n1, n2)


def find_moves(old, new, removed, added, ignored):
    """Findet verschobene/umbenannte Einträge unter den nur einseitig vorhandenen Keys.

    Rückgabe: Liste (alter_key, neuer_key, sicherheit) mit sicherheit 'sicher' oder
    'wahrscheinlich'. Gepaart wird nur bei eindeutigen 1:1-Treffern.
    """
    def same(r, a, col):
        return col not in ignored and old[r][col] != "" and old[r][col] == new[a][col]

    def strong(r, a):
        return same(r, a, "Created") and any(
            same(r, a, c) for c in ("Password", "URL", "Title"))

    def likely(r, a):
        return all(same(r, a, c) for c in ("Username", "Password", "URL"))

    moves = []
    left_old, left_new = list(removed), list(added)
    for matcher, confidence in ((strong, "sicher"), (likely, "wahrscheinlich")):
        cands = {r: [a for a in left_new if matcher(r, a)] for r in left_old}
        reverse = defaultdict(list)
        for r, lst in cands.items():
            for a in lst:
                reverse[a].append(r)
        paired = [(r, lst[0]) for r, lst in cands.items()
                  if len(lst) == 1 and len(reverse[lst[0]]) == 1]
        for r, a in paired:
            moves.append((r, a, confidence))
        left_old = [r for r in left_old if r not in {m[0] for m in paired}]
        left_new = [a for a in left_new if a not in {m[1] for m in paired}]
    return sorted(moves)


def classify(key, old, new, n1, n2, new_key=None):
    """Gibt (gruppe, delta_text) zurück. gruppe: 'old_outdated' | 'new_outdated' | 'unclear'."""
    t_old = parse_ts(old[key][TIME_COL])
    t_new = parse_ts(new[new_key or key][TIME_COL])
    if t_old is None or t_new is None:
        return "unclear", "Zeitstempel nicht auswertbar"
    diff = (t_new - t_old).total_seconds()
    if diff > 0:
        return "old_outdated", f"{n2} ist {human_delta(diff)} neuer"
    if diff < 0:
        return "new_outdated", f"{n1} ist {human_delta(diff)} neuer"
    return "unclear", "gleicher Zeitstempel, Inhalt unterschiedlich"


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


def main():
    p = argparse.ArgumentParser(description="KeePassium-CSV-Exporte vergleichen")
    p.add_argument("alt", help="Erste CSV-Datei")
    p.add_argument("neu", help="Zweite CSV-Datei")
    p.add_argument("--show-secrets", action="store_true",
                   help="Passwörter/TOTP im Klartext anzeigen")
    p.add_argument("-i", "--ignore", nargs="+", default=[], metavar="SPALTE",
                   help="Spalten, die beim Vergleich ignoriert werden "
                        "(z. B. --ignore Icon \"Last Modified\" oder --ignore Icon,Notes). "
                        f"Mögliche Werte: {', '.join(c for c in EXPECTED if c not in KEY_COLS)}")
    p.add_argument("-s", "--search", metavar="TEXT",
                   help="Nur Einträge anzeigen, deren Gruppe, Titel oder Username TEXT enthält "
                        "(Groß-/Kleinschreibung egal), samt Status. "
                        "Nicht kombinierbar mit --export-added.")
    p.add_argument("--hide-trash", action="store_true",
                   help="Einträge aus Papierkorb-Gruppen komplett ausblenden "
                        "(Vergleich, Suche und Exporte)")
    p.add_argument("-g", "--group", metavar="TEXT",
                   help="Nur Einträge betrachten, deren Gruppenpfad TEXT enthält "
                        "(Groß-/Kleinschreibung egal), z. B. --group Privat. "
                        "Gilt für Vergleich, Suche und Exporte.")
    p.add_argument("--stats", action="store_true",
                   help="Nur die Anzahl der Einträge pro Gruppe in beiden Dateien anzeigen "
                        "(nicht kombinierbar mit --search, --export-added, --export-merged)")
    p.add_argument("--check", action="store_true",
                   help="Jede Datei einzeln auf Dubletten und kaputte Einträge prüfen "
                        "(ohne Passwörter anzuzeigen; nicht kombinierbar mit --search, "
                        "--stats und den Exporten)")
    p.add_argument("--password-check", action="store_true",
                   help="Passwortqualität je Datei prüfen: wiederverwendete und kurze Passwörter, "
                        "lange nicht geänderte Einträge, TOTP-Anzahl (Passwörter werden nie "
                        "angezeigt; nicht kombinierbar mit --search, --stats, --check, Exporten)")
    p.add_argument("--min-length", type=int, default=10, metavar="N",
                   help="Mindestlänge für --password-check (Standard: 10)")
    p.add_argument("--max-age-days", type=int, default=730, metavar="TAGE",
                   help="Maximales Alter seit der letzten Änderung für --password-check "
                        "(Standard: 730)")
    p.add_argument("--no-detect-moves", action="store_true",
                   help="Verschobene/umbenannte Einträge nicht erkennen "
                        "(sie erscheinen dann als 'entfernt' plus 'hinzugefügt')")
    p.add_argument("--export-added", nargs="?", const="neue_eintraege.csv",
                   metavar="DATEI",
                   help="Neu hinzugefügte Einträge als CSV schreiben "
                        "(Standard: neue_eintraege.csv). Enthält Passwörter im Klartext! "
                        "Einträge aus Papierkorb-Gruppen werden ausgelassen.")
    p.add_argument("--export-merged", nargs="?", const="merged.csv", metavar="DATEI",
                   help="Zusammengeführte CSV schreiben: alle Einträge beider Dateien, bei "
                        "Unterschieden die jeweils neuere Version (Standard: merged.csv). "
                        "Enthält Passwörter im Klartext! Papierkorb-Gruppen werden ausgelassen. "
                        "Nicht kombinierbar mit --search.")
    args = p.parse_args()

    # Auswertungsmodi ersetzen die normale Ausgabe und schließen sich gegenseitig
    # sowie die Exporte aus.
    modes = [name for name, active in (("--search", args.search is not None),
                                       ("--stats", args.stats),
                                       ("--check", args.check),
                                       ("--password-check", args.password_check)) if active]
    exports = [name for name, active in (("--export-added", args.export_added),
                                         ("--export-merged", args.export_merged)) if active]
    if len(modes) > 1:
        p.error(f"{modes[0]} und {modes[1]} können nicht kombiniert werden.")
    if modes and exports:
        p.error(f"{modes[0]} und {exports[0]} können nicht kombiniert werden.")
    if args.search is not None and not args.search.strip():
        p.error("--search benötigt einen nicht-leeren Suchbegriff.")

    by_lower = {c.lower(): c for c in EXPECTED}
    ignored = []
    for part in (s.strip() for item in args.ignore for s in item.split(",")):
        if not part:
            continue
        col = by_lower.get(part.lower())
        if col is None:
            p.error(f"Unbekannte Spalte '{part}'. Gültig: "
                    f"{', '.join(c for c in EXPECTED if c not in KEY_COLS)}")
        if col in KEY_COLS:
            p.error(f"Die Spalte '{col}' identifiziert die Einträge und kann nicht ignoriert werden.")
        if col not in ignored:
            ignored.append(col)

    old, new = load(args.alt), load(args.neu)
    if args.hide_trash:
        old = {k: r for k, r in old.items() if not is_excluded(r)}
        new = {k: r for k, r in new.items() if not is_excluded(r)}
    if args.group is not None:
        needle = args.group.strip().lower()
        if not needle:
            p.error("--group benötigt einen nicht-leeren Suchbegriff.")
        old = {k: r for k, r in old.items() if needle in r["Group"].lower()}
        new = {k: r for k, r in new.items() if needle in r["Group"].lower()}
    n1, n2 = display_names(args.alt, args.neu)
    removed = sorted(set(old) - set(new))
    added = sorted(set(new) - set(old))

    compare_cols = [c for c in EXPECTED if c not in KEY_COLS and c not in ignored]

    # Verschobene/umbenannte Einträge aus removed/added herauslösen
    moves = [] if args.no_detect_moves else find_moves(old, new, removed, added, ignored)
    moved_old = {m[0] for m in moves}
    moved_new = {m[1] for m in moves}
    removed = [k for k in removed if k not in moved_old]
    added = [k for k in added if k not in moved_new]

    groups = {"old_outdated": [], "new_outdated": [], "unclear": []}
    for key in sorted(set(old) & set(new)):
        diffs = [c for c in compare_cols if old[key][c] != new[key][c]]
        if diffs:
            grp, delta = classify(key, old, new, n1, n2)
            groups[grp].append((key, diffs, delta))
    n_changed = sum(len(v) for v in groups.values())

    print(f"{n1}: {len(old)} Einträge")
    print(f"{n2}: {len(new)} Einträge")
    if ignored:
        print(f"Ignorierte Spalten: {', '.join(ignored)}")
    if args.hide_trash:
        print("Papierkorb-Gruppen ausgeblendet")
    if args.group is not None:
        print(f"Gruppenfilter: '{args.group.strip()}'")
    if args.stats:
        print()
        print_stats(old, new, n1, n2)
        return
    if args.check:
        print()
        print_check(old, new, n1, n2)
        return
    if args.password_check:
        print()
        print_password_check(old, new, n1, n2, args.min_length, args.max_age_days)
        return
    print()

    titles = {
        "old_outdated": f"Geändert – {n2} ist aktueller ({n1} muss aktualisiert werden)",
        "new_outdated": f"Geändert – {n1} ist aktueller ({n2} muss aktualisiert werden)",
        "unclear": "Geändert – Aktualität unklar (manuell prüfen)",
    }

    if args.search is not None:
        n_matches, results = search_matches(args.search, old, new, removed, added,
                                            moves, groups)
        if not n_matches:
            sys.exit(f"Kein Eintrag gefunden, dessen Gruppe, Titel oder Username "
                     f"'{args.search}' enthält.")
        print(f"Suche nach '{args.search}': {n_matches} Treffer\n")
        for kind, data in results:
            if kind == "moved":
                print(f"  Status: verschoben/umbenannt")
                print_move(data, compare_cols, old, new, n1, n2, args.show_secrets)
            elif kind == "only_old":
                print(f"  - {label(data)}")
                print(f"      Status: nur in {n1} (in {n2} nicht vorhanden)")
                print(f"      Last Modified: {old[data][TIME_COL]}")
            elif kind == "only_new":
                print(f"  + {label(data)}")
                print(f"      Status: nur in {n2} (in {n1} nicht vorhanden)")
                print(f"      Last Modified: {new[data][TIME_COL]}")
            elif kind == "changed":
                k, grp, diffs, delta = data
                print(f"  Status: {titles[grp]}")
                print_changed(k, diffs, delta, old, new, args.show_secrets)
            else:
                print(f"  = {label(data)}")
                print(f"      Status: identisch in beiden Dateien")
                print(f"      Last Modified: {old[data][TIME_COL]}")
            print()
        return

    if moves:
        print(f"== Verschoben/umbenannt: {len(moves)} ==")
        for move in moves:
            print_move(move, compare_cols, old, new, n1, n2, args.show_secrets)
        print()
    if removed:
        print(f"== Nur in {n1} (in {n2} nicht vorhanden): {len(removed)} ==")
        for k in removed:
            print(f"  - {label(k)}")
        print()
    if added:
        print(f"== Nur in {n2} (in {n1} nicht vorhanden): {len(added)} ==")
        for k in added:
            print(f"  + {label(k)}")
        print()

    for grp in ("old_outdated", "new_outdated", "unclear"):
        items = groups[grp]
        if not items:
            continue
        print(f"== {titles[grp]}: {len(items)} ==")
        for k, diffs, delta in items:
            print_changed(k, diffs, delta, old, new, args.show_secrets)
        print()

    if args.export_added:
        export = [k for k in added if not is_excluded(new[k])]
        skipped = len(added) - len(export)
        write_csv(args.export_added, [new[k] for k in export])
        print(f"{len(export)} neue Einträge nach '{args.export_added}' exportiert "
              f"({skipped} aus Papierkorb ausgelassen; Datei enthält Passwörter im Klartext).\n")

    if args.export_merged:
        rows, stats, conflicts = build_merged(old, new, removed, added, moves, compare_cols)
        export = [r for r in rows if not is_excluded(r)]
        write_csv(args.export_merged, export)
        print(f"{len(export)} Einträge nach '{args.export_merged}' exportiert "
              f"({len(rows) - len(export)} aus Papierkorb ausgelassen; "
              f"Datei enthält Passwörter im Klartext).")
        print(f"  nur in {n1}: {stats['nur_alt']}, nur in {n2}: {stats['nur_neu']}, "
              f"neuere Version aus {n1}: {stats['alt_neuer']}, "
              f"aus {n2}: {stats['neu_neuer']}, unverändert: {stats['gleich']}")
        if conflicts:
            print(f"  {len(conflicts)} Konflikt(e) mit unklarer Aktualität – "
                  f"Version aus {n2} übernommen, bitte prüfen:")
            for k in conflicts:
                print(f"    ! {label(k)}")
        print()

    if not (removed or added or n_changed or moves):
        print("Keine Unterschiede.")
    else:
        print(f"Zusammenfassung: {len(removed)} nur in {n1}, {len(added)} nur in {n2}, "
              f"{len(moves)} verschoben/umbenannt, "
              f"{n_changed} geändert "
              f"({len(groups['old_outdated'])} in {n1} zu aktualisieren, "
              f"{len(groups['new_outdated'])} in {n2} zu aktualisieren, "
              f"{len(groups['unclear'])} manuell prüfen).")


if __name__ == "__main__":
    main()
