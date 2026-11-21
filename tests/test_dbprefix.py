"""Tests für den Datenbanknamen am Anfang der KeePassium-Gruppenpfade."""

import csv
import os
import tempfile
import unittest

from csvcompare.importers.keepass_csv import strip_db_prefix
from csvcompare.service import analyze
from tests.helpers import ROOT, run, run_json, titles

A = os.path.join("tests", "keepassium_a.csv")
B = os.path.join("tests", "keepassium_b.csv")


class StripFunctionTests(unittest.TestCase):
    def rows(self, *groups):
        return [{"Group": g} for g in groups]

    def test_common_first_segment_is_removed(self):
        rows = self.rows("DB1/Web", "DB1/Web/Shops", "DB1", "DB1/Privat")
        self.assertEqual(strip_db_prefix(rows), "DB1")
        self.assertEqual([r["Group"] for r in rows], ["Web", "Web/Shops", "", "Privat"])

    def test_different_first_segments_are_kept(self):
        rows = self.rows("Web", "Privat")
        self.assertIsNone(strip_db_prefix(rows))
        self.assertEqual([r["Group"] for r in rows], ["Web", "Privat"])

    def test_one_entry_without_group_prevents_stripping(self):
        rows = self.rows("DB1/Web", "")
        self.assertIsNone(strip_db_prefix(rows))
        self.assertEqual([r["Group"] for r in rows], ["DB1/Web", ""])

    def test_no_rows(self):
        self.assertIsNone(strip_db_prefix([]))

    def test_similar_names_are_not_confused(self):
        rows = self.rows("DB1/Web", "DB10/Web")
        self.assertIsNone(strip_db_prefix(rows))


class ComparisonTests(unittest.TestCase):
    def test_different_database_names_do_not_matter(self):
        rc, r = run_json(A, B)
        self.assertEqual(rc, 0)
        self.assertEqual(r["files"]["old"]["db_prefix"], "Privat-DB")
        self.assertEqual(r["files"]["new"]["db_prefix"], "Familie-DB")
        self.assertEqual(
            r["summary"],
            {
                "only_in_old": 1,
                "only_in_new": 1,
                "moved": 1,
                "changed": 3,
                "newer_in_new": 2,
                "newer_in_old": 1,
                "unclear": 0,
                "identical": False,
            },
        )
        self.assertEqual(titles(r["only_in_old"]), ["Alt-Account"])
        self.assertEqual(titles(r["only_in_new"]), ["Neuer-Account"])

    def test_groups_are_reported_without_the_database_name(self):
        _, r = run_json(A, B)
        groups = {e["group"] for e in r["only_in_old"] + r["only_in_new"]}
        self.assertEqual(groups, {"Web"})
        shop = r["changed"]["newer_in_old"][0]["entry"]
        self.assertEqual(shop["group"], "Web/Shops")
        move = r["moved"][0]
        self.assertEqual((move["entry"]["group"], move["moved_to"]["group"]), ("Privat", "Web"))

    def test_entry_in_the_root_group_is_matched(self):
        _, r = run_json(A, B, "--search", "router")
        self.assertEqual(r["results"][0]["status"], "identical")
        self.assertEqual(r["results"][0]["entry"]["group"], "")

    def test_text_output_names_the_database_and_hides_it_in_paths(self):
        rc, out, _ = run(A, B)
        self.assertEqual(rc, 0)
        self.assertIn("Datenbankname „Privat-DB“ aus den Gruppenpfaden entfernt", out)
        self.assertIn("Datenbankname „Familie-DB“", out)
        self.assertNotIn("Privat-DB /", out)
        self.assertNotIn("Familie-DB/", out)

    def test_file_with_itself_is_identical(self):
        _, r = run_json(A, A)
        self.assertTrue(r["summary"]["identical"])

    def test_keep_db_name_restores_the_old_behaviour(self):
        # Ohne Verschoben-Erkennung stimmt kein Gruppenpfad mehr überein.
        _, r = run_json(A, B, "--keep-db-name", "--no-detect-moves")
        self.assertIsNone(r["files"]["old"]["db_prefix"])
        self.assertEqual(r["summary"]["only_in_old"], 8)
        self.assertEqual(r["summary"]["only_in_new"], 8)
        self.assertTrue(all(e["group"].startswith("Privat-DB") for e in r["only_in_old"]))

    def test_keep_db_name_with_move_detection_pairs_entries_by_content(self):
        # Die Verschoben-Erkennung fängt den abweichenden Datenbanknamen teilweise auf.
        _, r = run_json(A, B, "--keep-db-name")
        self.assertEqual(r["summary"]["moved"], 7)
        self.assertEqual(titles(r["only_in_old"]), ["Alt-Account"])
        self.assertEqual(titles(r["only_in_new"]), ["Neuer-Account"])

    def test_files_without_common_prefix_are_untouched(self):
        _, r = run_json(os.path.join("tests", "alt.csv"), os.path.join("tests", "neu.csv"))
        self.assertIsNone(r["files"]["old"]["db_prefix"])
        self.assertEqual(r["files"]["old"]["notes"], [])

    def test_stats_use_stripped_groups(self):
        _, r = run_json(A, B, "--stats")
        self.assertEqual(
            [g["group"] for g in r["groups"]], ["", "Papierkorb", "Privat", "Web", "Web/Shops"]
        )

    def test_group_filter_uses_stripped_groups(self):
        _, r = run_json(A, B, "--group", "shops")
        self.assertEqual(r["files"]["old"]["entries"], 1)

    def test_hide_trash_still_works(self):
        _, r = run_json(A, B, "--hide-trash")
        self.assertEqual(r["files"]["old"]["entries"], 7)


