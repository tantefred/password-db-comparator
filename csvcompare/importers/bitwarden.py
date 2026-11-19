"""Bitwarden/Vaultwarden-Exporte (unverschlüsseltes JSON und CSV).

Es werden alle Felder erfasst, nicht nur die, die KeePass kennt: Favorit, Typ, Nachfrage,
eigene Felder und alle URLs landen in eigenen Spalten, und der unveränderte Originaleintrag
steckt in ``SOURCE_KEY`` (mit ``id``, ``collectionIds``, ``passwordHistory`` usw.), damit ein
späterer Export in Bitwarden-Formate nichts verliert.
"""

import csv
import io
import json

from ..columns import ALL_NAMES, SOURCE_KEY, UNMAPPED_KEY
from ..display import plural
from ..values import collapse_whitespace, normalize_time
from .base import BITWARDEN_CSV, BITWARDEN_JSON, CsvError, LoadResult

# Diese Spalten liefert Bitwarden; ein Icon gibt es nicht.
PROVIDED_JSON = frozenset(ALL_NAMES) - {"Icon"}
# Das CSV enthält zusätzlich keine Zeitstempel.
PROVIDED_CSV = PROVIDED_JSON - {"Last Modified", "Created"}

NO_TIMESTAMPS_NOTE = ("Dieser Export enthält keine Zeitstempel; bei Änderungen lässt sich "
                      "nicht sagen, welche Datei aktueller ist.")
TRASH_GROUP = "Papierkorb"  # Bitwarden hat keine Papierkorb-Gruppe, nur ein Löschdatum

# Eintragstypen im JSON; alle anderen werden übersprungen
TYPE_LOGIN, TYPE_NOTE = 1, 2
SKIPPED_TYPE_NAMES = {3: ("Karte", "Karten"), 4: ("Identität", "Identitäten"),
                      5: ("SSH-Schlüssel", "SSH-Schlüssel")}

CSV_DETECT_COLUMNS = ("login_uri", "login_username")
CSV_KNOWN_COLUMNS = ("folder", "favorite", "type", "name", "notes", "fields", "reprompt",
                     "login_uri", "login_username", "login_password", "login_totp")


def as_text(value):
    """Beliebigen JSON-Wert als Text; ``None`` wird zu einer leeren Zeichenkette."""
    return "" if value is None else str(value)


def is_set(value):
    """Ist ein Schalter im Export gesetzt? (JSON: true/1, CSV: ``1``/``true``)"""
    return str(value).strip().lower() in ("1", "true")


def canonical_fields(fields):
    """Eigene Felder als ``Name: Wert Name: Wert`` mit vereinheitlichten Leerzeichen.

    Dieselbe Form liefert die CSV-Spalte ``fields``, so lassen sich beide vergleichen.
    """
    parts = [f"{as_text(field.get('name'))}: {as_text(field.get('value'))}"
             for field in (fields or []) if isinstance(field, dict)]
    return collapse_whitespace(" ".join(parts))


def make_row(source, unmapped, *, group, title, username, password, uris, notes, totp,
             favorite, kind, reprompt, fields, modified="", created=""):
    """Eine Zeile mit allen Spalten; was ein Format nicht liefert, bleibt leer."""
    row = dict.fromkeys(ALL_NAMES, "")
    row.update({
        "Group": group, "Title": title, "Username": username, "Password": password,
        "URL": uris[0] if uris else "", "URLs": "\n".join(uris),
        "Notes": notes, "TOTP": totp,
        "Last Modified": modified, "Created": created,
        "Favorite": "1" if favorite else "0", "Type": kind,
        "Reprompt": "1" if reprompt else "0", "Fields": fields,
        SOURCE_KEY: source, UNMAPPED_KEY: unmapped,
    })
    return row


def skipped_note(total, description):
    return (f"{plural(total, 'Eintrag', 'Einträge')} übersprungen ({description}); "
            f"verglichen werden Logins und sichere Notizen.")


# ---------------------------------------------------------------- JSON

def unmapped_json_item(item):
    """Bezeichnungen der Daten eines Bitwarden-Eintrags, die in keiner Spalte landen."""
    login = item.get("login") if isinstance(item.get("login"), dict) else {}
    fields = item.get("fields") or []
    uris = login.get("uris") or []
    labels = []
    if item.get("passwordHistory"):
        labels.append("Passwort-Verlauf")
    if login.get("fido2Credentials"):
        labels.append("Passkeys")
    if item.get("collectionIds"):
        labels.append("Sammlungen")
    if item.get("organizationId"):
        labels.append("Organisation")
    if any(isinstance(f, dict) and f.get("type") not in (None, 0) for f in fields):
        labels.append("Typ eigener Felder")
    if any(isinstance(u, dict) and u.get("match") is not None for u in uris):
        labels.append("URL-Abgleichsmodus")
    if item.get("deletedDate"):
        labels.append("Löschdatum")
    return labels


