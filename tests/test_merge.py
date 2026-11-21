"""Tests des Zusammenführens von Dubletten (Modul und ``--export-clean``)."""

import json
import os
import tempfile
import unittest

from csvcompare.columns import OLD_PASSWORDS_KEY
from csvcompare.duplicates import KEY, LOGIN, TITLE, find_duplicates
from csvcompare.entries import entries_from_rows
from csvcompare.importers import load_any
from csvcompare.merge import (
    BOTH,
    KEEP_ALL,
    KEEP_ONE,
    MERGE,
    Decision,
    clean_entries,
    merge_rows,
)
from tests.helpers import fixture_path, read_fixture, run

SAMPLE = fixture_path("dubletten.csv")


def row(**values):
    base = dict.fromkeys(
        ("Group", "Title", "Username", "Password", "URL", "Notes", "TOTP", "Icon"), ""
    )
    base.update({"Last Modified": "", "Created": ""})
    base.update(values)
    return base


def sample_entries():
    return entries_from_rows(load_any("dubletten.csv", read_fixture("dubletten.csv")).rows)


class MergeRowsTests(unittest.TestCase):
    def test_newest_row_is_the_base(self):
        old = row(Password="alt", **{"Last Modified": "2024-01-01T10:00:00Z"})
        new = row(Password="neu", **{"Last Modified": "2024-05-01T10:00:00Z"})
        merged, conflicts = merge_rows([old, new])
        self.assertEqual(merged["Password"], "neu")
        self.assertEqual(conflicts, ["Password"])

    def test_tie_prefers_the_later_row(self):
        a = row(Password="a", **{"Last Modified": "2024-01-01T10:00:00Z"})
        b = row(Password="b", **{"Last Modified": "2024-01-01T10:00:00Z"})
        self.assertEqual(merge_rows([a, b])[0]["Password"], "b")

    def test_row_without_a_time_is_the_oldest(self):
        undated = row(Password="u")
        dated = row(Password="d", **{"Last Modified": "2020-01-01T00:00:00Z"})
        self.assertEqual(merge_rows([dated, undated])[0]["Password"], "d")

    def test_empty_fields_are_filled_from_the_others(self):
        new = row(Password="p", **{"Last Modified": "2024-05-01T10:00:00Z"})
        old = row(
            Password="p", Notes="Notiz", TOTP="ABC", **{"Last Modified": "2024-01-01T10:00:00Z"}
        )
        merged, conflicts = merge_rows([old, new])
        self.assertEqual((merged["Notes"], merged["TOTP"]), ("Notiz", "ABC"))
        self.assertEqual(conflicts, [])

    def test_equal_values_are_no_conflict(self):
        a = row(URL="https://x.example.org/", Password="p")
        b = row(URL="HTTPS://X.example.org", Password="p")
        self.assertEqual(merge_rows([a, b])[1], [])

    def test_created_is_the_earliest_and_modified_the_latest(self):
        a = row(Created="2023-05-01T00:00:00Z", **{"Last Modified": "2024-01-01T00:00:00Z"})
        b = row(Created="2021-05-01T00:00:00Z", **{"Last Modified": "2025-01-01T00:00:00Z"})
        merged, _ = merge_rows([a, b])
        self.assertEqual(merged["Created"], "2021-05-01T00:00:00Z")
        self.assertEqual(merged["Last Modified"], "2025-01-01T00:00:00Z")

    def test_picks_choose_a_member_and_notes_can_be_joined(self):
        a = row(Password="a", Notes="eins", **{"Last Modified": "2024-01-01T00:00:00Z"})
        b = row(Password="b", Notes="zwei", **{"Last Modified": "2024-02-01T00:00:00Z"})
        picked, _ = merge_rows([a, b], {"Password": 0})
        self.assertEqual(picked["Password"], "a")
        self.assertEqual(picked[OLD_PASSWORDS_KEY][0][0], "b")
        both, _ = merge_rows([a, b], {"Notes": BOTH})
        self.assertEqual(both["Notes"], "zwei\n\neins")

    def test_older_passwords_are_kept_without_repeats(self):
        rows = [
            row(Password="p1", **{"Last Modified": "2023-01-01T00:00:00Z"}),
            row(Password="p2", **{"Last Modified": "2024-01-01T00:00:00Z"}),
            row(Password="p1", **{"Last Modified": "2022-01-01T00:00:00Z"}),
            row(Password="p3", **{"Last Modified": "2025-01-01T00:00:00Z"}),
        ]
        merged, _ = merge_rows(rows)
        self.assertEqual([p for p, _ in merged[OLD_PASSWORDS_KEY]], ["p2", "p1"])

    def test_urls_are_collected_with_the_chosen_one_first(self):
        a = row(URL="https://a.example.org", **{"Last Modified": "2024-01-01T00:00:00Z"})
        b = row(URL="https://b.example.org", **{"Last Modified": "2024-02-01T00:00:00Z"})
        merged, _ = merge_rows([a, b])
        self.assertEqual(merged["URLs"].split(), ["https://b.example.org", "https://a.example.org"])

    def test_inputs_are_not_modified(self):
        a, b = row(Password="a"), row(Password="b")
        copy_a, copy_b = dict(a), dict(b)
        merge_rows([a, b])
        self.assertEqual((a, b), (copy_a, copy_b))


