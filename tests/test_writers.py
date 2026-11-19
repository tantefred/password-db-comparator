"""Tests der Writer-Schnittstelle und der Meldung über nicht speicherbare Daten."""
import csv
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from csvcompare.columns import CORE_NAMES, UNMAPPED_KEY  # noqa: E402
from csvcompare.importers import load_any  # noqa: E402
from csvcompare.service import analyze  # noqa: E402
from csvcompare.writers import (DEFAULT_WRITER, KEEPASS_CSV, WRITERS, has_data,  # noqa: E402
                                loss_lines, lost_data)


def read(name):
    with open(os.path.join(ROOT, "tests", name), encoding="utf-8", newline="") as f:
        return f.read()


KP_A, KP_B = read("keepassium_a.csv"), read("keepassium_b.csv")
BW_JSON, BW_CSV = read("bitwarden.json"), read("bitwarden.csv")


class RegistryTests(unittest.TestCase):
    def test_keepass_csv_is_the_default_writer(self):
        self.assertIs(DEFAULT_WRITER, KEEPASS_CSV)
        self.assertEqual(WRITERS["keepass-csv"], KEEPASS_CSV)
        self.assertEqual(KEEPASS_CSV.columns, CORE_NAMES)
        self.assertFalse(KEEPASS_CSV.restores_source)

    def test_text_and_file_output_agree(self):
        rows = load_any("a.csv", KP_A).rows
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.csv")
            KEEPASS_CSV.write(path, rows)
            with open(path, encoding="utf-8", newline="") as f:
                self.assertEqual(f.read(), KEEPASS_CSV.text(rows))

    def test_output_has_only_the_core_columns(self):
        rows = load_any("bw.json", BW_JSON).rows
        reader = csv.DictReader(KEEPASS_CSV.text(rows).splitlines(keepends=True))
        self.assertEqual(reader.fieldnames, list(CORE_NAMES))
        self.assertEqual(len(list(reader)), 9)


class HasDataTests(unittest.TestCase):
    def test_defaults_do_not_count_as_data(self):
        row = {"Favorite": "0", "Reprompt": "0", "Type": "login", "Fields": "", "URLs": ""}
        for col in row:
            self.assertFalse(has_data(col, row), col)

    def test_real_values_count(self):
        row = {"Favorite": "1", "Reprompt": "1", "Type": "note", "Fields": "A: b"}
        for col in row:
            self.assertTrue(has_data(col, row), col)

    def test_only_additional_urls_count_as_lost(self):
        self.assertFalse(has_data("URLs", {"URLs": "https://a.example"}))
        self.assertTrue(has_data("URLs", {"URLs": "https://a.example\nhttps://b.example"}))

    def test_missing_keys_are_no_data(self):
        self.assertFalse(has_data("Fields", {}))


class LostDataTests(unittest.TestCase):
    def test_keepass_rows_lose_nothing(self):
        self.assertEqual(lost_data(load_any("a.csv", KP_A).rows),
                         {"columns": {}, "source": {}})
        self.assertEqual(loss_lines(lost_data(load_any("a.csv", KP_A).rows)), [])

    def test_bitwarden_json_rows_lose_extra_columns_and_source_data(self):
        lost = lost_data(load_any("bw.json", BW_JSON).rows)
        self.assertEqual(lost["columns"], {"Favorite": 1, "Type": 1, "Reprompt": 1,
                                           "Fields": 1, "URLs": 1})
        self.assertEqual(lost["source"], {"Passwort-Verlauf": 1, "Typ eigener Felder": 1,
                                          "Löschdatum": 1})

    def test_bitwarden_csv_rows_lose_extra_columns_only(self):
        lost = lost_data(load_any("bw.csv", BW_CSV).rows)
        self.assertEqual(lost["columns"], {"Favorite": 1, "Type": 1, "Reprompt": 1,
                                           "Fields": 1, "URLs": 1})
        self.assertEqual(lost["source"], {})

    def test_a_writer_that_restores_the_source_does_not_count_source_data(self):
        class Json(type(KEEPASS_CSV)):
            pass
        writer = Json("bitwarden-json", "Bitwarden-JSON", CORE_NAMES, restores_source=True)
        lost = lost_data(load_any("bw.json", BW_JSON).rows, writer)
        self.assertEqual(lost["source"], {})

    def test_unmapped_labels_of_the_json_importer(self):
        data = json.loads(BW_JSON)
        item = data["items"][1]                      # Shop: nichts Besonderes
        item["login"]["fido2Credentials"] = [{"credentialId": "x"}]
        item["collectionIds"] = ["c1"]
        item["organizationId"] = "o1"
        item["login"]["uris"][0]["match"] = 1
        rows = {r["Title"]: r for r in load_any("bw.json", json.dumps(data)).rows}
        self.assertEqual(sorted(rows["Shop"][UNMAPPED_KEY]),
                         ["Organisation", "Passkeys", "Sammlungen", "URL-Abgleichsmodus"])
        self.assertEqual(rows["Forum"][UNMAPPED_KEY], [])

    def test_extra_csv_columns_with_content_are_reported(self):
        text = BW_CSV.replace("folder,", "collections,folder,", 1)
        lines = text.splitlines(keepends=True)
        lines[1] = "Team," + lines[1]
        lines[2:] = [",".join([""]) + "," + ln for ln in lines[2:]]
        rows = load_any("org.csv", "".join(lines)).rows
        self.assertEqual(rows[0][UNMAPPED_KEY], ["Spalte „collections“"])
        self.assertEqual(rows[1][UNMAPPED_KEY], [])


