"""Bitwarden/Vaultwarden-JSON (unverschlüsselt) als Zielformat.

Einträge, die aus einem Bitwarden-JSON stammen, werden aus ihrem Originaleintrag aufgebaut,
über den die aktuellen Spaltenwerte gelegt werden; so bleiben Passwort-Verlauf, Passkeys,
Sammlungen, Feldtypen und IDs erhalten. Alle anderen Einträge werden aus den Spalten neu
aufgebaut. Die Ausgabe ist deterministisch: Neue IDs werden aus dem Inhalt abgeleitet.
"""

import copy
import json
import uuid
from dataclasses import dataclass
from datetime import UTC

from ..columns import ALL_NAMES, FORMAT_KEY, OLD_PASSWORDS_KEY, SOURCE_KEY
from ..display import plural
from ..importers import BITWARDEN_CSV, BITWARDEN_JSON
from ..importers.bitwarden import TYPE_LOGIN, TYPE_NOTE, canonical_fields
from ..values import parse_time, values_equal
from .base import Writer

# Feste Grundlage für die abgeleiteten IDs (damit dieselbe Eingabe dieselbe Datei ergibt)
ID_NAMESPACE = uuid.UUID("6f1c0a52-3b7e-4c1e-9a53-2d0c8f4b7a10")

# Reihenfolge der Schlüssel eines neu aufgebauten Eintrags, wie Bitwarden sie schreibt
# (Einträge aus einem Bitwarden-JSON behalten die Reihenfolge ihres Originals)
NEW_ITEM_KEY_ORDER = (
    "passwordHistory",
    "revisionDate",
    "creationDate",
    "deletedDate",
    "id",
    "organizationId",
    "folderId",
    "type",
    "reprompt",
    "name",
    "notes",
    "favorite",
    "fields",
    "login",
    "secureNote",
    "collectionIds",
)


def stable_id(*parts):
    """Eine UUID, die nur vom Inhalt abhängt."""
    return str(uuid.uuid5(ID_NAMESPACE, "\x1f".join(parts)))


def json_time(value, source_value):
    """Zeit im JSON-Format von Bitwarden; ein gleichwertiger Originalwert bleibt erhalten."""
    if source_value and values_equal("Created", value, source_value):
        return source_value
    moment = parse_time(value)
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z") if moment else None


def row_urls(row):
    """Alle URLs eines Eintrags; die erste steht zusätzlich in der Spalte ``URL``."""
    urls = row.get("URLs", "").split()
    return urls or ([row["URL"]] if row.get("URL") else [])


def uris_for(urls, source_uris):
    """URIs für den Eintrag; gleichwertige Originale behalten ihren Abgleichsmodus."""
    original = [u["uri"] for u in source_uris if isinstance(u, dict) and u.get("uri")]
    if original == urls:
        return source_uris
    return [{"match": None, "uri": url} for url in urls]


def parse_fields(text):
    """Zerlegt den Text der Spalte ``fields`` in Felder. Rückgabe: (felder, sicher).

    Zeilenweise ``Name: Wert`` lässt sich sicher zerlegen. Steht alles in einer Zeile
    (``Name: Wert Name: Wert``), wird jedes Wort mit ``:`` am Ende als neuer Feldname gedeutet;
    Namen mit Leerzeichen lassen sich dann nicht erkennen.
    """
    fields = []
    if "\n" in text.strip():
        for line in filter(str.strip, text.splitlines()):
            name, _, value = line.partition(": ")
            fields.append((name.strip(), value.strip()))
        exact = True
    else:
        exact = False
        for word in text.split():
            if word.endswith(":") and len(word) > 1:
                fields.append((word[:-1], ""))
            elif fields:
                name, value = fields[-1]
                fields[-1] = (name, f"{value} {word}".strip())
    return [{"name": n, "value": v, "type": 0, "linkedId": None} for n, v in fields], exact


def raw_fields_text(row):
    """Text der eigenen Felder; beim Bitwarden-CSV mit den ursprünglichen Zeilenumbrüchen."""
    if row.get(FORMAT_KEY) == BITWARDEN_CSV:
        return row[SOURCE_KEY].get("fields") or ""
    return row.get("Fields", "")


