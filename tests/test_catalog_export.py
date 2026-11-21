import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from scripts.export_catalog import filter_products, write_catalog


class CatalogExportTests(unittest.TestCase):
    def setUp(self):
        self.products = [
            {"product_id": "P-1", "name": "Blue Speaker", "category": "Electronics", "brand": "Acme"},
            {"product_id": "P-2", "name": "Running Shoe", "category": "Footwear", "brand": "Acme"},
        ]

    def test_filters_are_case_insensitive(self):
        selected = filter_products(self.products, category="electronics", brand="ACME")
        self.assertEqual([product["product_id"] for product in selected], ["P-1"])

    def test_writes_json_export(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "catalog.json"
            write_catalog(self.products, output, "json")
            exported = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(exported, self.products)

    def test_writes_csv_export(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "catalog.csv"
            write_catalog(self.products, output, "csv")
            with output.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual([row["product_id"] for row in rows], ["P-1", "P-2"])


if __name__ == "__main__":
    unittest.main()
