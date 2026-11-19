"""Spaltendefinitionen und Konfiguration."""

KEY_COLS = ("Group", "Title", "Username")
SECRET_COLS = ("Password", "TOTP")
TIME_COL = "Last Modified"
EXPECTED = ["Group", "Title", "Username", "Password", "URL", "Notes",
            "TOTP", "Icon", "Last Modified", "Created"]
# Einträge in Gruppen, deren Pfad eines dieser Muster enthält, werden nicht exportiert
EXCLUDE_GROUP_PATTERNS = ("papierkorb",)

TS_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d.%m.%Y %H:%M:%S",
              "%d.%m.%Y %H:%M", "%d.%m.%Y", "%Y-%m-%d", "%m/%d/%Y %H:%M:%S")