class CleanEntriesTests(unittest.TestCase):
    def setUp(self):
        self.entries = sample_entries()
        self.groups = find_duplicates(self.entries)

    def test_automatic_run_merges_only_key_groups(self):
        cleaned = clean_entries(self.entries, self.groups)
        self.assertEqual(len(cleaned.rows), 6)  # 9 - 1 Papierkorb - 2 zusammengeführt
        self.assertEqual((len(cleaned.merged), cleaned.removed, cleaned.trash), (1, 2, 1))
        self.assertEqual(find_duplicates(entries_from_rows(cleaned.rows), (KEY,)), [])

    def test_login_and_title_groups_stay_without_a_decision(self):
        cleaned = clean_entries(self.entries, self.groups)
        titles = sorted(r["Title"] for r in cleaned.rows)
        self.assertEqual(titles.count("Forum"), 2)
        self.assertIn("Bank", titles)
        self.assertIn("Bank Online", titles)

    def test_login_can_be_merged_when_asked(self):
        cleaned = clean_entries(self.entries, self.groups, auto_kinds=(KEY, LOGIN))
        self.assertEqual(len(cleaned.rows), 5)

    def test_decisions_override_the_defaults(self):
        by_kind = {g.kind: g for g in self.groups}
        decisions = {
            by_kind[KEY].id: Decision(KEEP_ALL),
            by_kind[TITLE].id: Decision(MERGE),
            by_kind[LOGIN].id: Decision(KEEP_ONE, keep=0),
        }
        cleaned = clean_entries(self.entries, self.groups, decisions)
        self.assertEqual(len(cleaned.rows), 9 - 1 - 1 - 1)
        self.assertEqual(cleaned.removed, 2)

    def test_trash_is_left_out(self):
        cleaned = clean_entries(self.entries, [])
        self.assertTrue(all("Papierkorb" not in r["Group"] for r in cleaned.rows))

    def test_invalid_decisions_are_rejected(self):
        group = self.groups[0]
        bad = (
            {"gibtsnicht": Decision(MERGE)},
            {group.id: Decision("löschen")},
            {group.id: Decision(KEEP_ONE, keep=9)},
            {group.id: Decision(MERGE, picks={"Password": 9})},
            {group.id: Decision(MERGE, picks={"Created": 0})},
        )
        for decisions in bad:
            with self.subTest(decisions=decisions), self.assertRaises(ValueError):
                clean_entries(self.entries, self.groups, decisions)


