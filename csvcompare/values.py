"""Werte inhaltlich vergleichen und normalisieren (Zeiten, TOTP, Leerraum)."""

import re
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

from .columns import TIME_NAMES

# Zeitformate, die zusätzlich zu ISO 8601 gelesen werden
TIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%d.%m.%Y %H:%M:%S",
    "%d.%m.%Y %H:%M",
    "%d.%m.%Y",
    "%Y-%m-%d",
    "%m/%d/%Y %H:%M:%S",
)


NAIVE_TIME = re.compile(r"^\d{4}-\d\d-\d\d[T ]\d\d:\d\d(:\d\d(\.\d+)?)?$")


def has_naive_time(text):
    """Ist es eine Zeitangabe ohne Zeitzone (die als UTC gelesen wird)?"""
    return bool(NAIVE_TIME.match((text or "").strip()))


def parse_time(text):
    """Zeitangabe -> aware datetime (UTC) oder None, wenn sie nicht lesbar ist."""
    text = (text or "").strip()
    if not text:
        return None
    moment = None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        for fmt in TIME_FORMATS:
            try:
                moment = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
    if moment is None:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def normalize_time(text):
    """Zeit als ``YYYY-MM-DDTHH:MM:SSZ`` (UTC); nicht lesbare Werte bleiben unverändert."""
    moment = parse_time(text)
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if moment else text


def collapse_whitespace(text):
    """Mehrfache Leerzeichen, Tabs und Zeilenumbrüche zu einem Leerzeichen zusammenfassen."""
    return " ".join((text or "").split())


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
    return (
        secret,
        params.get("digits", "6"),
        params.get("period", "30"),
        params.get("algorithm", "SHA1").upper(),
    )


def values_equal(column, a, b):
    """Vergleicht zwei Zellwerte inhaltlich statt zeichengenau.

    Zeiten gelten als gleich, wenn sie zur selben Sekunde gehören (egal in welcher
    Schreibweise); TOTP-Werte, wenn sie dasselbe Einmalpasswort ergeben. Alles andere
    wird genau verglichen.
    """
    if a == b:
        return True
    if column in TIME_NAMES:
        time_a, time_b = parse_time(a), parse_time(b)
        return (
            time_a is not None
            and time_b is not None
            and time_a.replace(microsecond=0) == time_b.replace(microsecond=0)
        )
    if column == "TOTP":
        key_a, key_b = totp_key(a), totp_key(b)
        return key_a is not None and key_a == key_b
    return False


def differing_columns(row_a, row_b, columns):
    """Spalten aus ``columns``, in denen sich beide Zeilen inhaltlich unterscheiden."""
    return [c for c in columns if not values_equal(c, row_a[c], row_b[c])]
