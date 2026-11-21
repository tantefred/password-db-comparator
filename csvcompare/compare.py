"""Vergleich zweier Dateien: verschobene Einträge, Aktualität und Unterschiede je Eintrag."""

from collections import defaultdict
from dataclasses import dataclass, field
from typing import NamedTuple

from .columns import ALL_NAMES, CORE_NAMES, KEY_NAMES, MODIFIED, TIME_NAMES
from .display import human_delta
from .values import differing_columns, parse_time, values_equal

# Welche Datei ist bei einem geänderten Eintrag aktueller?
NEWER_IN_NEW, NEWER_IN_OLD, UNCLEAR = "newer_in_new", "newer_in_old", "unclear"
FRESHNESS = (NEWER_IN_NEW, NEWER_IN_OLD, UNCLEAR)

# Wie sicher ist die Zuordnung eines verschobenen oder umbenannten Eintrags?
CERTAIN, LIKELY = "certain", "likely"

TIME_REASON = (
    "Zeitstempel verschiedener Formate sind nicht vergleichbar, sie bestimmen "
    "nur, welche Datei aktueller ist"
)


class Side(NamedTuple):
    """Eine der ausgewerteten Dateien: Name, Einträge und was beim Einlesen bekannt wurde."""

    name: str
    entries: dict
    source: object


class Move(NamedTuple):
    """Ein Eintrag, der in der zweiten Datei unter anderem Schlüssel steht."""

    old_key: tuple
    new_key: tuple
    confidence: str  # CERTAIN oder LIKELY

    @property
    def key_columns(self):
        """Welche Schlüsselspalten (Gruppe, Titel, Username) sich geändert haben."""
        pairs = zip(KEY_NAMES, self.old_key.identity, self.new_key.identity, strict=True)
        return [name for name, old, new in pairs if old != new]


class Change(NamedTuple):
    """Unterschiede eines Eintrags zwischen beiden Dateien."""

    key: tuple
    new_key: tuple  # gleich ``key``, außer bei verschobenen Einträgen
    columns: list  # Spalten mit Unterschieden (leer: nur der Schlüssel unterscheidet sich)
    note: str  # welche Datei aktueller ist, z. B. „neu.csv ist 3 Tage neuer“


@dataclass
class Comparison:
    """Ergebnis des Vergleichs zweier (bereits gefilterter) Dateien.

    Mit ``new_name=None`` steht nur eine Datei zur Auswertung (``single``): Dann gibt es keinen
    Vergleich, und alle Auswertungen einzelner Dateien laufen über ``sides``.
    """

    old: dict
    new: dict
    old_name: str
    new_name: str | None
    ignored: list  # per Option ignorierte Spalten
    columns: list  # tatsächlich verglichene Spalten
    only_old: list = field(default_factory=list)  # Schlüssel nur in der ersten Datei
    only_new: list = field(default_factory=list)  # Schlüssel nur in der zweiten Datei
    moves: list = field(default_factory=list)  # Move
    changes: dict = field(default_factory=lambda: {status: [] for status in FRESHNESS})
    old_source: object = None  # LoadResult der ersten Datei (Format, Datenbankname, Hinweise)
    new_source: object = None  # LoadResult der zweiten Datei
    auto_ignored: list = field(default_factory=list)  # [(spalte, grund)]

    @property
    def single(self):
        """Wird nur eine Datei ausgewertet (kein Vergleich)?"""
        return self.new_name is None

    @property
    def sides(self):
        """Die vorhandenen Dateien: eine bei ``single``, sonst beide."""
        sides = [Side(self.old_name, self.old, self.old_source)]
        if not self.single:
            sides.append(Side(self.new_name, self.new, self.new_source))
        return sides

    @property
    def n_changed(self):
        return sum(len(changes) for changes in self.changes.values())

    @property
    def identical(self):
        return not (self.only_old or self.only_new or self.n_changed or self.moves)

    def change_of(self, old_key, new_key=None):
        """Unterschiede und Aktualität eines Eintrags: (aktualität, Change).

        Bei verschobenen Einträgen steht ``new_key`` für den Schlüssel in der zweiten Datei.
        """
        new_key = new_key or old_key
        old_row, new_row = self.old[old_key], self.new[new_key]
        freshness, note = compare_freshness(old_row, new_row, self.old_name, self.new_name)
        columns = differing_columns(old_row, new_row, self.columns)
        return freshness, Change(old_key, new_key, columns, note)

    def move_change(self, move):
        """Die Unterschiede eines verschobenen Eintrags (abgesehen von seinem Schlüssel)."""
        return self.change_of(move.old_key, move.new_key)[1]


