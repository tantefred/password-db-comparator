"""Auswertungen einzelner Dateien: Statistik, Prüfung auf Dubletten und Passwortqualität.

Alle Prüfungen geben nur Einträge aus, nie Passwörter.
"""

from collections import Counter, defaultdict
from datetime import UTC, datetime
from typing import NamedTuple
from urllib.parse import urlsplit

from .columns import MODIFIED
from .entries import entry_label
from .values import parse_time


class Finding(NamedTuple):
    """Ein Fund einer Prüfung: Überschrift und die betroffenen Einträge als Zeilen."""

    title: str
    lines: list


def stats_rows(old, new):
    """Einträge pro Gruppe in beiden Dateien: Liste (gruppe, anzahl_alt, anzahl_neu)."""
    count_old = Counter(row["Group"] for row in old.values())
    count_new = Counter(row["Group"] for row in new.values())
    return [
        (group, count_old[group], count_new[group])
        for group in sorted(set(count_old) | set(count_new))
    ]


# ---------------------------------------------------------------- Dubletten und kaputte Einträge


def url_problem(url):
    """Grund, falls die URL offensichtlich ungültig ist, sonst None."""
    url = url.strip()
    if not url:
        return None
    if any(char.isspace() for char in url):
        return "enthält Leerzeichen"
    host = urlsplit(url if "://" in url else "//" + url).hostname or ""
    if not host:
        return "kein Host erkennbar"
    if "." not in host and host != "localhost" and ":" not in host:
        return "Host ohne Punkt"
    return None


def duplicate_entries(entries):
    """Einträge mit gleicher Gruppe, gleichem Titel und gleichem Username."""
    keys_by_identity = defaultdict(list)
    for key in entries:
        keys_by_identity[key.identity].append(key)
    return sorted(
        f"{entry_label(keys[0])}  ({len(keys)}×)"
        for keys in keys_by_identity.values()
        if len(keys) > 1
    )


def same_title_in_several_groups(entries):
    """Gleicher Titel und Username (ohne Beachtung der Schreibweise) in verschiedenen Gruppen."""
    keys_by_title = defaultdict(list)
    for key in entries:
        if key.title and key.username:
            keys_by_title[(key.title.lower(), key.username.lower())].append(key)
    lines = []
    for keys in keys_by_title.values():
        groups = {key.group or "(ohne Gruppe)" for key in keys}
        if len({key.group for key in keys}) > 1:
            lines.append(f"{keys[0].title} [{keys[0].username}] in: " + ", ".join(sorted(groups)))
    return sorted(lines)


def same_url_and_user(entries):
    """Gleiche URL und gleicher Username in verschiedenen Einträgen."""
    keys_by_login = defaultdict(list)
    for key, row in entries.items():
        url = row["URL"].strip().lower().rstrip("/")
        if url and key.username:
            keys_by_login[(url, key.username.lower())].append(key)
    lines = []
    for (url, username), keys in keys_by_login.items():
        if len({key.identity for key in keys}) > 1:
            lines.append(f"{url} [{username}]: " + "; ".join(entry_label(key) for key in keys))
    return sorted(lines)


def entries_without_password(entries):
    return sorted(entry_label(key) for key, row in entries.items() if not row["Password"])


def entries_without_title(entries):
    return sorted(entry_label(key) for key in entries if not key.title)


def invalid_urls(entries):
    lines = []
    for key, row in sorted(entries.items()):
        reason = url_problem(row["URL"])
        if reason:
            lines.append(f"{entry_label(key)}: '{row['URL'].strip()}' ({reason})")
    return lines


CHECKS = (
    ("Doppelte Einträge (gleiche Gruppe, Titel und Username)", duplicate_entries),
    ("Gleicher Titel und Username in verschiedenen Gruppen", same_title_in_several_groups),
    ("Gleiche URL und Username in verschiedenen Einträgen", same_url_and_user),
    ("Einträge ohne Passwort", entries_without_password),
    ("Einträge ohne Titel", entries_without_title),
    ("Ungültige URLs", invalid_urls),
)


def check_entries(entries):
    """Prüft eine Datei auf Dubletten und kaputte Einträge; nur Prüfungen mit Funden."""
    findings = [Finding(title, check(entries)) for title, check in CHECKS]
    return [finding for finding in findings if finding.lines]


# ---------------------------------------------------------------- Passwortqualität


def reused_passwords(entries):
    keys_by_password = defaultdict(list)
    for key, row in entries.items():
        if row["Password"]:
            keys_by_password[row["Password"]].append(key)
    return sorted(
        f"{len(keys)} Einträge teilen ein Passwort: "
        + "; ".join(entry_label(key) for key in sorted(keys))
        for keys in keys_by_password.values()
        if len(keys) > 1
    )


def short_passwords(entries, min_length):
    return [
        f"{entry_label(key)}  ({len(row['Password'])} Zeichen)"
        for key, row in sorted(entries.items())
        if row["Password"] and len(row["Password"]) < min_length
    ]


def stale_entries(entries, max_age_days, now):
    lines = []
    for key, row in sorted(entries.items()):
        modified = parse_time(row[MODIFIED])
        if modified is not None and (now - modified).days > max_age_days:
            lines.append(
                f"{entry_label(key)}  (zuletzt geändert {modified.date().isoformat()}, "
                f"vor {(now - modified).days} Tagen)"
            )
    return lines


def audit_entries(entries, min_length, max_age_days, now=None):
    """Bewertet die Passwortqualität einer Datei.

    Rückgabe: (funde, anzahl_totp); ``funde`` enthält nur Prüfungen mit Treffern.
    """
    now = now or datetime.now(UTC)
    findings = [
        Finding("Wiederverwendete Passwörter", reused_passwords(entries)),
        Finding(f"Kurze Passwörter (< {min_length} Zeichen)", short_passwords(entries, min_length)),
        Finding(
            f"Lange nicht geändert (> {max_age_days} Tage)",
            stale_entries(entries, max_age_days, now),
        ),
    ]
    totp_count = sum(1 for row in entries.values() if row["TOTP"].strip())
    return [finding for finding in findings if finding.lines], totp_count
