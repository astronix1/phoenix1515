"""Validation script to verify data integrity of catalogue.json and shoppers.json."""

import json
import os
import sys


def validate():
    base_dir = os.path.dirname(__file__)
    cat_path = os.path.join(base_dir, "catalogue.json")
    shop_path = os.path.join(base_dir, "shoppers.json")

    errors = []

    # 1. Validate Catalogue
    if not os.path.exists(cat_path):
        errors.append(f"Catalogue file not found at {cat_path}")
    else:
        with open(cat_path, "r", encoding="utf-8") as f:
            products = json.load(f)

        if not isinstance(products, list) or len(products) == 0:
            errors.append("Catalogue must be a non-empty list of products.")

        product_ids = set()
        for idx, p in enumerate(products):
            pid = p.get("product_id")
            if not pid:
                errors.append(f"Product at index {idx} missing product_id")
            elif pid in product_ids:
                errors.append(f"Duplicate product_id: {pid}")
            else:
                product_ids.add(pid)

            if not p.get("title") or not p.get("category") or not p.get("brand"):
                errors.append(f"Product {pid} missing essential metadata (title, category, or brand)")

            if p.get("price") is None or float(p.get("price")) < 0:
                errors.append(f"Product {pid} has invalid price: {p.get('price')}")

            if p.get("rating") is not None and not (0 <= float(p.get("rating")) <= 5):
                errors.append(f"Product {pid} has out-of-range rating: {p.get('rating')}")

    # 2. Validate Shoppers & Orders
    if not os.path.exists(shop_path):
        errors.append(f"Shoppers file not found at {shop_path}")
    else:
        with open(shop_path, "r", encoding="utf-8") as f:
            shop_data = json.load(f)

        shoppers = shop_data.get("shoppers", [])
        orders = shop_data.get("orders", [])

        shopper_ids = set()
        for s in shoppers:
            cid = s.get("customer_id")
            if not cid:
                errors.append("Shopper missing customer_id")
            elif cid in shopper_ids:
                errors.append(f"Duplicate customer_id: {cid}")
            else:
                shopper_ids.add(cid)

            if "@" not in s.get("email", ""):
                errors.append(f"Customer {cid} has invalid email: {s.get('email')}")

        for o in orders:
            oid = o.get("order_id")
            cid = o.get("customer_id")
            pid = o.get("product_id")

            if cid not in shopper_ids:
                errors.append(f"Order {oid} references non-existent customer {cid}")

            if product_ids and pid not in product_ids:
                errors.append(f"Order {oid} references non-existent product {pid}")

            if not o.get("order_status"):
                errors.append(f"Order {oid} missing order_status")

    if errors:
        print("❌ Data validation failed with errors:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    else:
        print(f"✅ Data validation passed! {len(products)} products, {len(shoppers)} shoppers, {len(orders)} orders verified.")


if __name__ == "__main__":
    validate()