def compare_freshness(old_row, new_row, old_name, new_name):
    """Welche Datei hat die neuere Version? Rückgabe: (aktualität, Text)."""
    old_time, new_time = parse_time(old_row[MODIFIED]), parse_time(new_row[MODIFIED])
    if old_time is None or new_time is None:
        return UNCLEAR, "Zeitstempel nicht auswertbar"
    seconds = (new_time - old_time).total_seconds()
    if seconds > 0:
        return NEWER_IN_NEW, f"{new_name} ist {human_delta(seconds)} neuer"
    if seconds < 0:
        return NEWER_IN_OLD, f"{old_name} ist {human_delta(seconds)} neuer"
    return UNCLEAR, "gleicher Zeitstempel, Inhalt unterschiedlich"


def unique_pairs(old_keys, new_keys, matches):
    """Paare (alt, neu), bei denen beide Seiten genau einen Partner haben."""
    candidates = {old: [new for new in new_keys if matches(old, new)] for old in old_keys}
    partners = defaultdict(list)
    for old, news in candidates.items():
        for new in news:
            partners[new].append(old)
    return [
        (old, news[0])
        for old, news in candidates.items()
        if len(news) == 1 and len(partners[news[0]]) == 1
    ]


def find_moves(old, new, only_old, only_new, ignored):
    """Findet verschobene oder umbenannte Einträge unter den nur einseitig vorhandenen.

    Gepaart wird nur bei eindeutigen 1:1-Treffern, zuerst die sicheren, dann die
    wahrscheinlichen.
    """

    def same(old_key, new_key, column):
        old_value = old[old_key][column]
        return (
            column not in ignored
            and old_value != ""
            and values_equal(column, old_value, new[new_key][column])
        )

    def certain(old_key, new_key):  # gleiche Erstellzeit und noch etwas Gemeinsames
        return same(old_key, new_key, "Created") and any(
            same(old_key, new_key, column) for column in ("Password", "URL", "Title")
        )

    def likely(old_key, new_key):  # gleicher Login mit gleicher Adresse
        return all(same(old_key, new_key, column) for column in ("Username", "Password", "URL"))

    moves = []
    todo_old, todo_new = list(only_old), list(only_new)
    for matches, confidence in ((certain, CERTAIN), (likely, LIKELY)):
        pairs = unique_pairs(todo_old, todo_new, matches)
        moves += [Move(old_key, new_key, confidence) for old_key, new_key in pairs]
        paired_old = {old_key for old_key, _ in pairs}
        paired_new = {new_key for _, new_key in pairs}
        todo_old = [key for key in todo_old if key not in paired_old]
        todo_new = [key for key in todo_new if key not in paired_new]
    return sorted(moves)


def comparable_columns(old_name, new_name, ignored, old_source, new_source):
    """Bestimmt, welche Spalten verglichen werden.

    Verglichen wird, was **beide** Dateien liefern. Spalten, die nur eine Seite hat, und –
    bei verschiedenen Formaten – die Zeitstempel werden automatisch ausgelassen.
    Rückgabe: (spalten, [(spalte, grund)]).
    """
    provided_old = old_source.provided_columns if old_source else frozenset(CORE_NAMES)
    provided_new = new_source.provided_columns if new_source else frozenset(CORE_NAMES)
    formats_differ = bool(old_source and new_source and old_source.format != new_source.format)
    columns, auto_ignored = [], []
    for column in ALL_NAMES:
        if column in KEY_NAMES or column in ignored:
            continue
        in_old, in_new = column in provided_old, column in provided_new
        if in_old and in_new:
            if formats_differ and column in TIME_NAMES:
                auto_ignored.append((column, TIME_REASON))
            else:
                columns.append(column)
        elif in_old or in_new:
            missing = new_name if in_old else old_name
            auto_ignored.append((column, f"kommt in {missing} nicht vor"))
    return columns, auto_ignored


def compare_files(
    old, new, old_name, new_name, ignored, detect_moves=True, old_source=None, new_source=None
):
    """Vergleicht zwei Dateien (Dicts {Key: Zeile}) und gibt ein Comparison zurück."""
    columns, auto_ignored = comparable_columns(old_name, new_name, ignored, old_source, new_source)
    only_old = sorted(set(old) - set(new))
    only_new = sorted(set(new) - set(old))
    moves = find_moves(old, new, only_old, only_new, ignored) if detect_moves else []
    moved_old = {move.old_key for move in moves}
    moved_new = {move.new_key for move in moves}

    cmp = Comparison(
        old,
        new,
        old_name,
        new_name,
        list(ignored),
        columns,
        only_old=[key for key in only_old if key not in moved_old],
        only_new=[key for key in only_new if key not in moved_new],
        moves=moves,
        old_source=old_source,
        new_source=new_source,
        auto_ignored=auto_ignored,
    )
    for key in sorted(set(old) & set(new)):
        freshness, change = cmp.change_of(key)
        if change.columns:
            cmp.changes[freshness].append(change)
    return cmp


def single_file(entries, name, ignored=(), source=None):
    """Eine einzelne Datei als ``Comparison`` ohne Gegenseite (für Auswertungen ohne Vergleich)."""
    return Comparison(entries, {}, name, None, list(ignored), [], old_source=source)
