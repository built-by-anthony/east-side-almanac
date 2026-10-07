"""NorthstarMLS Local Market Update PDFs (via Minneapolis Area Realtors / 10k Research) -> raw PDF + long fact table."""
import io
import logging
import re
from datetime import date, datetime, timezone
from urllib.parse import quote 

import pdfplumber
import polars as pl 
import requests

from app import config, storage

log = logging.getLogger(__name__)

# {YYYY-MM} selects a specific report month; the city name is URL-encoded ("North%20St.%20Paul").
URL_TEMPLATE = "https://maar.stats.10kresearch.com/docs/lmu/{month}/x/{city}"

CITIES = ["Woodbury", "Lake Elmo", "Oakdale", "Maplewood", "Stillwater", "Cottage Grove", "North St. Paul"]

# PDF row label -> our metric name. Names match REdfin's where the concept is the same; 
# kept distinct where the definition may differ 
LABELS = {
    "New Listings": "new_listings",
    "Closed Sales": "homes_sold",
    "Median Sales Price": "median_sale_price",
    "Average Sales Price": "average_sale_price",
    "Price Per Square Foot": "price_per_sqft",
    "Percent of Original List Price Received": "pct_of_original_list_received",
    "Days on Market Until Sale": "days_on_market",
    "Inventory of Homes for Sale": "inventory",
    "Months Supply of Inventory": "months_of_supply",
}

MONTHS = {name: i for i, name in enumerate(
    ["January", "February", "March", "April", "May", "June",
     "July", "August", "September", "October", "November", "December"], start=1)}

# "Local Market Update – August 2026". The dash is an en dash in the PDF; accept a hyphen too.
REPORT_RE = re.compile(r"Local Market Update\s+[–-]\s+([A-Z][a-z]+)\s+(\d{4})")

# One value cell: "--", "$499,500", "1,786", "98.1%", "2.8".
VALUE = r"(--|\$?[\d,]+(?:\.\d+)?%?)"
# One change cell: "--", "+ 9.4%", "-16.1%", "0.0%" (the sign is optional and may be followed by a space).
CHANGE = r"(--|[+-]?\s?[\d.]+%)"

COLUMNS = ["geo", "geo_level", "metric", "period_start", "period_type", "value", "source", "pulled_at"]

def add_months(d: date, n: int) -> date:
    """First of the month n months from d (n may be negative)."""
    index = d.year * 12 + (d.month - 1) + n
    return date(index // 12, index % 12 + 1, 1)

def row_pattern(label: str) -> re.Pattern: 
    # Label (optionally followed by the "*" footnote marker), then six cells:
    # prior-year month, current month, change, prior rolling 12, current rolling 12, change.
    # ^...$ with MULTILINE: the whole line must be a table row, so the chart's
    # "New Listings Closed Sales" line can never match.
    return re.compile(
        rf"^{re.escape(label)}\*?\s+{VALUE}\s+{VALUE}\s+{CHANGE}\s+{VALUE}\s+{VALUE}\s+{CHANGE}$",
        re.MULTILINE,
    )    

def to_number(cell: str) -> float | None: 
    """ "--" means the report has no value (e.g. inventory has no rolling-12 figure): no row."""
    if cell == "--":
        return None
    return float(cell.replace("$", "").replace(",", "").replace("%", ""))

def parse(pdf: bytes, city: str) -> tuple[date, list[dict]]:
    """PDF bytes -> (report month, fact rows without geo/source/pulled_at). Pure: no I/O, easy to test."""
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        if len(doc.pages) != 1:
            raise RuntimeError(f"lmu {city}: expected 1 page, got {len(doc.pages)}")
        text = doc.pages[0].extract_text() or ""

    # Search the whole text for patterns rather than relying on line numbers:
    # positions shift if the template gains or loses a line. 

    # pdfplumber merges the big city title with the three "Change in ..." header boxes
    # beside it, so the title line reads "Woodbury New Listings Closed Sales Median Sales Price".
    # Matching that whole line checks the PDF is about this exact city, not just
    # mentions it somewhere (e.g. in the chart legend).
    title = re.compile(rf"^{re.escape(city)} New Listings Closed Sales Median Sales Price$", re.MULTILINE)
    if not title.search(text):
        raise RuntimeError(f"lmu {city}: title line for this city not found in PDF")

    m = REPORT_RE.search(text)
    if not m or m[1] not in MONTHS:
        raise RuntimeError(f"lmu {city}: report month header not found")
    month = date(int(m[2]), MONTHS[m[1]], 1)

    # The four periods each row describes. 
    periods = [
        (add_months(month, -12), "month"),             # same month, prior year (as reported today)
        (month, "month"),                              # the report month
        (add_months(month, -23), "rolling_12_month"),  # 12 months ending one year ago
        (add_months(month, -11), "rolling_12_month"),  # 12 months ending in the report month
    ]

    rows = []
    for label, metric in LABELS.items():
        match = row_pattern(label).search(text)
        if not match:
            # A missing row means the layout changed: fail rather than store a partial report.
            raise RuntimeError(f"lmu {city}: row {label!r} not found; layout may have changed")
        prior, current, _change, r12_prior, r12_current, _r12_change = match.groups()
        # The two change columns are derived (rule 1), so they're dropped.
        for (period_start, period_type), cell in zip(periods, [prior, current, r12_prior, r12_current]):
            value = to_number(cell)
            if value is not None:
                rows.append({
                    "metric": metric,
                    "period_start": period_start,
                    "period_type": period_type,
                    "value": value,
                })
    return month, rows

def fetch(session: requests.Session, month: date, city: str) -> bytes:
    url = URL_TEMPLATE.format(month=f"{month:%Y-%m}", city=quote(city))
    resp = session.get(url, timeout=60)
    resp.raise_for_status()  # no secret in this URL
    if not resp.headers.get("Content-Type", "").startswith("application/pdf"):
        raise RuntimeError(f"lmu {city}: expected a PDF, got {resp.headers.get('Content-Type')}")
    return resp.content

def run() -> None: 
    curated = config.curated_root()
    raw_root = config.raw_root()

    pulled_at = datetime.now(timezone.utc)
    day = f"{pulled_at:%Y-%m-%d}"
    # Reports publish around the 8th of the following month, so ask for last month.
    month = add_months(date(pulled_at.year, pulled_at.month, 1), -2)
    log.info("lmu: requesting report month %s", f"{month:%Y-%m}")

    rows = []
    with requests.Session() as session: 
        for city in CITIES: 
            pdf = fetch(session, month, city)
            # Raw first: the PDF as received, so a parse failure can be debugged and replayed.
            storage.write_bytes(f"{raw_root}/lmu/{day}/{month:%Y-%m}/{city}.pdf", pdf)

            report_month, city_rows = parse(pdf, city)
            # The server might return a different month (e.g. not yet published). Fail, don't mislabel.
            if report_month != month:
                raise RuntimeError(f"lmu {city}: asked for {month:%Y-%m}, PDF is {report_month:%Y-%m}")
            log.info("lmu: %s, %d rows", city, len(city_rows))
            rows.extend({**r, "geo": city} for r in city_rows)

    df = (
            pl.DataFrame(rows)
            .with_columns(
                pl.lit("city").alias("geo_level"),
                pl.lit("northstar_lmu").alias("source"),
                pl.lit(pulled_at).alias("pulled_at"),
        )
        .select(COLUMNS)
    )

    # One file per pull date, same as the other jobs.
    path = f"{curated}/lmu/{day}.parquet"
    df.write_parquet(path, mkdir=True)
    log.info("lmu: wrote %d rows to %s", df.height, path)