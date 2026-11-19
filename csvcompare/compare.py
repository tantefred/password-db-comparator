"""Vergleichslogik: verschobene Einträge, Aktualität, Merge und Suche."""

from collections import defaultdict
from dataclasses import dataclass

from .common import human_delta, parse_ts
from .constants import EXPECTED, KEY_COLS, TIME_COL


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


@dataclass
class Comparison:
    """Ergebnis des Vergleichs zweier (bereits gefilterter) Dateien."""
    old: dict
    new: dict
    n1: str
    n2: str
    ignored: list
    compare_cols: list
    removed: list    # nur in der ersten Datei (ohne verschobene)
    added: list      # nur in der zweiten Datei (ohne verschobene)
    moves: list      # (alter_key, neuer_key, sicherheit)
    groups: dict     # 'old_outdated' | 'new_outdated' | 'unclear' -> [(key, diffs, delta)]

    @property
    def n_changed(self):
        return sum(len(v) for v in self.groups.values())

    @property
    def identical(self):
        return not (self.removed or self.added or self.n_changed or self.moves)


def compare_files(old, new, n1, n2, ignored, detect_moves=True):
    """Vergleicht zwei Dateien und gibt ein Comparison-Objekt zurück."""
    removed = sorted(set(old) - set(new))
    added = sorted(set(new) - set(old))
    compare_cols = [c for c in EXPECTED if c not in KEY_COLS and c not in ignored]

    # Verschobene/umbenannte Einträge aus removed/added herauslösen
    moves = find_moves(old, new, removed, added, ignored) if detect_moves else []
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
    return Comparison(old, new, n1, n2, list(ignored), compare_cols,
                      removed, added, moves, groups)
