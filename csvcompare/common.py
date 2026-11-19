"""Kleine Hilfsfunktionen für Zeitstempel, Beschriftung und Filter."""

from datetime import datetime, timezone
import os
from urllib.parse import parse_qs, urlsplit

from .constants import EXCLUDE_GROUP_PATTERNS, TS_FORMATS

TIME_COLUMNS = ("Last Modified", "Created")


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


def totp_key(value):
    """Vergleichbare Form eines TOTP-Werts: (Secret, Stellen, Periode, Algorithmus).

    Ein otpauth://-Link und das reine Secret gelten als gleich, wenn sie dasselbe
    Einmalpasswort erzeugen (Groß-/Kleinschreibung, Leerzeichen und Bindestriche im
    Secret spielen keine Rolle).
    """
    value = (value or "").strip()
    if not value:
        return None
    params = {}
    secret = value
    if value.lower().startswith("otpauth://"):
        params = {k.lower(): v[0] for k, v in parse_qs(urlsplit(value).query).items()}
        secret = params.get("secret", "")
    secret = "".join(secret.split()).replace("-", "").upper()
    return (secret, params.get("digits", "6"), params.get("period", "30"),
            params.get("algorithm", "SHA1").upper())


def values_equal(col, a, b):
    """Vergleicht zwei Zellwerte inhaltlich statt zeichengenau.

    Zeiten gelten als gleich, wenn sie zur selben Sekunde gehören (egal in welcher
    Schreibweise); TOTP-Werte, wenn sie dasselbe Einmalpasswort ergeben. Alles andere
    wird genau verglichen.
    """
    if a == b:
        return True
    if col in TIME_COLUMNS:
        ta, tb = parse_ts(a), parse_ts(b)
        return ta is not None and tb is not None and ta.replace(microsecond=0) == tb.replace(microsecond=0)
    if col == "TOTP":
        ka, kb = totp_key(a), totp_key(b)
        return ka is not None and ka == kb
    return False


def differing_columns(row_a, row_b, columns):
    """Spalten aus columns, in denen sich beide Zeilen inhaltlich unterscheiden."""
    return [c for c in columns if not values_equal(c, row_a[c], row_b[c])]


def normalize_timestamp(value):
    """Zeit als ``YYYY-MM-DDTHH:MM:SSZ`` (UTC); nicht lesbare Werte bleiben unverändert."""
    dt = parse_ts(value)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if dt else value


def collapse_whitespace(value):
    """Mehrfache Leerzeichen, Tabs und Zeilenumbrüche zu einem Leerzeichen zusammenfassen."""
    return " ".join((value or "").split())
