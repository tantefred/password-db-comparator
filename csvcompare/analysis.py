"""Auswertungen einzelner Dateien: Statistik, Prüfung, Passwortqualität."""

from collections import Counter, defaultdict
from urllib.parse import urlsplit

from .common import label, parse_ts
from .constants import TIME_COL


def stats_rows(old, new):
    """Einträge pro Gruppe in beiden Dateien: Liste (gruppe, alt, neu)."""
    c_old = Counter(r["Group"] for r in old.values())
    c_new = Counter(r["Group"] for r in new.values())
    return [(g, c_old[g], c_new[g]) for g in sorted(set(c_old) | set(c_new))]


def url_problem(url):
    """Gibt einen Grund zurück, falls die URL offensichtlich ungültig ist, sonst None."""
    url = url.strip()
    if not url:
        return None
    if any(ch.isspace() for ch in url):
        return "enthält Leerzeichen"
    host = urlsplit(url if "://" in url else "//" + url).hostname or ""
    if not host:
        return "kein Host erkennbar"
    if "." not in host and host != "localhost" and ":" not in host:
        return "Host ohne Punkt"
    return None


def check_entries(entries):
    """Prüft eine Datei auf Dubletten und kaputte Einträge.

    Rückgabe: Liste (überschrift, [zeilen]) – nur Kategorien mit Funden.
    Passwörter werden nie ausgegeben.
    """
    findings = []

    exact = defaultdict(list)
    for k in entries:
        exact[k[:3]].append(k)
    lines = [f"{label(ks[0])}  ({len(ks)}×)" for ks in exact.values() if len(ks) > 1]
    findings.append(("Doppelte Einträge (gleiche Gruppe, Titel und Username)", sorted(lines)))

    by_title = defaultdict(list)
    for k in entries:
        if k[1] and k[2]:
            by_title[(k[1].lower(), k[2].lower())].append(k)
    lines = []
    for ks in by_title.values():
        if len({k[0] for k in ks}) > 1:
            lines.append(f"{ks[0][1]} [{ks[0][2]}] in: " + ", ".join(sorted({k[0] or '(ohne Gruppe)' for k in ks})))
    findings.append(("Gleicher Titel und Username in verschiedenen Gruppen", sorted(lines)))

    by_url = defaultdict(list)
    for k, r in entries.items():
        url = r["URL"].strip().lower().rstrip("/")
        if url and k[2]:
            by_url[(url, k[2].lower())].append(k)
    lines = []
    for (url, user), ks in by_url.items():
        if len({k[:3] for k in ks}) > 1:
            lines.append(f"{url} [{user}]: " + "; ".join(label(k) for k in ks))
    findings.append(("Gleiche URL und Username in verschiedenen Einträgen", sorted(lines)))

    findings.append(("Einträge ohne Passwort",
                     sorted(label(k) for k, r in entries.items() if not r["Password"])))
    findings.append(("Einträge ohne Titel",
                     sorted(label(k) for k in entries if not k[1])))
    lines = []
    for k, r in sorted(entries.items()):
        reason = url_problem(r["URL"])
        if reason:
            lines.append(f"{label(k)}: '{r['URL'].strip()}' ({reason})")
    findings.append(("Ungültige URLs", lines))

    return [(title, lines) for title, lines in findings if lines]


def audit_entries(entries, min_length, max_age_days, now):
    """Bewertet die Passwortqualität einer Datei. Passwörter werden nie ausgegeben.

    Rückgabe: (funde, totp_anzahl) mit funde = Liste (überschrift, [zeilen]).
    """
    findings = []

    by_pw = defaultdict(list)
    for k, r in entries.items():
        if r["Password"]:
            by_pw[r["Password"]].append(k)
    lines = sorted(f"{len(ks)} Einträge teilen ein Passwort: " + "; ".join(label(k) for k in sorted(ks))
                   for ks in by_pw.values() if len(ks) > 1)
    findings.append(("Wiederverwendete Passwörter", lines))

    lines = [f"{label(k)}  ({len(r['Password'])} Zeichen)"
             for k, r in sorted(entries.items()) if r["Password"] and len(r["Password"]) < min_length]
    findings.append((f"Kurze Passwörter (< {min_length} Zeichen)", lines))

    lines = []
    for k, r in sorted(entries.items()):
        ts = parse_ts(r[TIME_COL])
        if ts is not None and (now - ts).days > max_age_days:
            lines.append(f"{label(k)}  (zuletzt geändert {ts.date().isoformat()}, "
                         f"vor {(now - ts).days} Tagen)")
    findings.append((f"Lange nicht geändert (> {max_age_days} Tage)", lines))

    totp = sum(1 for r in entries.values() if r["TOTP"].strip())
    return [(t, ls) for t, ls in findings if ls], totp
