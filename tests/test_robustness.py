"""Tests für kaputte Eingaben und kleine Absicherungen."""

import subprocess
import unittest

from csvcompare.duplicates import find_duplicates
from csvcompare.entries import entries_from_rows
from csvcompare.importers import load_any
from csvcompare.service import UsageError, analyze
from tests.helpers import ROOT, fixture_path, read_fixture, run, run_json

KEEPASS_HEADER = "Group,Title,Username,Password,URL,Notes,TOTP,Icon,Last Modified,Created\n"
BITWARDEN_HEADER = (
    "folder,favorite,type,name,notes,fields,reprompt,login_uri,login_username,"
    "login_password,login_totp\n"
)


class ShortRowTests(unittest.TestCase):
    def test_keepass_rows_with_too_few_cells_are_padded_and_reported(self):
        text = KEEPASS_HEADER + "Web,A,u\nWeb,A,u,pw,http://x.org,,,,,\n"
        source = load_any("x.csv", text)
        self.assertEqual(len(source.rows), 2)
        self.assertEqual(source.rows[0]["URL"], "")  # nicht None
        self.assertEqual(source.rows[0]["Password"], "")
        self.assertTrue(any("1 Zeilen haben weniger Spalten" in n for n in source.notes))
        self.assertTrue(any("erste: Zeile 2" in n for n in source.notes))

    def test_all_analyses_survive_short_rows(self):
        text = KEEPASS_HEADER + "Web,A,u\nWeb,A,u,pw,http://x.org,,,,,\nWeb,B\n"
        entries = entries_from_rows(load_any("x.csv", text).rows)
        find_duplicates(entries)  # stürzte früher mit AttributeError ab
        result = analyze("x.csv", text, None, None, {})
        self.assertEqual(result["report"]["mode"], "overview")

    def test_terminal_does_not_crash_on_short_rows(self):
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "kurz.csv")
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(KEEPASS_HEADER + "Web,A,u\nWeb,B,u,pw\n")
            for args in ([], ["--dedupe"], ["--password-check"]):
                with self.subTest(args=args):
                    rc, out, err = run(path, *args)
                    self.assertEqual(rc, 0, err)
                    self.assertNotIn("Traceback", err)
            self.assertIn("weniger Spalten", run(path)[1])

    def test_bitwarden_csv_short_rows(self):
        text = BITWARDEN_HEADER + "Ordner,0,login,Name\n"
        source = load_any("b.csv", text)
        self.assertEqual(source.rows[0]["Title"], "Name")
        self.assertEqual(source.rows[0]["Password"], "")
        self.assertTrue(any("weniger Spalten" in n for n in source.notes))

    def test_blank_lines_and_extra_cells_are_ignored(self):
        text = KEEPASS_HEADER + "\nWeb,A,u,pw,,,,,,,zuviel,noch mehr\n"
        source = load_any("x.csv", text)
        self.assertEqual(len(source.rows), 1)
        self.assertFalse(any("weniger Spalten" in n for n in source.notes))


class SearchTests(unittest.TestCase):
    def test_search_does_not_match_across_field_boundaries(self):
        path = fixture_path("keepassium_a.csv")
        rc, _, _ = run(path, "--search", "b / M")
        self.assertEqual(rc, 1)
        rc, report = run_json(path, "--search", "mail")
        self.assertEqual(report["match_count"], 1)


class NumberOptionTests(unittest.TestCase):
    def test_cli_rejects_zero_and_negative_values(self):
        path = fixture_path("keepassium_a.csv")
        for flag in ("--min-length", "--max-age-days"):
            for value in ("0", "-5", "x"):
                with self.subTest(flag=flag, value=value):
                    rc, _, err = run(path, "--password-check", flag, value)
                    self.assertEqual(rc, 2)
                    self.assertIn(flag, err)

    def test_service_rejects_zero(self):
        text = read_fixture("keepassium_a.csv")
        for options in ({"min_length": 0}, {"max_age_days": -1}):
            with self.subTest(options=options), self.assertRaises(UsageError):
                analyze("a.csv", text, None, None, {"mode": "password-check", **options})


