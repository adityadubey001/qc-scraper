"""Tests for CSV writer and deduplication."""

import csv
import os
import tempfile

import pytest

from src.config import CSV_FIELDS
from src.writer import print_summary, write_products


@pytest.fixture
def sample_products():
    return [
        {
            "date": "2026-02-10",
            "l1_category": "Dairy",
            "l1_category_id": 2,
            "l2_category": "Milk",
            "l2_category_id": 21,
            "store_id": 701,
            "variant_id": 10001,
            "variant_name": "Amul Milk 500ml",
            "group_id": 3001,
            "product_id": 5001,
            "selling_price": 27.0,
            "mrp": 29.0,
            "in_stock": 1,
            "inventory": 50,
            "is_sponsored": 0,
            "image_url": "https://example.com/milk.jpg",
            "brand_id": 201,
            "brand": "Amul",
            "latitude": 28.6,
            "longitude": 77.2,
        },
        {
            "date": "2026-02-10",
            "l1_category": "Dairy",
            "l1_category_id": 2,
            "l2_category": "Milk",
            "l2_category_id": 21,
            "store_id": 701,
            "variant_id": 10002,
            "variant_name": "Mother Dairy 1L",
            "group_id": 3002,
            "product_id": 5002,
            "selling_price": 66.0,
            "mrp": 68.0,
            "in_stock": 1,
            "inventory": 30,
            "is_sponsored": 0,
            "image_url": "https://example.com/md.jpg",
            "brand_id": 202,
            "brand": "Mother Dairy",
            "latitude": 28.6,
            "longitude": 77.2,
        },
    ]


class TestWriteProducts:
    def test_writes_csv_with_header(self, sample_products, tmp_path):
        output = str(tmp_path / "test.csv")
        written, dupes = write_products(sample_products, output)

        assert written == 2
        assert dupes == 0
        assert os.path.exists(output)

        with open(output, newline="") as f:
            reader = csv.DictReader(f)
            assert reader.fieldnames == CSV_FIELDS
            rows = list(reader)
            assert len(rows) == 2
            assert rows[0]["variant_name"] == "Amul Milk 500ml"

    def test_deduplicates_by_variant_id(self, sample_products, tmp_path):
        # Add a duplicate
        dupe = sample_products[0].copy()
        products_with_dupe = sample_products + [dupe]

        output = str(tmp_path / "test.csv")
        written, dupes = write_products(products_with_dupe, output)

        assert written == 2
        assert dupes == 1

    def test_append_mode(self, sample_products, tmp_path):
        output = str(tmp_path / "test.csv")

        # First write
        write_products(sample_products[:1], output)

        # Append — should skip the first product (already exists)
        written, dupes = write_products(sample_products, output, append=True)
        assert written == 1  # Only the second product is new
        assert dupes == 1

        with open(output, newline="") as f:
            rows = list(csv.DictReader(f))
            assert len(rows) == 2  # 1 original + 1 appended

    def test_empty_products(self, tmp_path):
        output = str(tmp_path / "test.csv")
        written, dupes = write_products([], output)
        assert written == 0
        assert dupes == 0


class TestPrintSummary:
    def test_summary_format(self):
        summary = print_summary(
            total_products=100,
            duplicates=10,
            categories_scraped=20,
            categories_failed=2,
            output_path="output.csv",
        )
        assert "100" in summary
        assert "10" in summary
        assert "90" in summary
        assert "20" in summary
        assert "2" in summary
        assert "output.csv" in summary
