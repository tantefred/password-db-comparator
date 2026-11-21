"""Welche Auswertung gewählt ist (Vergleich, Überblick, Statistik, Prüfung, Passwörter, Suche)."""

CLEAN = "clean"  # nur ein Export ohne Dubletten, ohne weitere Auswertung

COMPARE, OVERVIEW, DEDUPE, STATS, CHECK, PASSWORD_CHECK, SEARCH = (
    "compare",
    "overview",
    "dedupe",
    "stats",
    "check",
    "password-check",
    "search",
)
MODES = (COMPARE, OVERVIEW, DEDUPE, STATS, CHECK, PASSWORD_CHECK, SEARCH)
# Nur in der Weboberfläche: Dubletten suchen, dann nach eigener Wahl bereinigen
UI_MODES = (*MODES, CLEAN)


def selected_mode(args, single):
    """Der gewählte Modus. Ohne Wahl: Vergleich bei zwei Dateien, Überblick bei einer."""
    if args.dedupe:
        return DEDUPE
    if args.stats:
        return STATS
    if args.check:
        return CHECK
    if args.password_check:
        return PASSWORD_CHECK
    if args.search is not None:
        return SEARCH
    if args.export_clean:
        return CLEAN
    if args.overview or single:
        return OVERVIEW
    return COMPARE