class TimeSpanTests(unittest.TestCase):
    def test_spans_use_real_plurals(self):
        from csvcompare.display import human_delta

        cases = {
            1: "1 Sekunde",
            59: "59 Sekunden",
            60: "1 Minute",
            7200: "2 Stunden",
            3600: "1 Stunde",
            86400: "1 Tag",
            3 * 86400: "3 Tage",
            -3 * 86400: "3 Tage",
        }
        for seconds, text in cases.items():
            with self.subTest(seconds=seconds):
                self.assertEqual(human_delta(seconds), text)

    def test_notes_do_not_contain_placeholders_like_tag_e(self):
        _, out, _ = run(fixture_path("alt.csv"), fixture_path("neu.csv"))
        self.assertNotIn("(e)", out)
        self.assertNotIn("(n)", out)


class HintTests(unittest.TestCase):
    def test_entries_matched_by_order_are_reported_when_comparing(self):
        path = fixture_path("dubletten.csv")
        _, report = run_json(path, path)
        self.assertTrue(
            any("nur nach der Reihenfolge" in n for n in report["files"]["old"]["notes"])
        )
        self.assertIn(
            "2 Einträge haben denselben Schlüssel", " ".join(report["files"]["old"]["notes"])
        )
        _, out, _ = run(path, path)
        self.assertIn("Hinweis: 2 Einträge haben denselben Schlüssel", out)
        self.assertIn("und werden nur nach der Reihenfolge", out)
        one = fixture_path("probleme.csv")
        _, out, _ = run(one, fixture_path("passwoerter.csv"))
        self.assertIn("1 Eintrag hat denselben Schlüssel", out)
        self.assertIn("und wird nur nach der Reihenfolge", out)

    def test_no_order_hint_for_a_single_file_or_clean_data(self):
        _, report = run_json(fixture_path("dubletten.csv"))
        self.assertFalse(any("Reihenfolge" in n for n in report["files"]["old"]["notes"]))
        a, b = fixture_path("keepassium_a.csv"), fixture_path("keepassium_b.csv")
        _, report = run_json(a, b)
        self.assertFalse(any("Reihenfolge" in n for n in report["files"]["old"]["notes"]))

    def test_times_without_a_time_zone_are_reported(self):
        naive = load_any("x.csv", KEEPASS_HEADER + "Web,A,u,pw,,,,,2024-01-10T10:00:00,\n")
        self.assertTrue(any("keine Zeitzone" in n for n in naive.notes))
        zoned = load_any("x.csv", KEEPASS_HEADER + "Web,A,u,pw,,,,,2024-01-10T10:00:00Z,\n")
        self.assertFalse(any("Zeitzone" in n for n in zoned.notes))

    def test_overview_names_the_mergeable_groups(self):
        path = fixture_path("dubletten.csv")
        _, out, _ = run(path)
        self.assertIn("Zusammenführbare Dublettengruppen in dubletten.csv: 3", out)
        _, report = run_json(path)
        self.assertEqual(report["mergeable_groups"], [{"file": "dubletten.csv", "count": 3}])
        _, out, _ = run(fixture_path("keepassium_a.csv"))
        self.assertNotIn("Zusammenführbare", out)


class GitignoreTests(unittest.TestCase):
    def ignored(self, path):
        proc = subprocess.run(
            ["git", "check-ignore", "-q", path], cwd=ROOT, capture_output=True, check=False
        )
        return proc.returncode == 0

    def test_exports_are_ignored_but_fixtures_are_not(self):
        for path in ("bereinigt.json", "merged.json", "export.csv", "x/bitwarden_export.json"):
            with self.subTest(path=path):
                self.assertTrue(self.ignored(path))
        for path in ("tests/bitwarden.json", "tests/dubletten.csv"):
            with self.subTest(path=path):
                self.assertFalse(self.ignored(path))


if __name__ == "__main__":
    unittest.main()
