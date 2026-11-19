"""Alle Spalten, die die unterstützten Formate kennen.

Die ersten zehn sind das KeePass-CSV-Format (KeePassium/KeePassXC). Die weiteren stammen
aus Bitwarden/Vaultwarden. Jede Zeile eines eingelesenen Eintrags enthält alle diese
Spalten (nicht gelieferte bleiben leer); welche ein Format wirklich liefert, steht in
``LoadResult.provided_columns``. Den unveränderten Originaleintrag trägt die Zeile unter
``SOURCE_KEY``, damit spätere Exporte auch Daten ausgeben können, die nicht verglichen werden.
"""

from dataclasses import dataclass

SOURCE_KEY = "_source"
# Bezeichnungen für Daten des Originaleintrags, die in keiner Spalte stehen (z. B.
# „Passwort-Verlauf“). Wird beim Einlesen gefüllt und von Exporten gemeldet.
UNMAPPED_KEY = "_unmapped"


@dataclass(frozen=True)
class Column:
    name: str
    label: str                # deutsche Beschriftung für Oberfläche und Berichte
    secret: bool = False      # Werte werden ohne --show-secrets nicht angezeigt
    defaults: tuple = ("",)   # Werte, die „keine Daten“ bedeuten (für die Verlustmeldung)


CORE = (
    Column("Group", "Gruppe"),
    Column("Title", "Titel"),
    Column("Username", "Username"),
    Column("Password", "Passwort", secret=True),
    Column("URL", "URL"),
    Column("Notes", "Notizen"),
    Column("TOTP", "TOTP", secret=True),
    Column("Icon", "Icon"),
    Column("Last Modified", "Geändert am"),
    Column("Created", "Erstellt am"),
)

EXTENDED = (
    Column("Favorite", "Favorit", defaults=("", "0")),
    Column("Type", "Typ", defaults=("", "login")),
    Column("Reprompt", "Passwort-Nachfrage", defaults=("", "0")),
    # Im CSV-Export ist nicht erkennbar, welche Felder „verborgen“ sind: alles gilt als geheim.
    Column("Fields", "Eigene Felder", secret=True),
    Column("URLs", "Alle URLs"),
)

ALL_COLUMNS = CORE + EXTENDED
BY_NAME = {c.name: c for c in ALL_COLUMNS}
LABELS = {c.name: c.label for c in ALL_COLUMNS}

CORE_NAMES = tuple(c.name for c in CORE)      # die Spalten des KeePass-CSV
ALL_NAMES = tuple(c.name for c in ALL_COLUMNS)
SECRET_NAMES = tuple(c.name for c in ALL_COLUMNS if c.secret)

# Die Spalten, über die ein Eintrag zugeordnet wird; sie lassen sich nicht ignorieren.
KEY_NAMES = ("Group", "Title", "Username")
# Alle übrigen Spalten (das, was verglichen oder ignoriert werden kann).
VALUE_NAMES = tuple(n for n in ALL_NAMES if n not in KEY_NAMES)

MODIFIED, CREATED = "Last Modified", "Created"
TIME_NAMES = (MODIFIED, CREATED)
