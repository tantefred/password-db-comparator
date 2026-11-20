"""Dubletten zusammenführen: aus mehreren Zeilen eine machen und die Datei bereinigen.

Regeln: Der zuletzt geänderte Eintrag ist die Basis. Leere Felder werden aus den übrigen
ergänzt (neueste zuerst). Haben zwei Einträge verschiedene Werte in einem Feld, das man nicht
einfach mischen kann (Passwort, Notizen, ...), ist das ein Konflikt: Ohne Entscheidung gewinnt
die Basis, und die älteren Passwörter bleiben als Verlauf erhalten (wo das Zielformat es kann).
"""

from datetime import UTC, datetime
from typing import NamedTuple

from .columns import ALL_NAMES, BY_NAME, CREATED, MODIFIED, OLD_PASSWORDS_KEY
from .duplicates import KEY, normalized_url
from .entries import is_trash
from .values import parse_time, values_equal

MERGE, KEEP_ALL, KEEP_ONE = "merge", "keep_all", "keep"
ACTIONS = (MERGE, KEEP_ALL, KEEP_ONE)
BOTH = "both"  # Entscheidung für Notizen: alle verbinden
# Spalten, in denen verschiedene Werte nicht einfach vereinbar sind
CONFLICT_COLUMNS = ("Group", "Title", "Username", "Password", "URL", "Notes", "TOTP", "Icon")
NOTES_SEPARATOR = "\n\n"
EARLIEST = datetime.min.replace(tzinfo=UTC)


class Decision(NamedTuple):
    """Was mit einer Dublettengruppe geschehen soll."""

    action: str = MERGE
    keep: int = 0  # Nummer des Mitglieds bei ``KEEP_ONE``
    picks: dict = {}  # {Spalte: Nummer des Mitglieds oder BOTH} für Konflikte


def modified_at(row):
    return parse_time(row.get(MODIFIED, "")) or EARLIEST


def same_value(column, a, b):
    if column == "URL":
        return normalized_url({"URL": a}) == normalized_url({"URL": b})
    return values_equal(column, a, b)


def is_empty(column, value):
    return value in BY_NAME[column].defaults


def distinct_values(column, values):
    """Die verschiedenen nicht leeren Werte in der Reihenfolge ihres ersten Auftretens."""
    found = []
    for value in values:
        if not is_empty(column, value) and not any(same_value(column, value, v) for v in found):
            found.append(value)
    return found


def merged_urls(ordered):
    """Alle URLs der Mitglieder ohne Wiederholung; die Spalte ``URL`` des Ergebnisses zuerst."""
    urls = []
    for row in ordered:
        urls += [row["URL"]] if row.get("URL") else []
        urls += row.get("URLs", "").split()
    return urls


def merge_rows(rows, picks=None):
    """Führt Zeilen zu einer zusammen. Rückgabe: (zeile, spalten_mit_konflikt)."""
    picks = picks or {}
    order = sorted(range(len(rows)), key=lambda i: (modified_at(rows[i]), i), reverse=True)
    ordered = [rows[i] for i in order]
    result = dict(ordered[0])
    conflicts = []

    for column in ALL_NAMES:
        if column in (MODIFIED, CREATED, "URLs", "Fields") or column not in result:
            continue
        values = [row.get(column, "") for row in ordered]
        found = distinct_values(column, values)
        if column in CONFLICT_COLUMNS and len(found) > 1:
            conflicts.append(column)
        if column in picks:
            pick = picks[column]
            if pick == BOTH and column == "Notes":
                result[column] = NOTES_SEPARATOR.join(found)
            else:
                result[column] = rows[pick].get(column, "")
        elif is_empty(column, result[column]) and found:
            result[column] = found[0]

    fields = [row.get("Fields", "") for row in ordered]
    result["Fields"] = next((value for value in fields if value), "")
    created = [(parse_time(row.get(CREATED, "")), row) for row in ordered]
    created = [pair for pair in created if pair[0]]
    if created:
        result[CREATED] = min(created, key=lambda pair: pair[0])[1][CREATED]

    unique_urls = []
    for url in [result["URL"]] * bool(result["URL"]) + merged_urls(ordered):
        if not any(same_value("URL", url, other) for other in unique_urls):
            unique_urls.append(url)
    if "URLs" in result or len(unique_urls) > 1:
        result["URLs"] = "\n".join(unique_urls)

    old_passwords = []
    for row in ordered:
        candidates = [(row.get("Password", ""), row.get(MODIFIED, ""))]
        candidates += list(row.get(OLD_PASSWORDS_KEY) or [])
        for password, used in candidates:
            if (
                password
                and password != result["Password"]
                and all(password != known for known, _ in old_passwords)
            ):
                old_passwords.append((password, used))
    if old_passwords:
        result[OLD_PASSWORDS_KEY] = old_passwords
    return result, conflicts


