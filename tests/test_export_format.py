"""Tests der Wahl des Exportformats (KeePass-CSV oder Bitwarden-JSON)."""

import json
import os
import tempfile
import unittest

from csvcompare.importers import load_any
from csvcompare.service import UsageError, analyze
from tests.helpers import fixture_path, read_fixture, run, run_json

KP_A, KP_B = fixture_path("keepassium_a.csv"), fixture_path("keepassium_b.csv")
BW_JSON = fixture_path("bitwarden.json")


def read(path):
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


class CommandLineTests(unittest.TestCase):
    def test_bitwarden_json_export_is_written_and_readable_again(self):
        with tempfile.TemporaryDirectory() as d:
            target = os.path.join(d, "out.json")
            rc, out, _ = run(
                KP_A, KP_B, "--export-merged", target, "--export-format", "bitwarden-json"
            )
            self.assertEqual(rc, 0)
            data = json.loads(read(target))
        self.assertEqual(set(data), {"encrypted", "folders", "items"})
        titles = sorted(item["name"] for item in data["items"])
        self.assertIn("Streaming-Abo", titles)
        self.assertNotIn("Gelöscht", titles)  # Papierkorb bleibt draußen
        self.assertIn("Im Bitwarden-JSON nicht speicherbar", out)
        self.assertIn("Icon (", out)

    def test_default_names_follow_the_format(self):
        with tempfile.TemporaryDirectory() as d:
            for format_id, extension in (("bitwarden-json", ".json"), ("keepass-csv", ".csv")):
                rc, _, _ = run(
                    KP_A,
                    KP_B,
                    "--export-merged",
                    "--export-added",
                    "--export-format",
                    format_id,
                    cwd=d,
                )
                self.assertEqual(rc, 0)
                self.assertTrue(os.path.exists(os.path.join(d, f"merged{extension}")))
                self.assertTrue(os.path.exists(os.path.join(d, f"neue_eintraege{extension}")))

    def test_keepass_csv_stays_the_default(self):
        with tempfile.TemporaryDirectory() as d:
            rc, _, _ = run(KP_A, KP_B, "--export-merged", cwd=d)
            self.assertEqual(rc, 0)
            self.assertEqual(os.listdir(d), ["merged.csv"])

    def test_explicit_path_wins_over_the_default_name(self):
        with tempfile.TemporaryDirectory() as d:
            target = os.path.join(d, "mein-name.txt")
            run(KP_A, KP_B, "--export-merged", target, "--export-format", "bitwarden-json")
            self.assertEqual(json.loads(read(target))["encrypted"], False)

    def test_the_database_name_is_not_put_in_front_of_bitwarden_folders(self):
        with tempfile.TemporaryDirectory() as d:
            target = os.path.join(d, "out.json")
            run(KP_A, KP_B, "--export-merged", target, "--export-format", "bitwarden-json")
            folders = [f["name"] for f in json.loads(read(target))["folders"]]
        self.assertEqual(folders, ["Privat", "Web", "Web/Shops"])
        self.assertFalse(any("DB" in name for name in folders))

    def test_added_entries_as_bitwarden_json(self):
        with tempfile.TemporaryDirectory() as d:
            target = os.path.join(d, "added.json")
            run(KP_A, KP_B, "--export-added", target, "--export-format", "bitwarden-json")
            items = json.loads(read(target))["items"]
        self.assertEqual([item["name"] for item in items], ["Neuer-Account"])

    def test_json_report_and_json_export_together(self):
        with tempfile.TemporaryDirectory() as d:
            target = os.path.join(d, "out.json")
            rc, report = run_json(
                KP_A, KP_B, "--export-merged", target, "--export-format", "bitwarden-json"
            )
            self.assertEqual((rc, report["mode"]), (0, "compare"))
            self.assertEqual(json.loads(read(target))["encrypted"], False)

    def test_export_format_without_an_export_is_an_error(self):
        rc, _, err = run(KP_A, KP_B, "--export-format", "bitwarden-json")
        self.assertEqual(rc, 2)
        self.assertIn("--export-format braucht --export-added oder --export-merged", err)

    def test_unknown_format_is_rejected(self):
        rc, _, err = run(KP_A, KP_B, "--export-merged", "--export-format", "excel")
        self.assertEqual(rc, 2)
        self.assertIn("invalid choice", err)

    def test_bitwarden_json_to_bitwarden_json_keeps_everything(self):
        with tempfile.TemporaryDirectory() as d:
            target = os.path.join(d, "out.json")
            rc, out, _ = run(
                BW_JSON, BW_JSON, "--export-merged", target, "--export-format", "bitwarden-json"
            )
            self.assertEqual(rc, 0)
            self.assertNotIn("nicht speicherbar", out)
            items = {item["name"]: item for item in json.loads(read(target))["items"]}
        self.assertEqual(items["Mail"]["passwordHistory"][0]["password"], "pw-mail-0")
        self.assertEqual(items["Mail"]["fields"][0]["type"], 1)

    def test_help_names_the_formats(self):
        _, out, _ = run("--help")
        self.assertIn("--export-format", out)
        self.assertIn("bitwarden-json", out)


class ServiceTests(unittest.TestCase):
    OLD, NEW = read_fixture("keepassium_a.csv"), read_fixture("keepassium_b.csv")

    def export(self, **options):
        return analyze("a.csv", self.OLD, "b.csv", self.NEW, {"export_merged": True, **options})[
            "exports"
        ]["merged"]

    def test_bitwarden_json_payload(self):
        merged = self.export(export_format="bitwarden-json")
        self.assertEqual(merged["filename"], "merged.json")
        self.assertEqual(merged["mime"], "application/json")
        self.assertEqual(merged["target"], "Bitwarden-JSON")
        self.assertEqual(json.loads(merged["content"])["encrypted"], False)
        self.assertEqual(merged["lost"]["columns"], {"Icon": 8})

    def test_keepass_csv_payload_is_unchanged(self):
        merged = self.export()
        self.assertEqual((merged["filename"], merged["mime"]), ("merged.csv", "text/csv"))
        self.assertTrue(merged["content"].startswith("Group,Title,"))

    def test_content_can_be_read_back_by_the_importer(self):
        merged = self.export(export_format="bitwarden-json")
        self.assertEqual(load_any("m.json", merged["content"]).format, "bitwarden-json")

    def test_the_equivalent_command_names_the_format(self):
        result = analyze(
            "a.csv",
            self.OLD,
            "b.csv",
            self.NEW,
            {"export_added": True, "export_format": "bitwarden-json"},
        )
        self.assertIn("--export-format=bitwarden-json --export-added", result["command"])
        self.assertEqual(result["exports"]["added"]["filename"], "neue_eintraege.json")

    def test_format_without_an_export_is_ignored_by_the_options_translation(self):
        result = analyze("a.csv", self.OLD, "b.csv", self.NEW, {"export_format": "bitwarden-json"})
        self.assertEqual(result["exports"], {})

    def test_unknown_format_is_a_usage_error(self):
        with self.assertRaises(UsageError):
            self.export(export_format="excel")


if __name__ == "__main__":
    unittest.main()
