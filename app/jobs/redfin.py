"""Redfin job: Housing Market Tracker (all cities, monthly file) -> raw CSV + long fact table."""
import logging
import tempfile
from datetime import datetime, timezone, date
from email.utils import parsedate_to_datetime
from pathlib import Path

import polars as pl 
import requests 

from app import config, storage, schema

log = logging.getLogger(__name__)

# Public S3 object behind the Data Center download form. The form downloads this
# whoel file and filters it in the browswer; there i no per-state file.
URL = "https://redfin-public-data.s3.us-west-2.amazonaws.com/redfin_data_center/housing_market/monthly/all_cities.csv"

# Redfin Region ID -> our geo name. Filter on IDs, not names: names repeat even within
# a state (two "Aaronsburg, PA"), and spellings can change ("St." vs "Saint"). 
CITIES = {
    18242: "Woodbury",
    8750: "Lake Elmo",
    12183: "Oakdale",
    10305: "Maplewood",
    16123: "Stillwater",
    3510: "Cottage Grove",
    12062: "North St. Paul",
}

# The ID map is Redfin-specific; the names must match the asset's city list exactly.
if set(CITIES.values()) != set(schema.CITIES):
    raise RuntimeError(f"redfin: CITIES out of sync with schema.CITIES: {set(CITIES.values()) ^ set(schema.CITIES)}")

# Every row in the current file is a rolling 3-month window. If Redfin changes this, 
# period_type would silently be wrong, so the job checks it and fails instead. 
EXPECTED_FREQUENCY = "Rolling 3 Months"

# Source column -> our metric name. Levels and counts only: every MOM/YOY column is 
# left out (rule 1). Units stay as published, e.g. sale-to-list is 95.45, not 0.9545
METRICS = {
    "HOMES SOLD": "homes_sold",
    "MEDIAN SALE PRICE NSA ($)": "median_sale_price",
    "MEDIAN DAYS ON MARKET (DAYS)": "median_days_on_market",
    "AVERAGE SALE TO LIST RATIO (%)": "avg_sale_to_list_pct",
    "SHARE SOLD ABOVE ORIGINAL LIST (%)": "share_sold_above_list_pct",
    "NEW LISTINGS": "new_listings",
    "ACTIVE LISTINGS": "active_listings",
    "INVENTORY": "inventory",
    "PENDING SALES": "pending_sales",
    "MEDIAN NEW LISTING PRICE ($)": "median_new_listing_price",
    "MEDIAN NEW LISTING PRICE PER SQ.FT. ($)": "median_new_listing_price_per_sqft",
     "MEDIAN SALE PRICE PER SQ.FT. ($)": "median_sale_price_per_sqft",
      "MONTHS OF SUPPLY": "months_of_supply_closed_pace",
     "PERCENT OFF MARKET IN TWO WEEKS (%)": "off_market_in_two_weeks_pct",
}

schema.require_known(METRICS.values(), "redfin")

def download(dest: Path) -> date:
    """Stream the file to disk in 8 MB chunks; never hold in memory. Returns the file's Last-Modified date."""
    # timeout=(connect, read): 10s to connect, then up to 300s of silence between chunks. 
    with requests.get(URL, stream=True, timeout=(10, 300)) as resp: 
        # No secret in this URL, so reaise_for_status() is safe here (unlike Fred).
        resp.raise_for_status() 
        expected = int(resp.headers["Content-Length"])

        # The only publication marker Redfin gives. Weak: re-uploads change it without changing data.
        as_of = parsedate_to_datetime(resp.headers["Last-Modified"]).date()
        log.info(
            "redfin: downloading %.0f MB, Last-Modified %s",
            expected / 1e6, resp.headers.get("Last-Modified")
        )
        written = 0
        with dest.open("wb") as f: 
            for chunk in resp.iter_content(chunk_size=8 * 1024 * 1024):
                f.write(chunk)
                written += len(chunk)
    # A dropped connection can end the stream early without raising. Compare sizes
    # so a truncated file fails here instead of quietly losing cities later.
    if written != expected:
        raise RuntimeError(f"redfin: truncated download, got {written} of {expected} bytes")

    return as_of

