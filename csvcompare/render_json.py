"""JSON-Berichte: je Auswertungsmodus ein Bericht, den Terminal und Weboberfläche teilen."""

import json

from .analysis import audit_entries, check_entries, stats_rows
from .columns import MODIFIED, SECRET_NAMES
from .compare import FRESHNESS, NEWER_IN_NEW, NEWER_IN_OLD, UNCLEAR
from .display import mask_secret
from .search import MOVED, ONLY_IN_NEW, search


def dump(report):
    """Gibt einen Bericht als JSON auf stdout aus."""
    print(json.dumps(report, ensure_ascii=False, indent=2))


def entry_ref(key):
    """Schlüssel eines Eintrags als JSON-Objekt."""
    ref = {"group": key.group, "title": key.title, "username": key.username}
    if key.number > 1:
        ref["duplicate_index"] = key.number
    return ref


def change_json(cmp, change, show_secrets):
    """Einen Eintrag mit seinen Unterschieden als JSON-Objekt; Geheimnisse sind maskiert."""
    old_row, new_row = cmp.old[change.key], cmp.new[change.new_key]
    changes = {}
    for column in change.columns:
        old_value, new_value = old_row[column], new_row[column]
        if column in SECRET_NAMES and not show_secrets:
            changes[column] = {"old": mask_secret(old_value), "new": mask_secret(new_value),
                               "masked": True}
        else:
            changes[column] = {"old": old_value, "new": new_value}
    result = {"entry": entry_ref(change.key)}
    if change.new_key != change.key:
        result["moved_to"] = entry_ref(change.new_key)
    result["differing_columns"] = list(change.columns)
    result["only_timestamp"] = bool(change.columns) and all(c == MODIFIED for c in change.columns)
    result["note"] = change.note if change.columns else None
    result["last_modified"] = {"old": old_row[MODIFIED], "new": new_row[MODIFIED]}
    result["changes"] = changes
    return result


def move_json(cmp, move, show_secrets):
    """Ein verschobenes oder umbenanntes Paar als JSON-Objekt."""
    result = change_json(cmp, cmp.move_change(move), show_secrets)
    result["changed_key_columns"] = move.key_columns
    result["confidence"] = move.confidence
    return result


def base_report(cmp, args):
    """Gemeinsamer Kopf aller Berichte: Dateien und aktive Filter."""
    def side(name, path, entries, source):
        return {"name": name, "path": path, "entries": len(entries),
                "format": source.format if source else None,
                "db_prefix": source.db_prefix if source else None,
                "notes": list(source.notes) if source else []}

    return {
        "files": {
            "old": side(cmp.old_name, args.alt, cmp.old, cmp.old_source),
            "new": side(cmp.new_name, args.neu, cmp.new, cmp.new_source),
        },
        "filters": {
            "ignored_columns": cmp.ignored,
            "auto_ignored": [{"column": column, "reason": reason}
                             for column, reason in cmp.auto_ignored],
            "hide_trash": args.hide_trash,
            "group": args.group.strip() if args.group is not None else None,
            "detect_moves": not args.no_detect_moves,
        },
    }


def findings_json(findings):
    return [{"category": f.title, "count": len(f.lines), "items": f.lines} for f in findings]


def stats_report(base, cmp):
    rows = stats_rows(cmp.old, cmp.new)
    return {"mode": "stats", **base,
            "groups": [{"group": group, "old": old, "new": new, "difference": new - old}
                       for group, old, new in rows],
            "total": {"old": len(cmp.old), "new": len(cmp.new),
                      "difference": len(cmp.new) - len(cmp.old)}}


def check_report(base, cmp):
    sides = ((cmp.old_name, cmp.old), (cmp.new_name, cmp.new))
    return {"mode": "check", **base,
            "results": [{"file": name, "findings": findings_json(check_entries(entries))}
                        for name, entries in sides]}


def password_report(base, cmp, min_length, max_age_days):
    results = []
    for name, entries in ((cmp.old_name, cmp.old), (cmp.new_name, cmp.new)):
        findings, totp_count = audit_entries(entries, min_length, max_age_days)
        results.append({"file": name, "findings": findings_json(findings),
                        "totp": {"with_totp": totp_count, "entries": len(entries)}})
    return {"mode": "password-check", **base,
            "thresholds": {"min_length": min_length, "max_age_days": max_age_days},
            "results": results}


def search_report(base, cmp, query, hits, show_secrets):
    results = []
    for hit in hits:
        if hit.status == MOVED:
            results.append({"status": hit.status, **move_json(cmp, hit.item, show_secrets)})
        elif hit.status in FRESHNESS:
            results.append({"status": hit.status, **change_json(cmp, hit.item, show_secrets)})
        else:  # nur in einer Datei oder identisch
            entries = cmp.new if hit.status == ONLY_IN_NEW else cmp.old
            results.append({"status": hit.status, "entry": entry_ref(hit.item),
                            "last_modified": entries[hit.item][MODIFIED]})
    return {"mode": "search", **base, "query": query,
            "match_count": len(hits), "results": results}


def compare_report(base, cmp, show_secrets):
    count = {freshness: len(cmp.changes[freshness]) for freshness in FRESHNESS}
    return {
        "mode": "compare",
        **base,
        "moved": [move_json(cmp, move, show_secrets) for move in cmp.moves],
        "only_in_old": [entry_ref(key) for key in cmp.only_old],
        "only_in_new": [entry_ref(key) for key in cmp.only_new],
        "changed": {freshness: [change_json(cmp, change, show_secrets)
                                for change in cmp.changes[freshness]]
                    for freshness in FRESHNESS},
        "summary": {
            "only_in_old": len(cmp.only_old), "only_in_new": len(cmp.only_new),
            "moved": len(cmp.moves), "changed": cmp.n_changed,
            "newer_in_new": count[NEWER_IN_NEW],
            "newer_in_old": count[NEWER_IN_OLD],
            "unclear": count[UNCLEAR],
            "identical": cmp.identical,
        },
    }


def build_report(args, cmp):
    """Erzeugt den Bericht zum gewählten Modus: (Bericht, Exitcode).

    Der Exitcode ist 1 nur bei einer Suche ohne Treffer.
    """
    base = base_report(cmp, args)
    if args.stats:
        return stats_report(base, cmp), 0
    if args.check:
        return check_report(base, cmp), 0
    if args.password_check:
        return password_report(base, cmp, args.min_length, args.max_age_days), 0
    if args.search is not None:
        hits = search(cmp, args.search)
        return search_report(base, cmp, args.search, hits, args.show_secrets), 0 if hits else 1
    return compare_report(base, cmp, args.show_secrets), 0
