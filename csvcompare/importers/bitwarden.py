"""Bitwarden/Vaultwarden-Exporte (unverschlüsseltes JSON; CSV folgt).

Es werden alle Felder erfasst, nicht nur die, die KeePass kennt: Favorit, Typ, Nachfrage,
eigene Felder und alle URLs landen in eigenen Spalten, und der unveränderte Originaleintrag
steckt in ``SOURCE_KEY`` (mit ``id``, ``collectionIds``, ``passwordHistory`` usw.), damit ein
späterer Export in Bitwarden-Formate nichts verliert.
"""

import json

from ..columns import ALL_NAMES, SOURCE_KEY
from ..common import collapse_whitespace, normalize_timestamp
from .base import CsvError, LoadResult

FORMAT_JSON = "bitwarden-json"

# Diese Spalten liefert Bitwarden; ein Icon gibt es nicht.
PROVIDED = frozenset(ALL_NAMES) - {"Icon"}

TYPE_LOGIN, TYPE_NOTE = 1, 2
SKIPPED_TYPE_NAMES = {3: ("Karte", "Karten"), 4: ("Identität", "Identitäten"),
                      5: ("SSH-Schlüssel", "SSH-Schlüssel")}
TRASH_GROUP = "Papierkorb"


def text(value):
    """Beliebigen JSON-Wert als Text; ``None`` wird zu einer leeren Zeichenkette."""
    return "" if value is None else str(value)


def canonical_fields(fields):
    """Eigene Felder als ``Name: Wert Name: Wert`` mit vereinheitlichten Leerzeichen.

    Dieselbe Form liefert die CSV-Spalte ``fields``, so lassen sich beide vergleichen.
    """
    parts = [f"{text(f.get('name'))}: {text(f.get('value'))}"
             for f in (fields or []) if isinstance(f, dict)]
    return collapse_whitespace(" ".join(parts))


def empty_row():
    return {name: "" for name in ALL_NAMES}


def plural_names(counts):
    parts = []
    for type_id, n in sorted(counts.items()):
        one, many = SKIPPED_TYPE_NAMES.get(type_id, (f"Typ {type_id}", f"Typ {type_id}"))
        parts.append(f"{n} {one if n == 1 else many}")
    return ", ".join(parts)


def parse_json(text_, name):
    """Liest einen unverschlüsselten Bitwarden/Vaultwarden-JSON-Export."""
    try:
        data = json.loads(text_)
    except json.JSONDecodeError as e:
        raise CsvError(f"'{name}' ist kein gültiges JSON (Zeile {e.lineno}, "
                       f"Spalte {e.colno}).") from None
    if isinstance(data, dict) and data.get("encrypted") is True:
        raise CsvError(f"'{name}' ist ein verschlüsselter Bitwarden-Export und kann nicht "
                       f"gelesen werden. Exportiere unverschlüsselt als .json oder .csv.")
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise CsvError(f"'{name}' sieht nicht wie ein Bitwarden/Vaultwarden-Export aus "
                       f"(das Feld „items“ fehlt).")

    folders = {f.get("id"): text(f.get("name")) for f in data.get("folders") or []
               if isinstance(f, dict)}
    rows, skipped, deleted = [], {}, 0
    for item in data["items"]:
        if not isinstance(item, dict):
            continue
        type_id = item.get("type")
        if type_id not in (TYPE_LOGIN, TYPE_NOTE):
            skipped[type_id] = skipped.get(type_id, 0) + 1
            continue
        login = item.get("login") if isinstance(item.get("login"), dict) else {}
        uris = [text(u.get("uri")) for u in login.get("uris") or []
                if isinstance(u, dict) and u.get("uri")]

        row = empty_row()
        row["Group"] = folders.get(item.get("folderId"), "")
        row["Title"] = text(item.get("name"))
        row["Username"] = text(login.get("username"))
        row["Password"] = text(login.get("password"))
        row["URL"] = uris[0] if uris else ""
        row["URLs"] = "\n".join(uris)
        row["Notes"] = text(item.get("notes"))
        row["TOTP"] = text(login.get("totp"))
        row["Last Modified"] = normalize_timestamp(text(item.get("revisionDate")))
        row["Created"] = normalize_timestamp(text(item.get("creationDate")))
        row["Favorite"] = "1" if item.get("favorite") else "0"
        row["Type"] = "login" if type_id == TYPE_LOGIN else "note"
        row["Reprompt"] = "1" if item.get("reprompt") else "0"
        row["Fields"] = canonical_fields(item.get("fields"))
        if item.get("deletedDate"):
            row["Group"] = TRASH_GROUP  # Bitwarden hat keine Papierkorb-Gruppe
            deleted += 1
        row[SOURCE_KEY] = item
        rows.append(row)

    notes = []
    if skipped:
        n = sum(skipped.values())
        notes.append(f"{n} {'Eintrag' if n == 1 else 'Einträge'} übersprungen "
                     f"({plural_names(skipped)}); verglichen werden Logins und sichere Notizen.")
    if deleted:
        subject = ("1 gelöschter Eintrag ist" if deleted == 1
                   else f"{deleted} gelöschte Einträge sind")
        notes.append(f"{subject} enthalten und steht in der Gruppe „{TRASH_GROUP}“."
                     if deleted == 1 else
                     f"{subject} enthalten und stehen in der Gruppe „{TRASH_GROUP}“.")
    return LoadResult(rows=rows, format=FORMAT_JSON, provided_columns=PROVIDED, notes=notes)
