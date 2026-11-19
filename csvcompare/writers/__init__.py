"""Zielformate für Exporte und die Meldung, was ein Zielformat nicht speichern kann.

Jedes Format hat einen Writer mit ``text`` und ``write`` sowie der Liste der Spalten, die es
speichern kann; ``lost_data`` meldet für beliebige Zeilen, was beim Schreiben verloren ginge.
Ein weiteres Format kommt als eigenes Modul hierher und in ``WRITERS``.
"""

from .base import Writer, has_data, loss_lines, lost_data
from .keepass_csv import KEEPASS_CSV_WRITER

WRITERS = {writer.format: writer for writer in (KEEPASS_CSV_WRITER,)}
DEFAULT_WRITER = KEEPASS_CSV_WRITER

__all__ = [
    "DEFAULT_WRITER",
    "KEEPASS_CSV_WRITER",
    "WRITERS",
    "Writer",
    "has_data",
    "loss_lines",
    "lost_data",
]
