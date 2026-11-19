"""JSON-Darstellung der Ergebnisse."""

from .compare import classify
from .constants import KEY_COLS, SECRET_COLS, TIME_COL


def entry_ref(key):
    """Schlüssel eines Eintrags als JSON-Objekt."""
    ref = {"group": key[0], "title": key[1], "username": key[2]}
    if key[3] > 1:
        ref["duplicate_index"] = key[3]
    return ref


def changed_json(ok, nk, diffs, delta, old, new, show_secrets):
    """Geänderten (ggf. verschobenen) Eintrag als JSON-Objekt; Geheimnisse maskiert."""
    changes = {}
    for c in diffs:
        a, b = old[ok][c], new[nk][c]
        if c in SECRET_COLS and not show_secrets:
            changes[c] = {"old": "(gesetzt)" if a else "(leer)",
                          "new": "(gesetzt)" if b else "(leer)", "masked": True}
        else:
            changes[c] = {"old": a, "new": b}
    d = {"entry": entry_ref(ok)}
    if nk != ok:
        d["moved_to"] = entry_ref(nk)
    d["differing_columns"] = list(diffs)
    d["only_timestamp"] = bool(diffs) and all(c == TIME_COL for c in diffs)
    d["note"] = delta if diffs else None
    d["last_modified"] = {"old": old[ok][TIME_COL], "new": new[nk][TIME_COL]}
    d["changes"] = changes
    return d


def move_json(move, compare_cols, old, new, n1, n2, show_secrets):
    """Verschobenes/umbenanntes Paar als JSON-Objekt."""
    ok, nk, confidence = move
    diffs = [c for c in compare_cols if old[ok][c] != new[nk][c]]
    _, delta = classify(ok, old, new, n1, n2, new_key=nk)
    d = changed_json(ok, nk, diffs, delta, old, new, show_secrets)
    d["changed_key_columns"] = [c for c, a, b in zip(KEY_COLS, ok, nk) if a != b]
    d["confidence"] = "certain" if confidence == "sicher" else "likely"
    return d
