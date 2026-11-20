"""Welche Auswertung gewählt ist (Vergleich, Überblick, Statistik, Prüfung, Passwörter, Suche)."""

COMPARE, OVERVIEW, STATS, CHECK, PASSWORD_CHECK, SEARCH = (
    "compare",
    "overview",
    "stats",
    "check",
    "password-check",
    "search",
)
MODES = (COMPARE, OVERVIEW, STATS, CHECK, PASSWORD_CHECK, SEARCH)


def selected_mode(args, single):
    """Der gewählte Modus. Ohne Wahl: Vergleich bei zwei Dateien, Überblick bei einer."""
    if args.stats:
        return STATS
    if args.check:
        return CHECK
    if args.password_check:
        return PASSWORD_CHECK
    if args.search is not None:
        return SEARCH
    if args.overview or single:
        return OVERVIEW
    return COMPARE
