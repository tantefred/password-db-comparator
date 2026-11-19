"""Spaltendefinitionen und Konfiguration."""

from .columns import SECRET_NAMES

KEY_COLS = ("Group", "Title", "Username")
SECRET_COLS = SECRET_NAMES
TIME_COL = "Last Modified"
EXPECTED = ["Group", "Title", "Username", "Password", "URL", "Notes",
            "TOTP", "Icon", "Last Modified", "Created"]
# Einträge in Gruppen, deren Pfad eines dieser Muster enthält, werden nicht exportiert
EXCLUDE_GROUP_PATTERNS = ("papierkorb", "recycle bin")

TS_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d.%m.%Y %H:%M:%S",
              "%d.%m.%Y %H:%M", "%d.%m.%Y", "%Y-%m-%d", "%m/%d/%Y %H:%M:%S")
