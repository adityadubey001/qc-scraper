"""Constants and defaults for the Swiggy Instamart scraper."""

SWIGGY_BASE_URL = "https://www.swiggy.com"
INSTAMART_URL = "https://www.swiggy.com/instamart"
CATEGORY_LISTING_URL = (
    "https://www.swiggy.com/instamart/category-listing"
    "?categoryName={name}&custom_back=true&filteredEntity=Category"
)

# Delay between page navigations (seconds) — slower than Blinkit due to heavier anti-bot
DEFAULT_DELAY = 3.0

# Scrolling behaviour
SCROLL_PAUSE = 1.5   # seconds between scroll actions
MAX_SCROLLS = 20     # max scroll attempts per category page

# Page load timeout (ms)
PAGE_TIMEOUT = 30_000
NAV_TIMEOUT = 60_000

# Default output filename
DEFAULT_OUTPUT = "swiggy_products.csv"

# Categories cache file
CATEGORIES_CACHE = "swiggy_categories.csv"
