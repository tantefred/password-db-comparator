"""KeePass-CSV (KeePassium/KeePassXC) als Zielformat."""

import csv
import io
from dataclasses import dataclass

from ..columns import CORE_NAMES
from ..importers import KEEPASS_CSV
from .base import Writer


@dataclass(frozen=True)
class KeePassCsvWriter(Writer):
    def text(self, rows):
        buffer = io.StringIO(newline="")
        writer = csv.DictWriter(buffer, fieldnames=self.columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        return buffer.getvalue()


KEEPASS_CSV_WRITER = KeePassCsvWriter(
    format=KEEPASS_CSV,
    label="KeePass-CSV",
    extension=".csv",
    mime="text/csv",
    columns=CORE_NAMES,
    prefix_groups=True,
)
