"""Constants, default headers, and CSV field names for Blinkit scraper."""

BASE_URL = "https://blinkit.com"
CATEGORY_URL = "https://blinkit.com/cn/{slug}/cid/{l1_id}/{l2_id}"

# Default delay between requests (seconds)
DEFAULT_DELAY = 2.0

# Retry settings
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2  # seconds — exponential: 2, 4, 8

# If this fraction of categories return 403, suggest --browser
FAILURE_THRESHOLD = 0.5

# CSV output columns
CSV_FIELDS = [
    "date",
    "l1_category",
    "l1_category_id",
    "l2_category",
    "l2_category_id",
    "store_id",
    "variant_id",
    "variant_name",
    "group_id",
    "product_id",
    "selling_price",
    "mrp",
    "in_stock",
    "inventory",
    "is_sponsored",
    "image_url",
    "brand_id",
    "brand",
    "latitude",
    "longitude",
]

# Default headers mimicking a real browser
DEFAULT_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}

# Default output filename
DEFAULT_OUTPUT = "blinkit_products.csv"
