"""Tests unitaires de reconcile.py (doubles en mémoire, aucun accès fichier/DB)."""

import unittest

from reconcile import (
    TableRecord,
    expand_pattern_name,
    match_referenced_to_actual,
    reconcile,
)


class TestExpandPatternName(unittest.TestCase):
    def test_static_partition_matches_pattern(self) -> None:
        self.assertTrue(expand_pattern_name("mariadb://V5_data_{AAAA}/static_{MM}_d{1-3}",
                                            "mariadb://V5_data_2024/static_03_d2"))

    def test_plain_name_matches_itself(self) -> None:
        self.assertTrue(expand_pattern_name("mariadb://V5/comptes", "mariadb://V5/comptes"))

    def test_mismatch_returns_false(self) -> None:
        self.assertFalse(expand_pattern_name("mariadb://V5/comptes", "mariadb://V5/photolive"))


class TestReconcile(unittest.TestCase):
    def test_orphan_ghost_and_matched_are_partitioned(self) -> None:
        referenced = [
            TableRecord(name="mariadb://V5/comptes", source="code"),
            TableRecord(name="mariadb://V5/table_fantome", source="code"),
        ]
        actual = [
            TableRecord(name="mariadb://V5/comptes", source="db"),
            TableRecord(name="mariadb://V5/table_orpheline", source="db"),
        ]
        result = reconcile(referenced, actual)
        self.assertEqual([r.name for r in result.matched], ["mariadb://V5/comptes"])
        self.assertEqual([r.name for r in result.ghosts], ["mariadb://V5/table_fantome"])
        self.assertEqual([r.name for r in result.orphans], ["mariadb://V5/table_orpheline"])

    def test_partitioned_reference_matches_concrete_tables(self) -> None:
        referenced = [TableRecord(name="mariadb://V5_data_{AAAA}/static_{MM}_d{1-3}", source="code")]
        actual = [
            TableRecord(name="mariadb://V5_data_2023/static_11_d1", source="db"),
            TableRecord(name="mariadb://V5_data_2024/static_03_d2", source="db"),
        ]
        result = reconcile(referenced, actual)
        self.assertEqual(len(result.matched), 2)
        self.assertEqual(result.ghosts, [])
        self.assertEqual(result.orphans, [])


class TestMatchReferencedToActual(unittest.TestCase):
    def test_csv_row_converts_to_record(self) -> None:
        row = {"system": "mariadb", "database": "V5", "table": "comptes"}
        record = match_referenced_to_actual(row)
        self.assertEqual(record.name, "mariadb://V5/comptes")


if __name__ == "__main__":
    unittest.main()