def json_row(item, folders):
    """Die Zeile zu einem Login oder einer sicheren Notiz aus dem JSON-Export."""
    login = item.get("login") if isinstance(item.get("login"), dict) else {}
    uris = [as_text(uri.get("uri")) for uri in login.get("uris") or []
            if isinstance(uri, dict) and uri.get("uri")]
    deleted = bool(item.get("deletedDate"))
    return make_row(
        item, unmapped_json_item(item),
        group=TRASH_GROUP if deleted else folders.get(item.get("folderId"), ""),
        title=as_text(item.get("name")), username=as_text(login.get("username")),
        password=as_text(login.get("password")), uris=uris, notes=as_text(item.get("notes")),
        totp=as_text(login.get("totp")), favorite=item.get("favorite"),
        kind="login" if item.get("type") == TYPE_LOGIN else "note",
        reprompt=item.get("reprompt"), fields=canonical_fields(item.get("fields")),
        modified=normalize_time(as_text(item.get("revisionDate"))),
        created=normalize_time(as_text(item.get("creationDate"))))


def parse_json(content, name):
    """Liest einen unverschlüsselten Bitwarden/Vaultwarden-JSON-Export."""
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        raise CsvError(f"'{name}' ist kein gültiges JSON (Zeile {e.lineno}, "
                       f"Spalte {e.colno}).") from None
    if isinstance(data, dict) and data.get("encrypted") is True:
        raise CsvError(f"'{name}' ist ein verschlüsselter Bitwarden-Export und kann nicht "
                       f"gelesen werden. Exportiere unverschlüsselt als .json oder .csv.")
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise CsvError(f"'{name}' sieht nicht wie ein Bitwarden/Vaultwarden-Export aus "
                       f"(das Feld „items“ fehlt).")

    folders = {folder.get("id"): as_text(folder.get("name"))
               for folder in data.get("folders") or [] if isinstance(folder, dict)}
    rows, skipped_by_type, deleted = [], {}, 0
    for item in data["items"]:
        if not isinstance(item, dict):
            continue
        if item.get("type") not in (TYPE_LOGIN, TYPE_NOTE):
            skipped_by_type[item.get("type")] = skipped_by_type.get(item.get("type"), 0) + 1
            continue
        rows.append(json_row(item, folders))
        deleted += bool(item.get("deletedDate"))

    notes = []
    if skipped_by_type:
        names = []
        for type_id, count in sorted(skipped_by_type.items()):
            one, many = SKIPPED_TYPE_NAMES.get(type_id, (f"Typ {type_id}",) * 2)
            names.append(f"{count} {one if count == 1 else many}")
        notes.append(skipped_note(sum(skipped_by_type.values()), ", ".join(names)))
    if deleted == 1:
        notes.append(f"1 gelöschter Eintrag ist enthalten und steht in der Gruppe „{TRASH_GROUP}“.")
    elif deleted:
        notes.append(f"{deleted} gelöschte Einträge sind enthalten und stehen in der Gruppe "
                     f"„{TRASH_GROUP}“.")
    return LoadResult(rows=rows, format=BITWARDEN_JSON, provided_columns=PROVIDED_JSON,
                      notes=notes)


# ---------------------------------------------------------------- CSV

def is_csv(header):
    """Erkennt die Kopfzeile eines Bitwarden-CSV-Exports."""
    return all(column in header for column in CSV_DETECT_COLUMNS)


def unmapped_csv_row(source):
    """Bezeichnungen zusätzlicher CSV-Spalten mit Inhalt (z. B. ``collections`` in Organisationen)."""
    return [f"Spalte „{key}“" for key, value in source.items()
            if key is not None and key not in CSV_KNOWN_COLUMNS and value]


def csv_row(source, kind):
    """Die Zeile zu einer CSV-Zeile des Exports (``kind``: login oder note)."""
    return make_row(
        dict(source), unmapped_csv_row(source),
        group=as_text(source.get("folder")), title=as_text(source.get("name")),
        username=as_text(source.get("login_username")),
        password=as_text(source.get("login_password")),
        uris=(source.get("login_uri") or "").split(),  # mehrere URIs: eine pro Zeile
        notes=as_text(source.get("notes")), totp=as_text(source.get("login_totp")),
        favorite=is_set(as_text(source.get("favorite"))), kind=kind,
        reprompt=is_set(as_text(source.get("reprompt"))),
        fields=collapse_whitespace(as_text(source.get("fields"))))


def parse_csv(content, name):
    """Liest einen unverschlüsselten Bitwarden/Vaultwarden-CSV-Export (Logins und Notizen).

    Die Spalte ``fields`` steht dort als ``Name: Wert Name: Wert`` (durch Leerzeichen getrennt)
    und lässt sich nicht eindeutig zerlegen; sie wird deshalb nur mit vereinheitlichten
    Leerzeichen als Text verglichen. Das Original bleibt in ``SOURCE_KEY``.
    """
    rows, skipped_by_kind = [], {}
    for source in csv.DictReader(io.StringIO(content, newline="")):
        kind = (source.get("type") or "login").strip().lower()
        if kind in ("login", "note"):
            rows.append(csv_row(source, kind))
        else:
            skipped_by_kind[kind] = skipped_by_kind.get(kind, 0) + 1

    notes = []
    if skipped_by_kind:
        names = ", ".join(f"{count} {kind}" for kind, count in sorted(skipped_by_kind.items()))
        notes.append(skipped_note(sum(skipped_by_kind.values()), names))
    notes.append(NO_TIMESTAMPS_NOTE)
    return LoadResult(rows=rows, format=BITWARDEN_CSV, provided_columns=PROVIDED_CSV, notes=notes)
