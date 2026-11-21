"""Dubletten zusammenführen: aus mehreren Zeilen eine machen und die Datei bereinigen.

Regeln: Der zuletzt geänderte Eintrag ist die Basis. Leere Felder werden aus den übrigen
ergänzt (neueste zuerst). Haben zwei Einträge verschiedene Werte in einem Feld, das man nicht
einfach mischen kann (Passwort, Notizen, ...), ist das ein Konflikt: Ohne Entscheidung gewinnt
die Basis, und die älteren Passwörter bleiben als Verlauf erhalten (wo das Zielformat es kann).
"""

import copy
from datetime import UTC, datetime
from typing import NamedTuple

from .columns import (
    ALL_NAMES,
    BY_NAME,
    CREATED,
    MODIFIED,
    OLD_PASSWORDS_KEY,
    SOURCE_KEY,
    UNMAPPED_KEY,
)
from .duplicates import KEY, normalized_url
from .entries import is_trash
from .importers.bitwarden import canonical_fields
from .values import parse_time, values_equal

MERGE, KEEP_ALL, KEEP_ONE = "merge", "keep_all", "keep"
ACTIONS = (MERGE, KEEP_ALL, KEEP_ONE)
BOTH = "both"  # Entscheidung: die Werte aller Mitglieder verbinden
# Spalten, in denen verschiedene Werte nicht einfach vereinbar sind
CONFLICT_COLUMNS = (
    "Group",
    "Title",
    "Username",
    "Password",
    "URL",
    "Notes",
    "TOTP",
    "Icon",
    "Fields",
    "Type",
)
# Nur hier lassen sich mehrere Werte sinnvoll hintereinander schreiben
JOIN_SEPARATORS = {"Notes": "\n\n", "Fields": " "}
# Schalter: ist er bei einem Mitglied gesetzt, ist er es im Ergebnis
ANY_WINS_COLUMNS = ("Favorite", "Reprompt")
EARLIEST = datetime.min.replace(tzinfo=UTC)


class Decision(NamedTuple):
    """Was mit einer Dublettengruppe geschehen soll."""

    action: str = MERGE
    keep: int = 0  # Nummer des Mitglieds bei ``KEEP_ONE``
    picks: dict | None = None  # {Spalte: Nummer des Mitglieds oder BOTH} für Konflikte


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


def merged_uri_objects(ordered, urls):
    """Die Bitwarden-URI-Objekte (mit Abgleichsmodus) zu den URLs des Ergebnisses."""
    originals = [
        uri
        for row in ordered
        for uri in ((row.get(SOURCE_KEY) or {}).get("login") or {}).get("uris") or []
        if isinstance(uri, dict) and uri.get("uri")
    ]
    objects = []
    for url in urls:
        matching = [u for u in originals if same_value("URL", u["uri"], url)]
        # ein ausdrücklich gesetzter Abgleichsmodus geht vor „Standard“ (None)
        found = next((u for u in matching if u.get("match") is not None), None) or next(
            iter(matching), None
        )
        objects.append(copy.deepcopy(found) if found else {"match": None, "uri": url})
    return objects


def union(items, key):
    """Die Elemente aller Listen ohne Wiederholung (nach ``key``), in der Reihenfolge."""
    seen, result = set(), []
    for item in items:
        marker = key(item)
        if marker not in seen:
            seen.add(marker)
            result.append(item)
    return result


def merge_sources(ordered, result):
    """Der Originaleintrag des Ergebnisses: der der Basis, ergänzt um Daten der anderen.

    Passwort-Verlauf, Passkeys, Sammlungen, URI-Abgleichsmodi und die Typen eigener Felder
    der übrigen Einträge gehen so nicht verloren.
    """
    sources = [row[SOURCE_KEY] for row in ordered if isinstance(row.get(SOURCE_KEY), dict)]
    if not isinstance(ordered[0].get(SOURCE_KEY), dict):
        return None  # die Basis stammt nicht aus Bitwarden-JSON: es gibt nichts fortzuschreiben
    merged = copy.deepcopy(sources[0])
    history = union(
        [h for s in sources for h in s.get("passwordHistory") or [] if isinstance(h, dict)],
        lambda h: (h.get("password"), h.get("lastUsedDate")),
    )
    merged["passwordHistory"] = history or None
    collections = union([c for s in sources for c in s.get("collectionIds") or []], lambda c: c)
    merged["collectionIds"] = collections or None
    login = merged.get("login")
    if isinstance(login, dict):
        passkeys = [
            k
            for s in sources
            for k in (s.get("login") or {}).get("fido2Credentials") or []
            if isinstance(k, dict)
        ]
        login["fido2Credentials"] = union(
            passkeys, lambda k: k.get("credentialId") or repr(sorted(k.items()))
        )
        urls = result.get("URLs", "").split() or ([result["URL"]] if result.get("URL") else [])
        login["uris"] = merged_uri_objects(ordered, urls)
    # Eigene Felder mit ihren Typen von dem Mitglied, dessen Text im Ergebnis steht
    for source in sources:
        if canonical_fields(source.get("fields")) == result.get("Fields", ""):
            merged["fields"] = copy.deepcopy(source.get("fields"))
            break
    return merged


