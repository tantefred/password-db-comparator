"""Dublettengruppen in einer Datei: was zusammengehört und worin sich die Einträge unterscheiden.

Es gibt drei Arten. Ein Eintrag gehört höchstens einer Gruppe, und zwar der stärksten Art:

- ``key``: gleiche Gruppe, gleicher Titel, gleicher Username (sicher dieselbe Sache)
- ``login``: gleiche URL und gleicher Username (meist dasselbe Konto)
- ``title``: gleicher Titel und Username in verschiedenen Gruppen (nur ein Hinweis)

Einträge im Papierkorb zählen nicht.
"""

import hashlib
from collections import defaultdict
from typing import NamedTuple

from .columns import ALL_NAMES, KEY_NAMES
from .entries import is_trash
from .values import values_equal

KEY, LOGIN, TITLE = "key", "login", "title"
KINDS = (KEY, LOGIN, TITLE)  # von der stärksten zur schwächsten Art
KIND_LABELS = {
    KEY: "Identischer Schlüssel (Gruppe, Titel, Username)",
    LOGIN: "Gleicher Login (URL und Username)",
    TITLE: "Gleicher Titel und Username in anderen Gruppen",
}
# Diese Spalten sagen nichts darüber, ob sich Einträge inhaltlich unterscheiden
IGNORED_FOR_DIFFERENCES = ("Last Modified", "Created", "URLs")


class DuplicateGroup(NamedTuple):
    id: str  # stabil: hängt nur von Art und Mitgliedern ab
    kind: str
    reason: str
    keys: tuple  # die Mitglieder, sortiert
    differing: tuple  # Spalten, in denen sich die Mitglieder unterscheiden


def normalized_url(row):
    return row["URL"].strip().lower().rstrip("/")


def bucket_id(kind, keys):
    text = kind + "\n" + "\n".join(repr(tuple(key)) for key in keys)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]


def differing_columns(rows):
    """Die Spalten, in denen sich mindestens zwei der Zeilen inhaltlich unterscheiden."""
    return tuple(
        column
        for column in ALL_NAMES
        if column not in IGNORED_FOR_DIFFERENCES
        and column not in KEY_NAMES
        and any(
            not values_equal(column, rows[0].get(column, ""), row.get(column, ""))
            for row in rows[1:]
        )
    )


def bucket_key(kind, key, row):
    """Wonach Einträge der Art ``kind`` zusammengefasst werden; ``None`` = zählt nicht."""
    if kind == KEY:
        return key.identity
    if kind == LOGIN:
        url = normalized_url(row)
        return (url, key.username.lower()) if url and key.username else None
    return (key.title.lower(), key.username.lower()) if key.title and key.username else None


def reason_for(kind, bucket):
    if kind == LOGIN:
        return f"{KIND_LABELS[kind]}: {bucket[0]} [{bucket[1]}]"
    if kind == TITLE:
        return f"{KIND_LABELS[kind]}: {bucket[0]} [{bucket[1]}]"
    return KIND_LABELS[kind]


def find_duplicates(entries, kinds=KINDS):
    """Alle Dublettengruppen der gewünschten Arten, stärkste Art zuerst."""
    taken = set()
    groups = []
    for kind in (k for k in KINDS if k in kinds):
        buckets = defaultdict(list)
        for key, row in entries.items():
            if key in taken or is_trash(row):
                continue
            bucket = bucket_key(kind, key, row)
            if bucket is not None:
                buckets[bucket].append(key)
        for bucket, keys in sorted(buckets.items()):
            keys = sorted(keys)
            if len(keys) < 2:
                continue
            if kind == TITLE and len({key.group for key in keys}) < 2:
                continue
            taken.update(keys)
            rows = [entries[key] for key in keys]
            groups.append(
                DuplicateGroup(
                    bucket_id(kind, keys),
                    kind,
                    reason_for(kind, bucket),
                    tuple(keys),
                    differing_columns(rows),
                )
            )
    return groups