def read_cities(path: Path) -> pl.DataFrame: 
    """Lazily scan the 1.1 GB CSV and keep only our seven cities' rows."""
    # infer_scheama=False: read every column as text and cast the ones we keep explicity. 
    # Inference only looks at the first 100 rows, which is a guess about 4.5 million rows. 
    lf = pl.scan_csv(path, infer_schema=False, null_values="NA")

    # Schema drift check: fail loudly if Redfin renames or drops a column we depend on. 
    needed = ["REGION ID", "FREQUENCY", "PERIOD BEGIN", *METRICS]
    missing = [col for col in needed if col not in lf.collect_schema().names()]
    if missing:
        raise RuntimeError(f"redfin: columns missing from source file: {missing}")

    return (
        lf
        # Compare as text, so we never cast 4.5 million other cities' ID (one abd row elsewhere can't fail us).
        .filter(pl.col("REGION ID").is_in([str(i) for i in CITIES]))
        .select(needed)
        .with_columns(pl.col("REGION ID").cast(pl.Int64))
        # Streaming engine: reads the file in batches, so meory holds our ~2,400 rows, not 1.1 GB. 
        .collect(engine="streaming")
    )

def validate(wide: pl.DataFrame) -> None: 
    # Every city must be present. An absent city is a failure, not a smaller sucess. 
    found = set(wide["REGION ID"].unique().to_list())
    absent = [name for rid, name in CITIES.items() if rid not in found]
    if absent:
        raise RuntimeError(f"redfin: cities missing from source file: {absent}")

    other = wide.filter(pl.col("FREQUENCY") != EXPECTED_FREQUENCY)["FREQUENCY"].unique().to_list()
    if other:
        raise RuntimeError(f"redfin: undexpected FREQUENCY values {other}; period_type would be wrong")

def to_facts(wide: pl.DataFrame, pulled_at: datetime, as_of: date) -> pl.DataFrame:
    """One wide row per city-window -> one long row per city-window-metric"""
    return (
        wide.select(
            pl.col("REGION ID").replace_strict(CITIES).alias("geo"), 
            pl.col("PERIOD BEGIN").str.to_date().alias("period_start"), 
            # strict cast: a non-numeric value fails the job instead of becoming null. 
            *[pl.col(src).cast(pl.Float64).alias(metric) for src, metric in METRICS.items()], 
        )
        .unpivot(index=["geo", "period_start"], variable_name="metric", value_name="value")
        # NA means Redfin had no value for that window (common for small cities). 
        # No row is accurate, a zero would be false. 
        .drop_nulls("value")
        .with_columns(
            pl.lit("city").alias("geo_level"),
            # Overlapping windows: Jun-Aug, then Jul-Sep. Never sum across consecutive rows.
            pl.lit("rolling_3_month").alias("period_type"),
            pl.lit("redfin").alias("source"), 
            pl.lit(pulled_at).alias("pulled_at"),
            pl.lit(as_of).alias("source_as_of")
        )
        .select(schema.COLUMNS)
    )

def run() -> None: 
    curated = config.curated_root()
    raw_root = config.raw_root()

    # One timestampe for the whole run: it identifies this vintage. 
    pulled_at = datetime.now(timezone.utc)
    day = f"{pulled_at:%Y-%m-%d}"

    # The temp dir and the 1.1 GB file inside it are deleted when this block exits, 
    # even if something fails. 
    with tempfile.TemporaryDirectory() as tmp: 
        local = Path(tmp) / "all_cities.csv"
        as_of = download(local)
        # Raw frist, before parsing: the whole file as received, so a parser bug can be replayed. 
        storage.copy_file(local, f"{raw_root}/redfin/{day}/all_cities.csv")
        wide = read_cities(local)

    validate(wide)
    df = to_facts(wide, pulled_at, as_of)

    for name, count in df.group_by("geo").len().sort("geo").iter_rows():
        log.info("redfin: %s, %d rows", name, count)

    # One file per pull date, same as fred: a same-day rerun overwrites it. 
    path = f"{curated}/redfin/{day}.parquet"
    df.write_parquet(path, mkdir=True)
    log.info("redfin: wrote %d rows to %s", df.height, path)
