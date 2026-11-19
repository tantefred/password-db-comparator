"""Kleine Hilfsfunktionen für Zeitstempel, Beschriftung und Filter."""

from datetime import datetime, timezone
import os

from .constants import EXCLUDE_GROUP_PATTERNS, TS_FORMATS


def parse_ts(s):
    """Zeitstempel -> aware datetime (UTC) oder None, wenn nicht lesbar."""
    s = (s or "").strip()
    if not s:
        return None
    dt = None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        for fmt in TS_FORMATS:
            try:
                dt = datetime.strptime(s, fmt)
                break
            except ValueError:
                pass
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def human_delta(seconds):
    seconds = int(abs(seconds))
    for unit, size in (("Tag(e)", 86400), ("Stunde(n)", 3600), ("Minute(n)", 60)):
        if seconds >= size:
            return f"{seconds // size} {unit}"
    return f"{seconds} Sekunde(n)"


def label(key):
    group, title, user, n = key
    s = f"{group or '(ohne Gruppe)'} / {title or '(ohne Titel)'}"
    if user:
        s += f"  [{user}]"
    if n > 1:
        s += f"  #{n}"
    return s


def short(value, secret, show_secrets):
    if secret and not show_secrets:
        return "(gesetzt)" if value else "(leer)"
    value = value.replace("\r", "").replace("\n", " ⏎ ")
    if len(value) > 80:
        value = value[:77] + "..."
    return repr(value) if value == "" else value


def is_excluded(row):
    g = row["Group"].lower()
    return any(p in g for p in EXCLUDE_GROUP_PATTERNS)


def display_names(path1, path2):
    """Dateinamen für die Ausgabe; bei gleichem Namen der volle Pfad."""
    n1, n2 = os.path.basename(path1), os.path.basename(path2)
    return (path1, path2) if n1 == n2 else (n1, n2)