class ExportTests(unittest.TestCase):
    def read(self, path):
        with open(path, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def test_exports_put_the_database_name_back(self):
        with tempfile.TemporaryDirectory() as d:
            added, merged = os.path.join(d, "a.csv"), os.path.join(d, "m.csv")
            rc, _, _ = run(A, B, "--export-added", added, "--export-merged", merged)
            self.assertEqual(rc, 0)
            rows = self.read(added)
            self.assertEqual(
                [(r["Title"], r["Group"]) for r in rows], [("Neuer-Account", "Familie-DB/Web")]
            )
            groups = {r["Title"]: r["Group"] for r in self.read(merged)}
            self.assertEqual(groups["Router"], "Familie-DB")  # direkt in der Wurzel
            self.assertEqual(groups["Shop"], "Familie-DB/Web/Shops")
            self.assertTrue(all(g.startswith("Familie-DB") for g in groups.values()))
            self.assertNotIn("Gelöscht", groups)  # Papierkorb bleibt draußen

    def test_prefix_of_the_first_file_is_used_if_the_second_has_none(self):
        with tempfile.TemporaryDirectory() as d:
            merged = os.path.join(d, "m.csv")
            run(A, os.path.join("tests", "neu.csv"), "--export-merged", merged)
            groups = [r["Group"] for r in self.read(merged)]
            self.assertTrue(all(g.startswith("Privat-DB") for g in groups))

    def test_keep_db_name_exports_unchanged_paths(self):
        with tempfile.TemporaryDirectory() as d:
            merged = os.path.join(d, "m.csv")
            run(A, A, "--keep-db-name", "--export-merged", merged)
            self.assertTrue(all(r["Group"].startswith("Privat-DB") for r in self.read(merged)))
            self.assertFalse(
                any(r["Group"].startswith("Privat-DB/Privat-DB") for r in self.read(merged))
            )

    def test_exporting_the_same_file_reproduces_the_original_groups(self):
        with tempfile.TemporaryDirectory() as d:
            merged = os.path.join(d, "m.csv")
            run(A, A, "--export-merged", merged)
            original = {
                (r["Title"], r["Group"])
                for r in self.read(os.path.join(ROOT, A))
                if "Papierkorb" not in r["Group"]
            }
            self.assertEqual({(r["Title"], r["Group"]) for r in self.read(merged)}, original)


class ServiceTests(unittest.TestCase):
    def texts(self):
        with open(os.path.join(ROOT, A), encoding="utf-8", newline="") as f:
            a = f.read()
        with open(os.path.join(ROOT, B), encoding="utf-8", newline="") as f:
            b = f.read()
        return a, b

    def test_service_reports_database_names(self):
        a, b = self.texts()
        files = analyze("a.csv", a, "b.csv", b, {})["report"]["files"]
        self.assertEqual(
            (files["old"]["db_prefix"], files["new"]["db_prefix"]), ("Privat-DB", "Familie-DB")
        )

    def test_service_can_keep_the_database_name(self):
        a, b = self.texts()
        result = analyze("a.csv", a, "b.csv", b, {"keep_db_name": True})
        self.assertIsNone(result["report"]["files"]["old"]["db_prefix"])
        self.assertIn("--keep-db-name", result["command"])

    def test_service_exports_with_prefix(self):
        a, b = self.texts()
        export = analyze("a.csv", a, "b.csv", b, {"export_added": True})["exports"]["added"]
        rows = list(csv.DictReader(export["content"].splitlines(keepends=True)))
        self.assertEqual(rows[0]["Group"], "Familie-DB/Web")


if __name__ == "__main__":
    unittest.main()
