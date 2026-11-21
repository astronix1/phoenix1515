"""Export the seed catalogue as JSON or CSV."""

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Iterable


BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = BASE_DIR / "data" / "products.json"


def filter_products(
    products: Iterable[dict],
    category: str | None = None,
    brand: str | None = None,
) -> list[dict]:
    filtered = list(products)
    if category:
        category_lower = category.casefold()
        filtered = [
            product
            for product in filtered
            if str(product.get("category", "")).casefold() == category_lower
        ]
    if brand:
        brand_lower = brand.casefold()
        filtered = [
            product
            for product in filtered
            if str(product.get("brand", "")).casefold() == brand_lower
        ]
    return filtered


def write_catalog(products: list[dict], output: Path, format_name: str) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    if format_name == "json":
        output.write_text(json.dumps(products, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return

    fieldnames = [
        "product_id",
        "name",
        "category",
        "brand",
        "price_inr",
        "stock",
        "rating",
        "description",
    ]
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for product in products:
            writer.writerow(product)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--format", choices=("json", "csv"), default="json")
    parser.add_argument("--category")
    parser.add_argument("--brand")
    args = parser.parse_args()

    try:
        products = json.loads(args.source.read_text(encoding="utf-8"))
        selected = filter_products(products, args.category, args.brand)
        write_catalog(selected, args.output, args.format)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Exported {len(selected)} products to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
