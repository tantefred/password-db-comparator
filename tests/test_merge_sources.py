"""Tests: Beim Zusammenführen bleiben Bitwarden-Daten aller Mitglieder erhalten."""

import json
import os
import tempfile
import unittest

from csvcompare.duplicates import find_duplicates
from csvcompare.entries import entries_from_rows
from csvcompare.importers import load_any
from csvcompare.merge import BOTH, KEEP_ONE, MERGE, Decision, clean_entries, merge_rows
from csvcompare.service import UsageError, analyze
from tests.helpers import fixture_path, read_fixture, run

SAMPLE = fixture_path("bitwarden_dubletten.json")


def members():
    rows = load_any("b.json", read_fixture("bitwarden_dubletten.json")).rows
    return [row for row in rows if row["Title"] == "Mail"]


def written(*args):
    with tempfile.TemporaryDirectory() as tmp:
        rc, out, err = run(
            SAMPLE, "--export-clean", "--export-format", "bitwarden-json", *args, cwd=tmp
        )
        with open(os.path.join(tmp, "bereinigt.json"), encoding="utf-8") as f:
            data = json.load(f)
    mail = next(i for i in data["items"] if i["name"] == "Mail")
    return rc, out, mail, data


class MergeSourcesTests(unittest.TestCase):
    def test_newest_entry_is_the_base_and_keeps_its_id(self):
        _, _, mail, data = written()
        self.assertEqual(len(data["items"]), 2)
        self.assertEqual(mail["id"], "new-1")
        self.assertEqual(mail["login"]["password"], "pw-neu")

    def test_passkeys_of_all_members_are_kept(self):
        _, _, mail, _ = written()
        ids = [k["credentialId"] for k in mail["login"]["fido2Credentials"]]
        self.assertEqual(ids, ["cred-2", "cred-1"])

    def test_collections_are_united(self):
        self.assertEqual(written()[2]["collectionIds"], ["coll-2", "coll-1"])

    def test_password_history_is_united_without_repeats(self):
        history = [h["password"] for h in written()[2]["passwordHistory"]]
        self.assertEqual(history, ["pw-alt", "pw-aelter"])  # pw-alt steht nur einmal

    def test_uris_keep_their_match_mode(self):
        uris = written()[2]["login"]["uris"]
        self.assertEqual(
            [(u["uri"], u["match"]) for u in uris],
            [("https://mail.example.org", 3), ("https://alt.example.org", 1)],
        )

    def test_custom_fields_keep_their_type_when_filled_from_an_older_entry(self):
        fields = written()[2]["fields"]
        self.assertEqual([(f["name"], f["type"]) for f in fields], [("PIN", 1)])

    def test_favorite_is_set_if_any_member_has_it(self):
        self.assertTrue(written()[2]["favorite"])

    def test_inputs_are_not_modified(self):
        rows = members()
        before = json.dumps(rows, sort_keys=True, default=str)
        merge_rows(rows)
        self.assertEqual(json.dumps(rows, sort_keys=True, default=str), before)

    def test_keepass_csv_reports_what_cannot_be_stored(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, out, _ = run(SAMPLE, "--export-clean", cwd=tmp)
        self.assertIn("nicht speicherbar", out)
        for label in ("Passkeys", "Sammlungen", "Passwort-Verlauf"):
            self.assertIn(label, out)

    def test_organizations_that_differ_are_reported(self):
        rows = members()
        rows[0]["_source"]["organizationId"] = "org-a"
        rows[1]["_source"]["organizationId"] = "org-b"
        entries = entries_from_rows(rows)
        cleaned = clean_entries(entries, find_duplicates(entries))
        self.assertEqual(len(cleaned.merged[0].notes), 1)
        self.assertIn("Organisation", cleaned.merged[0].notes[0])


class ConflictColumnTests(unittest.TestCase):
    def row(self, **values):
        base = dict.fromkeys(
            ("Group", "Title", "Username", "Password", "URL", "Notes", "TOTP", "Icon"), ""
        )
        base.update({"Last Modified": "", "Created": "", "Fields": "", "Type": "login"})
        base.update(values)
        return base

    def test_fields_and_type_are_conflicts(self):
        a = self.row(Fields="PIN: 1", Type="login", **{"Last Modified": "2024-01-01T00:00:00Z"})
        b = self.row(Fields="PIN: 2", Type="note", **{"Last Modified": "2024-02-01T00:00:00Z"})
        merged, conflicts = merge_rows([a, b])
        self.assertEqual(sorted(conflicts), ["Fields", "Type"])
        self.assertEqual((merged["Fields"], merged["Type"]), ("PIN: 2", "note"))

    def test_base_type_login_is_not_replaced_by_a_gap_fill(self):
        a = self.row(Type="note", **{"Last Modified": "2024-01-01T00:00:00Z"})
        b = self.row(Type="login", **{"Last Modified": "2024-02-01T00:00:00Z"})
        self.assertEqual(merge_rows([a, b])[0]["Type"], "login")

    def test_fields_can_be_joined(self):
        a = self.row(Fields="A: 1", **{"Last Modified": "2024-01-01T00:00:00Z"})
        b = self.row(Fields="B: 2", **{"Last Modified": "2024-02-01T00:00:00Z"})
        self.assertEqual(merge_rows([a, b], {"Fields": BOTH})[0]["Fields"], "B: 2 A: 1")

    def test_both_is_refused_for_other_columns(self):
        a, b = self.row(Password="a"), self.row(Password="b")
        with self.assertRaises(ValueError):
            merge_rows([a, b], {"Password": BOTH})


class DecisionValidationTests(unittest.TestCase):
    def setUp(self):
        entries = entries_from_rows(members())
        self.groups = find_duplicates(entries)
        self.entries = entries

    def test_invalid_picks_are_rejected(self):
        gid = self.groups[0].id
        bad = (
            Decision(MERGE, picks={"Password": BOTH}),
            Decision(MERGE, picks={"Password": True}),
            Decision(KEEP_ONE, keep=True),
        )
        for decision in bad:
            with self.subTest(decision=decision), self.assertRaises(ValueError):
                clean_entries(self.entries, self.groups, {gid: decision})

    def test_unknown_group_message_asks_to_evaluate_again(self):
        with self.assertRaisesRegex(ValueError, "neu auswerten"):
            clean_entries(self.entries, self.groups, {"fremd": Decision(MERGE)})

    def test_server_answers_with_a_usage_error_for_both_on_password(self):
        text = read_fixture("dubletten.csv")
        first = analyze("d.csv", text, None, None, {"mode": "clean"})["report"]["groups"][0]
        decisions = {first["id"]: {"action": "merge", "picks": {"Password": "both"}}}
        with self.assertRaises(UsageError):
            analyze(
                "d.csv",
                text,
                None,
                None,
                {"mode": "clean", "export_clean": True, "decisions": decisions},
            )


class CleanKindsOptionTests(unittest.TestCase):
    csv = fixture_path("dubletten.csv")

    def test_kinds_options_need_their_modes(self):
        for args, message in (
            (("--clean-kinds", "key"), "--clean-kinds braucht --export-clean"),
            (("--dedupe-kinds", "key"), "--dedupe-kinds braucht --dedupe"),
        ):
            with self.subTest(args=args):
                rc, _, err = run(self.csv, *args)
                self.assertEqual(rc, 2)
                self.assertIn(message, err)

    def test_dedupe_kinds_restrict_what_is_cleaned(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc, out, _ = run(
                self.csv,
                "--dedupe",
                "--dedupe-kinds",
                "login,title",
                "--export-clean",
                "--clean-kinds",
                "login",
                cwd=tmp,
            )
        self.assertEqual(rc, 0)
        # Mit nur „login“ und „title“ bilden die drei Mail-Einträge keine Gruppe der Art „key“;
        # zusammengeführt werden die beiden Gruppen der Art „login“.
        self.assertIn("6 Einträge nach 'bereinigt.csv' exportiert", out)
        self.assertIn("2 Gruppen bearbeitet", out)

    def test_empty_intersection_is_an_error(self):
        rc, _, err = run(self.csv, "--dedupe-kinds", "login", "--export-clean")
        self.assertEqual(rc, 2)
        self.assertIn("würde nichts zusammenführen", err)


if __name__ == "__main__":
    unittest.main()
