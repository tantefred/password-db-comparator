"""Tests der Dublettengruppen (Modul und ``--dedupe``)."""

import unittest

from csvcompare.duplicates import KEY, KINDS, LOGIN, TITLE, find_duplicates
from csvcompare.entries import entries_from_rows
from csvcompare.importers import load_any
from tests.helpers import fixture_path, read_fixture, run, run_json

SAMPLE = fixture_path("dubletten.csv")


def load_entries():
    return entries_from_rows(load_any("dubletten.csv", read_fixture("dubletten.csv")).rows)


class FindDuplicatesTests(unittest.TestCase):
    def setUp(self):
        self.entries = load_entries()
        self.groups = find_duplicates(self.entries)

    def test_finds_one_group_of_each_kind(self):
        self.assertEqual([g.kind for g in self.groups], [KEY, LOGIN, TITLE])

    def test_key_group_has_all_three_members_and_no_trash(self):
        group = self.groups[0]
        self.assertEqual([k.number for k in group.keys], [1, 2, 3])
        self.assertTrue(all("Papierkorb" not in k.group for k in group.keys))

    def test_login_group_ignores_url_case_and_trailing_slash(self):
        titles = sorted(k.title for k in self.groups[1].keys)
        self.assertEqual(titles, ["Bank", "Bank Online"])

    def test_title_group_ignores_case_of_username(self):
        self.assertEqual(sorted(k.group for k in self.groups[2].keys), ["Alt", "Web"])

    def test_differing_columns_ignore_timestamps(self):
        self.assertEqual(self.groups[0].differing, ("Password", "URL", "Notes", "TOTP", "Icon"))
        self.assertNotIn("Last Modified", self.groups[0].differing)

    def test_every_entry_belongs_to_at_most_one_group(self):
        keys = [key for group in self.groups for key in group.keys]
        self.assertEqual(len(keys), len(set(keys)))

    def test_kinds_can_be_restricted(self):
        only_login = find_duplicates(self.entries, (LOGIN,))
        self.assertEqual({g.kind for g in only_login}, {LOGIN})
        self.assertEqual([g.kind for g in find_duplicates(self.entries, (TITLE,))], [TITLE])

    def test_ids_are_stable_and_unique(self):
        again = find_duplicates(load_entries())
        self.assertEqual([g.id for g in self.groups], [g.id for g in again])
        self.assertEqual(len({g.id for g in self.groups}), 3)

    def test_stronger_kind_takes_the_entries_first(self):
        # Ohne „key“ bilden die Einträge Gruppen der Art „login“ (Mail #3 hat keine URL)
        only_login = find_duplicates(self.entries, (LOGIN,))
        self.assertEqual([len(g.keys) for g in only_login], [2, 2])
        self.assertEqual(KINDS, (KEY, LOGIN, TITLE))

    def test_no_duplicates_in_a_clean_file(self):
        clean = entries_from_rows(load_any("a", read_fixture("keepassium_a.csv")).rows)
        self.assertEqual(find_duplicates(clean), [])


class DedupeCliTests(unittest.TestCase):
    def test_text_lists_the_groups_without_secrets(self):
        rc, out, _ = run(SAMPLE, "--dedupe")
        self.assertEqual(rc, 0)
        self.assertIn("3 Dublettengruppen", out)
        self.assertIn("Unterschiede in: Password, URL, Notes, TOTP, Icon", out)
        self.assertNotIn("pw-neu", out)

    def test_show_secrets_reveals_values(self):
        _, out, _ = run(SAMPLE, "--dedupe", "--show-secrets")
        self.assertIn("pw-neu", out)

    def test_json_report(self):
        rc, report = run_json(SAMPLE, "--dedupe")
        self.assertEqual(rc, 0)
        self.assertEqual(report["mode"], "dedupe")
        self.assertEqual(report["group_count"], 3)
        self.assertEqual(report["kinds"], ["key", "login", "title"])
        first = report["groups"][0]
        self.assertEqual(len(first["members"]), 3)
        self.assertEqual(first["members"][1]["values"]["Password"], "(gesetzt)")
        self.assertEqual(first["members"][1]["entry"]["duplicate_index"], 2)

    def test_kinds_option(self):
        _, report = run_json(SAMPLE, "--dedupe", "--dedupe-kinds", "title,key")
        self.assertEqual([g["kind"] for g in report["groups"]], ["key", "title"])

    def test_unknown_kind_is_an_error(self):
        rc, _, err = run(SAMPLE, "--dedupe", "--dedupe-kinds", "foo")
        self.assertEqual(rc, 2)
        self.assertIn("Unbekannte Dublettenart 'foo'", err)

    def test_clean_file_reports_no_duplicates(self):
        _, out, _ = run(fixture_path("keepassium_a.csv"), "--dedupe")
        self.assertIn("Keine Dubletten gefunden.", out)

    def test_needs_a_single_file_and_no_other_mode(self):
        rc, _, err = run(SAMPLE, SAMPLE, "--dedupe")
        self.assertEqual(rc, 2)
        self.assertIn("einzelne Datei", err)
        rc, _, err = run(SAMPLE, "--dedupe", "--stats")
        self.assertEqual(rc, 2)
        self.assertIn("--dedupe und --stats können nicht kombiniert werden", err)


if __name__ == "__main__":
    unittest.main()
