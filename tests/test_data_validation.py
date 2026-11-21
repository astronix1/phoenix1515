import json
import unittest
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]


class SeedDataValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.products = json.loads(
            (BASE_DIR / "data" / "products.json").read_text(encoding="utf-8")
        )
        cls.shoppers = json.loads(
            (BASE_DIR / "data" / "shoppers.json").read_text(encoding="utf-8")
        )

    def test_catalog_has_unique_product_ids(self):
        ids = [product["product_id"] for product in self.products]
        self.assertEqual(len(ids), len(set(ids)))

    def test_required_product_fields_are_present(self):
        required = {"product_id", "name", "category", "brand", "price_inr", "stock"}
        for product in self.products:
            self.assertTrue(required.issubset(product), product["product_id"])

    def test_product_references_in_orders_are_valid(self):
        product_ids = {product["product_id"] for product in self.products}
        for shopper in self.shoppers:
            for order in shopper.get("orders", []):
                self.assertIn(order["product_id"], product_ids)


if __name__ == "__main__":
    unittest.main()
