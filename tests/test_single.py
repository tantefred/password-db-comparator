"""Tests für die Auswertung einer einzelnen Datei (ohne Vergleich)."""

import argparse
import unittest

from csvcompare.compare import compare_files, single_file
from csvcompare.entries import entries_from_rows
from csvcompare.importers import load_any
from csvcompare.render_json import base_report, check_report, stats_report
from tests.helpers import read_fixture

ARGS = argparse.Namespace(
    hide_trash=False, group=None, alt="a.csv", neu=None, no_detect_moves=False
)


def load(name):
    source = load_any(name, read_fixture(name))
    return entries_from_rows(source.rows), source


class SingleComparisonTests(unittest.TestCase):
    def setUp(self):
        entries, source = load("keepassium_a.csv")
        self.cmp = single_file(entries, "a.csv", source=source)

    def test_marks_itself_as_single_with_one_side(self):
        self.assertTrue(self.cmp.single)
        self.assertEqual([side.name for side in self.cmp.sides], ["a.csv"])
        self.assertEqual(len(self.cmp.sides[0].entries), 8)
        self.assertIs(self.cmp.sides[0].source, self.cmp.old_source)

    def test_two_files_have_two_sides(self):
        old, old_source = load("keepassium_a.csv")
        new, new_source = load("keepassium_b.csv")
        cmp = compare_files(old, new, "a", "b", [], old_source=old_source, new_source=new_source)
        self.assertFalse(cmp.single)
        self.assertEqual([side.name for side in cmp.sides], ["a", "b"])

    def test_report_has_no_second_file(self):
        base = base_report(self.cmp, ARGS)
        self.assertIsNone(base["files"]["new"])
        self.assertEqual(base["files"]["old"]["entries"], 8)
        self.assertEqual(base["files"]["old"]["format"], "keepass-csv")

    def test_stats_report_has_one_count_per_group(self):
        report = stats_report(base_report(self.cmp, ARGS), self.cmp)
        self.assertEqual(report["total"], {"old": 8})
        self.assertEqual(
            {g["group"]: g["old"] for g in report["groups"]},
            {"": 1, "Papierkorb": 1, "Privat": 2, "Web": 3, "Web/Shops": 1},
        )
        self.assertTrue(all(set(g) == {"group", "old"} for g in report["groups"]))

    def test_check_report_has_one_result(self):
        report = check_report(base_report(self.cmp, ARGS), self.cmp)
        self.assertEqual([r["file"] for r in report["results"]], ["a.csv"])


if __name__ == "__main__":
    unittest.main()