class ExportCleanCliTests(unittest.TestCase):
    def run_in_tmp(self, *args):
        with tempfile.TemporaryDirectory() as tmp:
            rc, out, err = run(SAMPLE, *args, cwd=tmp)
            files = {}
            for name in os.listdir(tmp):
                with open(os.path.join(tmp, name), encoding="utf-8", newline="") as f:
                    files[name] = f.read()
        return rc, out, err, files

    def test_default_name_and_round_trip(self):
        rc, out, _, files = self.run_in_tmp("--export-clean")
        self.assertEqual(rc, 0)
        self.assertEqual(list(files), ["bereinigt.csv"])
        self.assertIn("6 Einträge nach 'bereinigt.csv' exportiert", out)
        self.assertNotIn("== Statistik ==", out)  # nur der Export, kein Überblick
        again = entries_from_rows(load_any("bereinigt.csv", files["bereinigt.csv"]).rows)
        self.assertEqual(len(again), 6)
        self.assertEqual(find_duplicates(again, (KEY,)), [])
        mail = next(r for r in again.values() if r["Title"] == "Mail")
        self.assertEqual((mail["Password"], mail["Notes"]), ("pw-neu", "Neue Notiz"))
        self.assertIn("Privat-DB/Web,Mail,", files["bereinigt.csv"])  # Datenbankname wieder vorn

    def test_conflicts_and_losses_are_reported(self):
        _, out, _, _ = self.run_in_tmp("--export-clean")
        self.assertIn("1 Konflikt", out)
        self.assertIn("! Web / Mail  [max@example.org]: Password", out)
        self.assertIn("Frühere Passwörter (1)", out)

    def test_bitwarden_json_keeps_the_old_passwords(self):
        rc, _, _, files = self.run_in_tmp("--export-clean", "--export-format", "bitwarden-json")
        self.assertEqual(rc, 0)
        data = json.loads(files["bereinigt.json"])
        mail = next(i for i in data["items"] if i["name"] == "Mail")
        self.assertEqual(mail["login"]["password"], "pw-neu")
        self.assertEqual([h["password"] for h in mail["passwordHistory"]], ["pw-alt"])
        self.assertEqual(mail["passwordHistory"][0]["lastUsedDate"], "2024-01-10T10:00:00.000Z")

    def test_bitwarden_output_reports_no_password_history_loss(self):
        _, out, _, _ = self.run_in_tmp("--export-clean", "--export-format", "bitwarden-json")
        self.assertNotIn("Frühere Passwörter", out)

    def test_clean_kinds_widen_the_merge(self):
        _, out, _, files = self.run_in_tmp("--export-clean", "--clean-kinds", "key,login")
        self.assertIn("5 Einträge", out)
        self.assertEqual(len(entries_from_rows(load_any("x", files["bereinigt.csv"]).rows)), 5)

    def test_title_is_never_automatic(self):
        rc, _, err, _ = self.run_in_tmp("--export-clean", "--clean-kinds", "title")
        self.assertEqual(rc, 2)
        self.assertIn("nie automatisch", err)

    def test_dedupe_shows_the_plan_first(self):
        _, out, _, files = self.run_in_tmp("--dedupe", "--export-clean", "sauber.csv")
        self.assertIn("3 Dublettengruppen", out)
        self.assertIn("nach 'sauber.csv' exportiert", out)
        self.assertEqual(list(files), ["sauber.csv"])

    def test_json_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc, out, _ = run(SAMPLE, "--export-clean", "--format", "json", cwd=tmp)
        self.assertEqual(rc, 0)
        export = json.loads(out)["export"]
        self.assertEqual((export["path"], export["entries"]), ("bereinigt.csv", 6))
        self.assertEqual(export["lost"]["source"], {"Frühere Passwörter": 1})

    def test_incompatible_combinations(self):
        cases = (
            ((SAMPLE, SAMPLE, "--export-clean"), "einzelne Datei"),
            ((SAMPLE, "--export-clean", "--export-added"), "nicht kombiniert"),
            ((SAMPLE, "--export-clean", "--stats"), "nicht kombiniert"),
        )
        for args, message in cases:
            with self.subTest(args=args):
                rc, _, err = run(*args)
                self.assertEqual(rc, 2)
                self.assertIn(message, err)

    def test_export_format_still_needs_an_export(self):
        rc, _, err = run(SAMPLE, "--export-format", "bitwarden-json")
        self.assertEqual(rc, 2)
        self.assertIn("braucht --export-added", err)

    def test_unwritable_target_is_reported(self):
        rc, _, err = run(SAMPLE, "--export-clean", "/does/not/exist/out.csv")
        self.assertEqual(rc, 1)
        self.assertIn("kann nicht geschrieben werden", err)


if __name__ == "__main__":
    unittest.main()