class ExportMessageTests(unittest.TestCase):
    def run_cli(self, *args):
        proc = subprocess.run([sys.executable, os.path.join(ROOT, "compare_csv.py"), *args],
                              cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
        return proc.returncode, proc.stdout, proc.stderr

    def test_terminal_names_what_the_export_loses(self):
        with tempfile.TemporaryDirectory() as d:
            rc, out, _ = self.run_cli("tests/keepassium_a.csv", "tests/bitwarden.json",
                                      "--export-merged", os.path.join(d, "m.csv"))
        self.assertEqual(rc, 0)
        self.assertIn("Im KeePass-CSV nicht speicherbar (Anzahl betroffener Einträge): "
                      "Passwort-Nachfrage (1), Typ (1), Favorit (1), Eigene Felder (1), "
                      "Alle URLs (1), Passwort-Verlauf (1), Typ eigener Felder (1)", out)

    def test_loss_line_comes_before_the_blank_line(self):
        with tempfile.TemporaryDirectory() as d:
            _, out, _ = self.run_cli("tests/keepassium_a.csv", "tests/bitwarden.json",
                                     "--export-merged", os.path.join(d, "m.csv"))
        lines = out.split("\n")
        i = next(n for n, line in enumerate(lines) if "nicht speicherbar" in line)
        self.assertEqual(lines[i + 1], "")

    def test_export_added_reports_losses_too(self):
        with tempfile.TemporaryDirectory() as d:
            _, out, _ = self.run_cli("tests/keepassium_a.csv", "tests/bitwarden.json",
                                     "--export-added", os.path.join(d, "a.csv"))
        self.assertIn("nicht speicherbar", out)          # die Notiz ist „note“, nur im Bitwarden-Export

    def test_no_message_when_nothing_is_lost(self):
        with tempfile.TemporaryDirectory() as d:
            _, out, _ = self.run_cli("tests/keepassium_a.csv", "tests/keepassium_b.csv",
                                     "--export-merged", os.path.join(d, "m.csv"),
                                     "--export-added", os.path.join(d, "a.csv"))
        self.assertNotIn("nicht speicherbar", out)

    def test_losses_only_count_rows_that_are_exported(self):
        # Der gelöschte Eintrag (Löschdatum) steht im Papierkorb und wird nicht exportiert.
        with tempfile.TemporaryDirectory() as d:
            _, out, _ = self.run_cli("tests/bitwarden.json", "tests/bitwarden.json",
                                     "--export-merged", os.path.join(d, "m.csv"))
        self.assertNotIn("Löschdatum", out)
        self.assertIn("Passwort-Verlauf (1)", out)

    def test_json_mode_sends_the_message_to_stderr(self):
        with tempfile.TemporaryDirectory() as d:
            rc, out, err = self.run_cli("tests/keepassium_a.csv", "tests/bitwarden.json",
                                        "--format", "json", "--export-merged",
                                        os.path.join(d, "m.csv"))
        self.assertEqual(json.loads(out)["mode"], "compare")
        self.assertIn("nicht speicherbar", err)
        self.assertNotIn("nicht speicherbar", out)


class WordingTests(unittest.TestCase):
    def test_singular_and_plural_in_export_messages(self):
        one = analyze("kp.csv", KP_A, "bw.json", BW_JSON, {"export_added": True})
        self.assertTrue(one["exports"]["added"]["lines"][0].startswith("1 neuer Eintrag nach "))
        many = analyze("a.csv", KP_A, "b.csv", KP_B, {"export_merged": True})
        self.assertTrue(many["exports"]["merged"]["lines"][0].startswith("8 Einträge nach "))
        single = KP_A.splitlines(keepends=True)
        single = "".join(single[:2])
        merged = analyze("a.csv", single, "b.csv", single, {"export_merged": True})
        self.assertTrue(merged["exports"]["merged"]["lines"][0].startswith("1 Eintrag nach "))


class ServiceTests(unittest.TestCase):
    def test_service_returns_structured_losses(self):
        result = analyze("kp.csv", KP_A, "bw.json", BW_JSON, {"export_merged": True})
        merged = result["exports"]["merged"]
        self.assertEqual(merged["target"], "KeePass-CSV")
        self.assertEqual(merged["lost"]["columns"]["Favorite"], 1)
        self.assertEqual(merged["lost"]["source"]["Passwort-Verlauf"], 1)
        self.assertTrue(any("nicht speicherbar" in line for line in merged["lines"]))

    def test_service_added_export_has_losses(self):
        result = analyze("kp.csv", KP_A, "bw.json", BW_JSON, {"export_added": True})
        added = result["exports"]["added"]
        self.assertEqual(added["lost"]["columns"], {"Type": 1})
        self.assertEqual(added["csv"].splitlines()[0], ",".join(CORE_NAMES))

    def test_nothing_lost_between_keepass_files(self):
        result = analyze("a.csv", KP_A, "b.csv", KP_B, {"export_merged": True})
        self.assertEqual(result["exports"]["merged"]["lost"], {"columns": {}, "source": {}})

    def test_private_keys_never_reach_the_csv_or_the_report(self):
        result = analyze("kp.csv", KP_A, "bw.json", BW_JSON, {"export_merged": True})
        blob = json.dumps(result["report"]) + result["exports"]["merged"]["csv"]
        for secret_key in ("_source", "_unmapped", "passwordHistory", "pw-mail-0"):
            self.assertNotIn(secret_key, blob)


if __name__ == "__main__":
    unittest.main()
