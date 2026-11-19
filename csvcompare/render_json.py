"""JSON-Darstellung der Ergebnisse."""

import json
from datetime import datetime, timezone

from .analysis import audit_entries, check_entries, stats_rows
from .common import differing_columns
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
    diffs = differing_columns(old[ok], new[nk], compare_cols)
    _, delta = classify(ok, old, new, n1, n2, new_key=nk)
    d = changed_json(ok, nk, diffs, delta, old, new, show_secrets)
    d["changed_key_columns"] = [c for c, a, b in zip(KEY_COLS, ok, nk) if a != b]
    d["confidence"] = "certain" if confidence == "sicher" else "likely"
    return d


def dump(report):
    """Gibt einen Bericht als JSON auf stdout aus."""
    print(json.dumps(report, ensure_ascii=False, indent=2))


def base_report(cmp, path_old, path_new, hide_trash, group, detect_moves):
    """Gemeinsamer Kopf aller Berichte: Dateien und aktive Filter."""
    return {
        "files": {
            "old": {"name": cmp.n1, "path": path_old, "entries": len(cmp.old)},
            "new": {"name": cmp.n2, "path": path_new, "entries": len(cmp.new)},
        },
        "filters": {
            "ignored_columns": cmp.ignored,
            "hide_trash": hide_trash,
            "group": group.strip() if group is not None else None,
            "detect_moves": detect_moves,
        },
    }


def _findings(findings):
    return [{"category": t, "count": len(ls), "items": ls} for t, ls in findings]


def stats_report(base, cmp):
    rows = stats_rows(cmp.old, cmp.new)
    return {"mode": "stats", **base,
            "groups": [{"group": g, "old": a, "new": b, "difference": b - a}
                       for g, a, b in rows],
            "total": {"old": len(cmp.old), "new": len(cmp.new),
                      "difference": len(cmp.new) - len(cmp.old)}}


def check_report(base, cmp):
    return {"mode": "check", **base,
            "results": [{"file": name, "findings": _findings(check_entries(entries))}
                        for name, entries in ((cmp.n1, cmp.old), (cmp.n2, cmp.new))]}


def password_report(base, cmp, min_length, max_age_days):
    now = datetime.now(timezone.utc)
    results = []
    for name, entries in ((cmp.n1, cmp.old), (cmp.n2, cmp.new)):
        findings, totp = audit_entries(entries, min_length, max_age_days, now)
        results.append({"file": name, "findings": _findings(findings),
                        "totp": {"with_totp": totp, "entries": len(entries)}})
    return {"mode": "password-check", **base,
            "thresholds": {"min_length": min_length, "max_age_days": max_age_days},
            "results": results}


def search_report(base, cmp, query, n_matches, results, show_secrets):
    status_of = {"old_outdated": "newer_in_new", "new_outdated": "newer_in_old",
                 "unclear": "unclear"}
    old, new, n1, n2 = cmp.old, cmp.new, cmp.n1, cmp.n2
    items = []
    for kind, data in results:
        if kind == "moved":
            items.append({"status": "moved", **move_json(
                data, cmp.compare_cols, old, new, n1, n2, show_secrets)})
        elif kind == "changed":
            k, grp, diffs, delta = data
            items.append({"status": status_of[grp], **changed_json(
                k, k, diffs, delta, old, new, show_secrets)})
        elif kind == "only_old":
            items.append({"status": "only_in_old", "entry": entry_ref(data),
                          "last_modified": old[data][TIME_COL]})
        elif kind == "only_new":
            items.append({"status": "only_in_new", "entry": entry_ref(data),
                          "last_modified": new[data][TIME_COL]})
        else:
            items.append({"status": "identical", "entry": entry_ref(data),
                          "last_modified": old[data][TIME_COL]})
    return {"mode": "search", **base, "query": query,
            "match_count": n_matches, "results": items}


def compare_report(base, cmp, show_secrets):
    old, new, n1, n2, g = cmp.old, cmp.new, cmp.n1, cmp.n2, cmp.groups

    def changed(items):
        return [changed_json(k, k, d, dl, old, new, show_secrets) for k, d, dl in items]

    return {
        "mode": "compare",
        **base,
        "moved": [move_json(m, cmp.compare_cols, old, new, n1, n2, show_secrets)
                  for m in cmp.moves],
        "only_in_old": [entry_ref(k) for k in cmp.removed],
        "only_in_new": [entry_ref(k) for k in cmp.added],
        "changed": {
            "newer_in_new": changed(g["old_outdated"]),
            "newer_in_old": changed(g["new_outdated"]),
            "unclear": changed(g["unclear"]),
        },
        "summary": {
            "only_in_old": len(cmp.removed), "only_in_new": len(cmp.added),
            "moved": len(cmp.moves), "changed": cmp.n_changed,
            "newer_in_new": len(g["old_outdated"]),
            "newer_in_old": len(g["new_outdated"]),
            "unclear": len(g["unclear"]),
            "identical": cmp.identical,
        },
    }