class MergedGroup(NamedTuple):
    group: object  # die DuplicateGroup
    action: str
    conflicts: tuple  # Spalten mit verschiedenen Werten (auch wenn entschieden wurde)
    kept: tuple  # Schlüssel der Einträge, die in der Datei bleiben, oder ()


class Cleaned(NamedTuple):
    rows: list
    merged: list  # MergedGroup je zusammengeführter Gruppe
    removed: int  # Einträge, die durch das Zusammenführen oder Auswählen wegfielen
    trash: int  # ausgelassene Papierkorb-Einträge


def decision_for(group, decisions, auto_kinds):
    """Die Entscheidung zur Gruppe; ohne Angabe wird nur bei ``auto_kinds`` zusammengeführt."""
    if decisions and group.id in decisions:
        return decisions[group.id]
    return Decision(MERGE if group.kind in auto_kinds else KEEP_ALL)


def check_decisions(groups, decisions):
    """Wirft ``ValueError`` bei unbekannten Gruppen oder ungültigen Entscheidungen."""
    by_id = {group.id: group for group in groups}
    for group_id, decision in (decisions or {}).items():
        group = by_id.get(group_id)
        if group is None:
            raise ValueError(f"Unbekannte Dublettengruppe '{group_id}'.")
        if decision.action not in ACTIONS:
            raise ValueError(f"Unbekannte Aktion '{decision.action}'.")
        size = len(group.keys)
        if decision.action == KEEP_ONE and not 0 <= decision.keep < size:
            raise ValueError("Das zu behaltende Mitglied gibt es nicht.")
        for column, pick in decision.picks.items():
            if column not in CONFLICT_COLUMNS:
                raise ValueError(f"Für die Spalte '{column}' kann nichts gewählt werden.")
            if not (pick == BOTH or (isinstance(pick, int) and 0 <= pick < size)):
                raise ValueError("Die gewählte Quelle gibt es nicht.")


def clean_entries(entries, groups, decisions=None, auto_kinds=(KEY,)):
    """Die Datei ohne Dubletten: Zeilen nach den Entscheidungen, ohne Papierkorb, sortiert."""
    check_decisions(groups, decisions)
    handled = {key for group in groups for key in group.keys}
    rows = [row for key, row in entries.items() if key not in handled and not is_trash(row)]
    merged, removed = [], 0
    for group in groups:
        decision = decision_for(group, decisions, auto_kinds)
        members = [entries[key] for key in group.keys]
        if decision.action == KEEP_ALL:
            rows += members
        elif decision.action == KEEP_ONE:
            rows.append(members[decision.keep])
            removed += len(members) - 1
            merged.append(MergedGroup(group, KEEP_ONE, (), (group.keys[decision.keep],)))
        else:
            row, conflicts = merge_rows(members, decision.picks)
            rows.append(row)
            removed += len(members) - 1
            merged.append(MergedGroup(group, MERGE, tuple(conflicts), ()))
    trash = sum(1 for row in entries.values() if is_trash(row))
    rows.sort(key=lambda row: (row["Group"], row["Title"], row["Username"]))
    return Cleaned(rows, merged, removed, trash)
