"""Check the data against the schema. Every order must point at a real product.

Run: python -m data.validate_data
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main():
    products = json.loads((HERE / "products.json").read_text())
    shoppers = json.loads((HERE / "shoppers.json").read_text())
    ids = {p["product_id"] for p in products}
    errors = []
    if len(products) < 250:
        errors.append(f"only {len(products)} products, need 250+")
    if len({p["category"] for p in products}) < 5:
        errors.append("fewer than 5 categories")
    for product in products:
        for field in ("product_id", "name", "category", "brand", "price_inr", "stock"):
            if field not in product:
                errors.append(f"{product.get('product_id')}: missing {field}")
        if product["price_inr"] < 0 or product["stock"] < 0:
            errors.append(f"{product['product_id']}: negative price/stock")
    if len(shoppers) < 25:
        errors.append(f"only {len(shoppers)} shoppers, need 25+")
    for shopper in shoppers:
        for order in shopper.get("orders", []):
            if order["product_id"] not in ids:
                errors.append(f"{shopper['shopper_id']}: order {order['order_id']} "
                              f"points at unknown {order['product_id']}")
    if errors:
        print("\n".join(errors))
        sys.exit(1)
    print(f"OK: {len(products)} products, {len(shoppers)} shoppers, "
          f"{sum(len(s['orders']) for s in shoppers)} orders")


if __name__ == "__main__":
    main()
