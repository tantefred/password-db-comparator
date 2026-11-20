"""Tests der Auswertung einer einzelnen Datei im Terminal."""

import unittest

from tests.helpers import fixture_path, run, run_json

KP_A = fixture_path("keepassium_a.csv")
KP_B = fixture_path("keepassium_b.csv")
PROBLEME = fixture_path("probleme.csv")
PASSWOERTER = fixture_path("passwoerter.csv")
BW_JSON = fixture_path("bitwarden.json")
BW_CSV = fixture_path("bitwarden.csv")


class DefaultOverviewTests(unittest.TestCase):
    def test_one_file_without_a_mode_shows_the_overview(self):
        rc, out, _ = run(PROBLEME)
        self.assertEqual(rc, 0)
        self.assertIn("probleme.csv: 12 Einträge", out)
        for heading in ("== Statistik ==", "== Prüfung auf Dubletten", "== Passwortqualität =="):
            self.assertIn(heading, out)
        self.assertIn("Doppelte Einträge", out)  # die Prüfung findet etwas
        self.assertNotIn("Zusammenfassung", out)  # kein Vergleich

    def test_overview_json_has_the_three_sections(self):
        rc, report = run_json(PROBLEME)
        self.assertEqual(rc, 0)
        self.assertEqual(report["mode"], "overview")
        self.assertIsNone(report["files"]["new"])
        self.assertEqual(report["stats"]["total"], {"old": 12})
        self.assertEqual([r["file"] for r in report["check"]["results"]], ["probleme.csv"])
        self.assertEqual([r["file"] for r in report["password_check"]["results"]], ["probleme.csv"])
        self.assertNotIn("mode", report["stats"])  # die Abschnitte tragen keinen eigenen Modus

    def test_overview_is_the_same_as_the_three_single_reports(self):
        _, overview = run_json(PROBLEME, "--max-age-days", "100000")
        _, check = run_json(PROBLEME, "--check")
        _, stats = run_json(PROBLEME, "--stats")
        _, passwords = run_json(PROBLEME, "--password-check", "--max-age-days", "100000")
        self.assertEqual(overview["check"]["results"], check["results"])
        self.assertEqual(overview["stats"]["groups"], stats["groups"])
        self.assertEqual(overview["password_check"]["results"], passwords["results"])

    def test_explicit_overview_with_two_files_reports_each_file(self):
        rc, report = run_json(KP_A, KP_B, "--overview")
        self.assertEqual(rc, 0)
        self.assertEqual(
            [r["file"] for r in report["check"]["results"]],
            ["keepassium_a.csv", "keepassium_b.csv"],
        )

    def test_two_files_without_a_mode_still_compare(self):
        _, report = run_json(KP_A, KP_B)
        self.assertEqual(report["mode"], "compare")


class SingleModesTests(unittest.TestCase):
    def test_stats_with_one_count_column(self):
        rc, out, _ = run(KP_A, "--stats")
        self.assertEqual(rc, 0)
        self.assertIn("Gesamt", out)
        self.assertNotIn("Differenz", out)
        _, report = run_json(KP_A, "--stats")
        self.assertEqual(report["total"], {"old": 8})
        self.assertIsNone(report["files"]["new"])

    def test_check_finds_the_duplicates_of_the_sample_file(self):
        _, report = run_json(PROBLEME, "--check")
        categories = {f["category"] for f in report["results"][0]["findings"]}
        self.assertIn("Doppelte Einträge (gleiche Gruppe, Titel und Username)", categories)

    def test_password_check_thresholds(self):
        _, report = run_json(PASSWOERTER, "--password-check", "--max-age-days", "100000")
        self.assertEqual(report["thresholds"], {"min_length": 10, "max_age_days": 100000})
        self.assertEqual(report["results"][0]["totp"], {"with_totp": 1, "entries": 6})

    def test_search_lists_hits_without_a_comparison_status(self):
        rc, out, _ = run(KP_A, "--search", "mail")
        self.assertEqual(rc, 0)
        self.assertIn("1 Treffer", out)
        self.assertIn("* Web / Mail", out)
        self.assertNotIn("identisch in beiden", out)
        _, report = run_json(KP_A, "--search", "web")
        self.assertEqual({r["status"] for r in report["results"]}, {"found"})
        self.assertEqual(report["match_count"], 4)

    def test_search_without_a_hit_exits_with_one(self):
        rc, _, err = run(KP_A, "--search", "zzz")
        self.assertEqual(rc, 1)
        self.assertIn("Kein Eintrag gefunden", err)

    def test_filters_apply_to_a_single_file(self):
        _, report = run_json(KP_A, "--stats", "--hide-trash", "--group", "web")
        self.assertEqual(report["total"], {"old": 4})
        self.assertEqual(report["filters"]["group"], "web")

    def test_bitwarden_files_work_too(self):
        for path, fmt in ((BW_JSON, "bitwarden-json"), (BW_CSV, "bitwarden-csv")):
            with self.subTest(path=path):
                rc, report = run_json(path)
                self.assertEqual(rc, 0)
                self.assertEqual(report["files"]["old"]["format"], fmt)

    def test_header_names_the_format_and_hints_once(self):
        _, out, _ = run(BW_JSON)
        self.assertEqual(out.count("bitwarden.json: 9 Einträge (Bitwarden-JSON)"), 1)
        self.assertIn("Hinweis: 2 Einträge übersprungen", out)


class SingleErrorTests(unittest.TestCase):
    def test_comparison_exports_need_two_files(self):
        for flag in ("--export-added", "--export-merged"):
            with self.subTest(flag=flag):
                rc, _, err = run(KP_A, flag)
                self.assertEqual(rc, 2)
                self.assertIn(f"{flag} braucht zwei Dateien", err)

    def test_modes_exclude_each_other(self):
        rc, _, err = run(KP_A, "--overview", "--stats")
        self.assertEqual(rc, 2)
        self.assertIn("--overview und --stats können nicht kombiniert werden", err)

    def test_no_file_is_an_error(self):
        rc, _, err = run()
        self.assertEqual(rc, 2)
        self.assertIn("mindestens eine Datei", err)

    def test_unreadable_single_file(self):
        rc, _, err = run("/does/not/exist.csv")
        self.assertEqual(rc, 1)
        self.assertIn("kann nicht gelesen werden", err)


if __name__ == "__main__":
    unittest.main()
