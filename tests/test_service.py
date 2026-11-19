"""Tests der Service-Schicht (Weboberfläche): gleiches Ergebnis wie die Kommandozeile."""
import copy
import json
import os
import tempfile
import unittest

from csvcompare.service import UsageError, analyze, options_to_argv
from tests.helpers import read_fixture, run

ALT, NEU = read_fixture("alt.csv"), read_fixture("neu.csv")


def cli_json(*args):
    rc, out, _ = run("tests/alt.csv", "tests/neu.csv", *args, "--format", "json")
    return rc, json.loads(out)


def without_paths(report):
    report = copy.deepcopy(report)
    for side in report["files"].values():
        side.pop("path")
    return report


def ui(options, old=ALT, new=NEU):
    return analyze("alt.csv", old, "neu.csv", new, options)


class SameAsCommandLineTests(unittest.TestCase):
    """Für gleiche Optionen muss das UI exakt den Bericht der Kommandozeile liefern."""

    CASES = [
        ({}, []),
        ({"show_secrets": True}, ["--show-secrets"]),
        ({"ignore": ["Icon"]}, ["--ignore", "Icon"]),
        ({"ignore": ["Icon", "Notes"]}, ["--ignore", "Icon,Notes"]),
        ({"hide_trash": True}, ["--hide-trash"]),
        ({"group": "web"}, ["--group", "web"]),
        ({"group": "web", "hide_trash": True, "ignore": ["Icon"]},
         ["--group", "web", "--hide-trash", "--ignore", "Icon"]),
        ({"detect_moves": False}, ["--no-detect-moves"]),
        ({"mode": "search", "search": "mail"}, ["--search", "mail"]),
        ({"mode": "search", "search": "streaming"}, ["--search", "streaming"]),
        ({"mode": "stats"}, ["--stats"]),
        ({"mode": "stats", "group": "privat"}, ["--stats", "--group", "privat"]),
        ({"mode": "check"}, ["--check"]),
        ({"mode": "password-check", "max_age_days": 100000},
         ["--password-check", "--max-age-days", "100000"]),
        ({"mode": "password-check", "min_length": 25, "max_age_days": 100000},
         ["--password-check", "--min-length", "25", "--max-age-days", "100000"]),
    ]

    def test_reports_match_cli(self):
        for options, cli_args in self.CASES:
            with self.subTest(options=options):
                rc, expected = cli_json(*cli_args)
                result = ui(options)
                self.assertEqual(without_paths(result["report"]), without_paths(expected))
                self.assertEqual(result["status"], rc)

    def test_search_without_match_has_status_one(self):
        result = ui({"mode": "search", "search": "zzz"})
        self.assertEqual(result["status"], 1)
        self.assertEqual(result["report"]["match_count"], 0)

    def test_exports_match_cli_files(self):
        with tempfile.TemporaryDirectory() as d:
            a, m = os.path.join(d, "a.csv"), os.path.join(d, "m.csv")
            rc, _, _ = run("tests/alt.csv", "tests/neu.csv", "--export-added", a,
                           "--export-merged", m)
            self.assertEqual(rc, 0)
            result = ui({"export_added": True, "export_merged": True})
            with open(a, encoding="utf-8", newline="") as f:
                self.assertEqual(result["exports"]["added"]["csv"], f.read())
            with open(m, encoding="utf-8", newline="") as f:
                self.assertEqual(result["exports"]["merged"]["csv"], f.read())
        self.assertEqual(result["exports"]["merged"]["filename"], "merged.csv")
        self.assertEqual(len(result["exports"]["merged"]["conflicts"]), 2)


class ServiceBehaviourTests(unittest.TestCase):
    def test_command_line_equivalent_is_shown(self):
        cmd = ui({"ignore": ["Icon"], "hide_trash": True, "mode": "search",
                  "search": "mail server"})["command"]
        self.assertEqual(cmd, "python3 compare_csv.py alt.csv neu.csv --ignore=Icon "
                              "--hide-trash '--search=mail server'")

    def test_no_exports_unless_requested(self):
        self.assertEqual(ui({})["exports"], {})

    def test_blank_group_means_no_filter(self):
        self.assertEqual(ui({"group": "  "})["report"]["filters"]["group"], None)

    def test_same_file_name_is_made_distinguishable(self):
        report = analyze("export.csv", ALT, "export.csv", NEU, {})["report"]
        self.assertEqual(report["files"]["old"]["name"], "export.csv (1)")
        self.assertEqual(report["files"]["new"]["name"], "export.csv (2)")

    def test_utf8_bom_is_ignored(self):
        report = analyze("a.csv", "﻿" + ALT, "b.csv", ALT, {})["report"]
        self.assertTrue(report["summary"]["identical"])

    def test_passwords_stay_masked_unless_requested(self):
        self.assertNotIn("pw-mail", json.dumps(ui({})["report"]))
        self.assertIn("pw-mail-1", json.dumps(ui({"show_secrets": True})["report"]))

    def test_invalid_input_raises_usage_error(self):
        bad = [
            {"mode": "search"},
            {"mode": "search", "search": "x", "export_added": True},
            {"mode": "stats", "export_merged": True},
            {"ignore": ["Foo"]},
            {"ignore": ["Title"]},
            {"ignore": "Icon"},
            {"mode": "bogus"},
            {"mode": "password-check", "min_length": "abc"},
            {"mode": "password-check", "max_age_days": True},
        ]
        for options in bad:
            with self.subTest(options=options), self.assertRaises(UsageError):
                ui(options)

    def test_unusable_csv_raises_usage_error(self):
        with self.assertRaises(UsageError) as ctx:
            analyze("kaputt.csv", "Group,Title\nx,y\n", "neu.csv", NEU, {})
        self.assertIn("kaputt.csv", str(ctx.exception))
        self.assertIn("fehlen Spalten", str(ctx.exception))

    def test_option_values_cannot_inject_other_options(self):
        # Ein Suchbegriff, der wie eine Option aussieht, bleibt ein Suchbegriff.
        argv = options_to_argv({"mode": "search", "search": "--export-added"})
        self.assertEqual(argv, ["--search=--export-added"])
        result = ui({"mode": "search", "search": "--export-added"})
        self.assertEqual(result["exports"], {})
        self.assertEqual(result["report"]["query"], "--export-added")


if __name__ == "__main__":
    unittest.main()
