#!/usr/bin/env python3
"""Vergleicht zwei KeePassium-CSV-Exporte und zeigt die Unterschiede.

Aufruf: python3 compare_csv.py alt.csv neu.csv [Optionen]   (Optionen: --help)
"""

from csvcompare.cli import main

if __name__ == "__main__":
    main()
