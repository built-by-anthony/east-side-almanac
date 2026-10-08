"""FRED job: seven national macro series -> long fact table -> one parquet file per pull date."""
import logging
import json
from datetime import date, datetime, timezone 

import polars as pl 
import requests 

from app import config, storage, schema, quality


log = logging.getLogger(__name__)

FRED_KEY_VAR = "FRED_API_KEY"
API_URL = "https://api.stlouisfed.org/fred/series/observations"

# FRED series id -> (our metric name, period_type)
# Target names must exist in app.schema.METRICS
SERIES = {
    "DGS10"        : ("treasury_10y_yield", "day"),
    "DGS2"         : ("treasury_2y_yield", "day"),
    "MORTGAGE30US" : ("mortgage_30y_fixed_rate", "week"),
    "MORTGAGE15US" : ("mortgage_15y_fixed_rate", "week"),
    "DFF"          : ("fed_funds_effective_rate", "day"),
    "CPIAUCSL"     : ("cpi_all_items_sa", "month"),
    "UNRATE"       : ("unemployment_rate", "month"),
}

schema.require_known((m for m, _ in SERIES.values()), "fred")

# Each pull re-reads this many years of that FRED's revisions (CPI seasonal factors
# reach back ~5 years) appear as new vintages. Full history comes from a Phase 7 backfill
LOOKBACK_YEARS = 5

def fetch(session: requests.Session, series_id: str, api_key: str, start: date) -> bytes:
    params = {
        "series_id" : series_id, 
        "api_key"  : api_key, 
        "file_type" : "json", 
        "observation_start" : start.isoformat(), 
    }

    try: 
        resp = session.get(API_URL, params=params, timeout=30)
    except requests.RequestException as e:
        # requests puts the full URL, including ?api_key=..., in its exception messages.
        # Re-raise with only the series and error type `from None` drops the original 
        # exception from the traceback so they key never reaches CloudWatch.
        raise RuntimeError(f"FRED {series_id}: request failed ({type(e).__name__})") from None
    if resp.status_code != 200:
        # Not raise_for_status() for the same teason: its message includes the URL. 
        raise RuntimeError(f"FRED {series_id}: HTTP {resp.status_code}")
    return resp.content

def parse(series_id: str, body: bytes) -> list[dict]:
    """Bytes -> FRED's list of {date, value} observations. Fails loudly on anything unexpected."""
    payload = json.loads(body)
    if "observations" not in payload: 
        raise RuntimeError(f"FRED {series_id}: unexpected resposne: {payload.get('error_message', 'no observations')}")
    return payload["observations"]

def run() -> None: 
    curated = config.curated_root()
    api_key = config.require(
        FRED_KEY_VAR, 
        "Locally: export it from SSM and pass -e FRED_API_KEY. In AWS: task definition `secrets`.",
    )

    # One timestampe for the whole run, never per row: it identifies this vintage
    pulled_at = datetime.now(timezone.utc)
    start = date(pulled_at.year - LOOKBACK_YEARS, 1, 1)
    raw_dir = f"{config.raw_root()}/fred/{pulled_at:%Y-%m-%d}"

    rows = []
    with requests.Session() as session: # reuses one TLS connection for all seven calls 
        for series_id, (metric, period_type) in SERIES.items():
            body = fetch(session, series_id, api_key, start)

            # Save the source bytes BEFORE parsing: if parse() fails, teh exact
            # response that broke it is already on disk to debug from
            storage.write_bytes(f"{raw_dir}/{series_id}.json", body)

            observations = parse(series_id, body)

            values = []
            for obs in observations: 
                # FRED marks a missing observation (e.g. a bond-market holiday) with a ".".
                if obs["value"] == ".":
                    continue
                # Anything else non-numeric makes float() raise and fail the job loudly. 
                values.append((obs["date"], float(obs["value"])))

            # A series that returns nothing is a failure, not a quiet success 
            if not values: 
                raise RuntimeError(f"FRED {series_id}: no observations since {start}")

            log.info("fred: %s -> %s, %d rows", series_id, metric, len(values))

            # One fact-table row per (date, value) pari. 
            for obs_date, value in values: 
                rows.append({
                    "metric"      : metric, 
                    "period_start": obs_date, 
                    "period_type" : period_type, 
                    "value"       : value, 
                })

    df = (
        pl.DataFrame(rows)
        .with_columns(
            pl.col("period_start").str.to_date(), # "2026-10-06" -> Date
            pl.lit("US").alias("geo"), 
            pl.lit("national").alias("geo_level"),
            pl.lit("fred").alias("source"),
            pl.lit(pulled_at).alias("pulled_at"), # timezone aware datetime -> Datetime(UTC)
            # No per-pull publication date: the response's realtime_start is the query's
            # real-time period, not when each value was published. True vintages need ALFRED.
            pl.lit(None, dtype=pl.Date).alias("source_as_of"),
        )
        .select(schema.COLUMNS)
    )

    # One file per pull date: a same-day rerun overwrites it, so a day never gets two vintages. 
    path = f"{curated}/fred/{pulled_at:%Y-%m-%d}.parquet"
    quality.validate(df, "fred", expected_geos={"US"}, expected_metrics={m for m, _ in SERIES.values()})
    df.write_parquet(path, mkdir=True)
    log.info("fred: wrote %d rows to %s (raw in %s)", df.height, path, raw_dir)