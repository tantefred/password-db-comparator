"""Darstellung von Werten für Menschen: Maskierung, Zeitabstände, Dateinamen."""

import os


def mask_secret(value):
    """Zeigt nur, ob ein geheimer Wert gesetzt ist, nie den Wert selbst."""
    return "(gesetzt)" if value else "(leer)"


def display_value(value, secret, show_secrets):
    """Wert einzeilig und gekürzt für die Textausgabe; Geheimnisse werden maskiert."""
    if secret and not show_secrets:
        return mask_secret(value)
    value = value.replace("\r", "").replace("\n", " ⏎ ")
    if len(value) > 80:
        value = value[:77] + "..."
    return repr(value) if value == "" else value


def human_delta(seconds):
    """Zeitabstand als größte passende Einheit, z. B. ``3 Tag(e)``."""
    seconds = int(abs(seconds))
    for unit, size in (("Tag(e)", 86400), ("Stunde(n)", 3600), ("Minute(n)", 60)):
        if seconds >= size:
            return f"{seconds // size} {unit}"
    return f"{seconds} Sekunde(n)"


def display_names(path_old, path_new):
    """Dateinamen für die Ausgabe; bei gleichem Namen der volle Pfad."""
    name_old, name_new = os.path.basename(path_old), os.path.basename(path_new)
    return (path_old, path_new) if name_old == name_new else (name_old, name_new)


def plural(count, one, many):
    """``1 Eintrag`` / ``3 Einträge``."""
    return f"{count} {one if count == 1 else many}"