def fields_for(row, source):
    """Eigene Felder des Eintrags; Original, wenn es dem Spaltenwert entspricht."""
    text = row.get("Fields", "")
    if source and canonical_fields(source.get("fields")) == text:
        return source.get("fields")
    return parse_fields(raw_fields_text(row))[0] or None


@dataclass(frozen=True)
class BitwardenJsonWriter(Writer):
    def keeps_source(self, row):
        return row.get(FORMAT_KEY) == BITWARDEN_JSON

    def notes(self, rows):
        guessed = sum(
            1
            for row in rows
            if row.get(FORMAT_KEY) == BITWARDEN_CSV
            and row.get("Fields")
            and not parse_fields(raw_fields_text(row))[1]
        )
        if not guessed:
            return []
        return [
            f"  Hinweis: Bei {plural(guessed, 'Eintrag', 'Einträgen')} wurden die eigenen Felder "
            f"aus dem Bitwarden-CSV nur geschätzt in Name und Wert zerlegt."
        ]

    def item(self, row, item_id, folder_id):
        """Ein Bitwarden-Eintrag zu einer Zeile."""
        source = row.get(SOURCE_KEY) if self.keeps_source(row) else None
        item = copy.deepcopy(source) if source else {}
        source_login = (source or {}).get("login")
        source_login = source_login if isinstance(source_login, dict) else {}
        is_note = row.get("Type") == "note"

        item.update(
            id=item_id,
            folderId=folder_id,
            type=TYPE_NOTE if is_note else TYPE_LOGIN,
            reprompt=1 if row.get("Reprompt") == "1" else 0,
            name=row["Title"],
            notes=row["Notes"] or None,
            favorite=row.get("Favorite") == "1",
            fields=fields_for(row, source),
            revisionDate=json_time(row["Last Modified"], (source or {}).get("revisionDate")),
            creationDate=json_time(row["Created"], (source or {}).get("creationDate")),
        )
        for key in ("organizationId", "collectionIds", "deletedDate", "passwordHistory"):
            item.setdefault(key, None)
        if row.get(OLD_PASSWORDS_KEY):
            added = [
                {"lastUsedDate": json_time(used, None), "password": password}
                for password, used in row[OLD_PASSWORDS_KEY]
            ]
            known = {entry["password"] for entry in added}
            kept = [
                entry
                for entry in item.get("passwordHistory") or []
                if not (isinstance(entry, dict) and entry.get("password") in known)
            ]
            item["passwordHistory"] = added + kept
        if is_note:
            item.pop("login", None)
            item.setdefault("secureNote", {"type": 0})
        else:
            item.pop("secureNote", None)
            item["login"] = {
                "fido2Credentials": [],
                **source_login,
                "uris": uris_for(row_urls(row), source_login.get("uris") or []),
                "username": row["Username"] or None,
                "password": row["Password"] or None,
                "totp": row["TOTP"] or None,
            }
        if source:
            return item
        ordered = {key: item[key] for key in NEW_ITEM_KEY_ORDER if key in item}
        return ordered | {key: value for key, value in item.items() if key not in ordered}

    def data(self, rows):
        """Der gesamte Export als Python-Objekt."""
        names = sorted({row["Group"] for row in rows if row["Group"]})
        folder_ids = {name: stable_id("folder", name) for name in names}
        items, used_ids, seen = [], set(), {}
        for row in rows:
            identity = (row["Group"], row["Title"], row["Username"])
            seen[identity] = seen.get(identity, 0) + 1
            item_id = (row.get(SOURCE_KEY) or {}).get("id") if self.keeps_source(row) else None
            if not item_id or item_id in used_ids:
                item_id = stable_id("item", *identity, str(seen[identity]))
            used_ids.add(item_id)
            items.append(self.item(row, item_id, folder_ids.get(row["Group"])))
        return {
            "encrypted": False,
            "folders": [{"id": folder_ids[name], "name": name} for name in names],
            "items": items,
        }

    def text(self, rows):
        return json.dumps(self.data(rows), ensure_ascii=False, indent=2) + "\n"


BITWARDEN_JSON_WRITER = BitwardenJsonWriter(
    format=BITWARDEN_JSON,
    label="Bitwarden-JSON",
    extension=".json",
    mime="application/json",
    columns=tuple(name for name in ALL_NAMES if name != "Icon"),
    stores_password_history=True,
)
