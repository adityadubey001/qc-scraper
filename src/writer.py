"""CSV output writer with deduplication and summary statistics."""

import csv
import os

from .config import CSV_FIELDS


def write_products(
    products: list[dict],
    output_path: str,
    append: bool = False,
    csv_fields: list[str] | None = None,
) -> tuple[int, int]:
    """Write products to CSV, deduplicating by variant_id.

    Returns (written_count, duplicate_count).
    """
    fields = csv_fields or CSV_FIELDS
    seen_ids = set()
    unique_products = []

    # If appending, load existing variant_ids first
    if append and os.path.exists(output_path):
        with open(output_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                vid = row.get("variant_id")
                if vid:
                    seen_ids.add(str(vid))

    duplicate_count = 0
    for product in products:
        vid = str(product.get("variant_id", ""))
        if vid and vid in seen_ids:
            duplicate_count += 1
            continue
        seen_ids.add(vid)
        unique_products.append(product)

    mode = "a" if append and os.path.exists(output_path) else "w"
    write_header = mode == "w" or not os.path.exists(output_path)

    with open(output_path, mode, newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerows(unique_products)

    return len(unique_products), duplicate_count


def print_summary(
    total_products: int,
    duplicates: int,
    categories_scraped: int,
    categories_failed: int,
    output_path: str,
) -> str:
    """Format a summary string of the scrape results."""
    lines = [
        "",
        "=" * 50,
        "  Scrape Complete",
        "=" * 50,
        f"  Categories scraped : {categories_scraped}",
        f"  Categories failed  : {categories_failed}",
        f"  Total products     : {total_products}",
        f"  Duplicates removed : {duplicates}",
        f"  Unique products    : {total_products - duplicates}",
        f"  Output file        : {output_path}",
        "=" * 50,
    ]
    return "\n".join(lines)
