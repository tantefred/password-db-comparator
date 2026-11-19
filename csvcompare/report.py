"""Wählt den passenden JSON-Bericht für die angefragte Auswertung."""

from .compare import search_matches
from .render_json import (check_report, compare_report, password_report, search_report,
                          stats_report)


def build_report(opts, cmp, base):
    """Erzeugt den Bericht zum gewählten Modus.

    opts: Optionen (argparse-Namespace) mit stats, check, password_check, search,
    show_secrets, min_length und max_age_days.
    Rückgabe: (bericht, exitcode); Exitcode 1 nur bei einer Suche ohne Treffer.
    """
    if opts.stats:
        return stats_report(base, cmp), 0
    if opts.check:
        return check_report(base, cmp), 0
    if opts.password_check:
        return password_report(base, cmp, opts.min_length, opts.max_age_days), 0
    if opts.search is not None:
        n_matches, results = search_matches(opts.search, cmp.old, cmp.new, cmp.removed,
                                            cmp.added, cmp.moves, cmp.groups)
        return (search_report(base, cmp, opts.search, n_matches, results, opts.show_secrets),
                0 if n_matches else 1)
    return compare_report(base, cmp, opts.show_secrets), 0
