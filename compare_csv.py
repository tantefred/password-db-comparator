#!/usr/bin/env python3
"""Vergleicht, wertet aus und bereinigt Passwort-Exporte (KeePass-CSV, Bitwarden-JSON/-CSV).

Aufruf: python3 compare_csv.py alt.csv [neu.csv] [Optionen]   (Optionen: --help)
"""

from csvcompare.cli import main

if __name__ == "__main__":
    main()
