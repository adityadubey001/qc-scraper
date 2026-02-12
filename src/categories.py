"""Category dataclass and CSV loader for Blinkit L1/L2 categories."""

import csv
import os
from dataclasses import dataclass


@dataclass
class Category:
    """A Blinkit L2 (sub) category."""
    l1_name: str
    l1_id: int
    l2_name: str
    l2_id: int
    slug: str

    @property
    def display_name(self) -> str:
        return f"{self.l1_name} > {self.l2_name}"


def load_categories(csv_path: str | None = None) -> list[Category]:
    """Load categories from the bundled categories.csv file.

    CSV format: l1_name,l1_id,l2_name,l2_id,slug
    """
    if csv_path is None:
        csv_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "categories.csv",
        )

    categories = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            categories.append(
                Category(
                    l1_name=row["l1_name"],
                    l1_id=int(row["l1_id"]),
                    l2_name=row["l2_name"],
                    l2_id=int(row["l2_id"]),
                    slug=row["slug"],
                )
            )
    return categories


def filter_categories(
    categories: list[Category], l1_filter: str | None = None
) -> list[Category]:
    """Filter categories by L1 name (case-insensitive substring match)."""
    if not l1_filter:
        return categories
    lower = l1_filter.lower()
    return [c for c in categories if lower in c.l1_name.lower()]