def merge_notes(rows):
    """Daten, die sich beim Zusammenführen nicht vereinen lassen (für die Meldung)."""
    organizations = {
        s.get("organizationId")
        for s in (row.get(SOURCE_KEY) for row in rows)
        if isinstance(s, dict) and s.get("organizationId")
    }
    return (
        ["Organisation (die Einträge gehören zu verschiedenen)"] if len(organizations) > 1 else []
    )


def newest_first(rows):
    """Die Nummern der Zeilen, die zuletzt geänderte zuerst (bei Gleichstand die spätere)."""
    return sorted(range(len(rows)), key=lambda i: (modified_at(rows[i]), i), reverse=True)


def merge_rows(rows, picks=None):
    """Führt Zeilen zu einer zusammen. Rückgabe: (zeile, spalten_mit_konflikt)."""
    picks = picks or {}
    order = newest_first(rows)
    ordered = [rows[i] for i in order]
    result = dict(ordered[0])
    conflicts = []

    for column in ALL_NAMES:
        if column in (MODIFIED, CREATED, "URLs") or column not in result:
            continue
        values = [row.get(column, "") for row in ordered]
        found = distinct_values(column, values)
        if column == "Type":  # „login“ gilt als Standardwert, ist hier aber ein echter Wert
            found = union([v for v in values if v], lambda v: v)
        if column in CONFLICT_COLUMNS and len(found) > 1:
            conflicts.append(column)
        if column in picks:
            pick = picks[column]
            if pick == BOTH:
                if column not in JOIN_SEPARATORS:
                    raise ValueError(
                        f"Die Werte der Spalte '{column}' lassen sich nicht verbinden."
                    )
                result[column] = JOIN_SEPARATORS[column].join(found)
            else:
                result[column] = rows[pick].get(column, "")
        elif column in ANY_WINS_COLUMNS:
            result[column] = "1" if "1" in values else result[column]
        elif column == "Type":
            result[column] = result[column] or (found[0] if found else "")
        elif is_empty(column, result[column]) and found:
            result[column] = found[0]

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

    source = merge_sources(ordered, result)
    if source is not None:
        result[SOURCE_KEY] = source
    labels = union([label for row in ordered for label in row.get(UNMAPPED_KEY) or []], lambda x: x)
    if UNMAPPED_KEY in result:
        result[UNMAPPED_KEY] = labels
    return result, conflicts


class MergedGroup(NamedTuple):
    group: object  # die DuplicateGroup
    action: str
    conflicts: tuple  # Spalten mit verschiedenen Werten (auch wenn entschieden wurde)
    kept: tuple  # Schlüssel der Einträge, die in der Datei bleiben, oder ()
    notes: tuple = ()  # Daten, die sich nicht vereinen ließen


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


def is_index(value, size):
    """Eine gültige Mitgliedsnummer (``True``/``False`` zählen nicht als Zahl)."""
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value < size


def check_decisions(groups, decisions):
    """Wirft ``ValueError`` bei unbekannten Gruppen oder ungültigen Entscheidungen."""
    by_id = {group.id: group for group in groups}
    for group_id, decision in (decisions or {}).items():
        group = by_id.get(group_id)
        if group is None:
            raise ValueError(
                "Die Entscheidungen passen nicht zur Datei (unbekannte Dublettengruppe). "
                "Bitte neu auswerten."
            )
        if decision.action not in ACTIONS:
            raise ValueError(f"Unbekannte Aktion '{decision.action}'.")
        size = len(group.keys)
        if decision.action == KEEP_ONE and not is_index(decision.keep, size):
            raise ValueError("Das zu behaltende Mitglied gibt es nicht.")
        for column, pick in (decision.picks or {}).items():
            if column not in CONFLICT_COLUMNS:
                raise ValueError(f"Für die Spalte '{column}' kann nichts gewählt werden.")
            if pick == BOTH:
                if column not in JOIN_SEPARATORS:
                    raise ValueError(
                        f"Die Werte der Spalte '{column}' lassen sich nicht verbinden."
                    )
            elif not is_index(pick, size):
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
            row, conflicts = merge_rows(members, decision.picks or {})
            rows.append(row)
            removed += len(members) - 1
            merged.append(
                MergedGroup(group, MERGE, tuple(conflicts), (), tuple(merge_notes(members)))
            )
    trash = sum(1 for row in entries.values() if is_trash(row))
    rows.sort(key=lambda row: (row["Group"], row["Title"], row["Username"]))
    return Cleaned(rows, merged, removed, trash)
