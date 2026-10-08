"""Quality gate for a pull: runs on the finished fact tablem just before the curate write. 

Every check returns a list of problems instead of raising, so one failed run reports 
everything wrong at once. validate() raises QualityError if anything failed; the job 
exits non-zero and the curate file is never written. Raw is already saved for replay.
"""

import polars as pl 

from app import schema

class QualityError(RuntimeError): 
    """The pull failed validation. Nothing was written to curated/."""

EXPECTED_DTYPES: dict[str, pl.DataType] = {
    "geo": pl.String(),
    "geo_level": pl.String(),
    "metric": pl.String(),
    "period_start": pl.Date(),
    "period_type": pl.String(),
    "value": pl.Float64(),
    "source": pl.String(),
    "pulled_at": pl.Datetime("us", "UTC"),
    "source_as_of": pl.Date(),
}

# Only source_as_of may be null (FRED has no publication date per pull). 
NULLABLE = {"source_as_of"}

# unit -> expression that is True for an IMPOSSIBLE value. Loose on purpose: these each 
# sign errors and garbage, not scale mistakes (0.95 vs 95 needs per-metrics bounds). 
RULES: dict[str, pl.Expr] = {
    "count": (pl.col("value") < 0) | (pl.col("value") % 1 != 0),
    "usd": pl.col("value") <= 0,
    "usd_per_sqft": pl.col("value") <= 0,
    "days": pl.col("value") < 0,
    "months": pl.col("value") < 0,
    "pct": ~pl.col("value").is_between(-10, 200),
    "index": pl.col("value") <= 0,
}

EXAMPLE_COLS = ["geo", "metric", "period_start", "period_type", "value"]

def examples(bad: pl.DataFrame, n: int = 3) -> str: 
    """A few offending rows, one line, so the error is debuggable without opening the data"""
    rows = bad.select([c for c in EXAMPLE_COLS if c in bad.columns]).head(n).iter_rows()
    return "; ".join(", ".join(str(v) for v in row) for row in rows)

def check_schema(df: pl.DataFrame) -> list[str]:
    errors = []
    if df.columns != schema.COLUMNS:
        errors.append(f"columns {df.columns} != expected {schema.COLUMNS}")
    for col, expected in EXPECTED_DTYPES.items():
        actual = df.schema.get(col)
        if actual is not None and actual != expected: 
            errors.append(f"column {col!r} is {actual}, expected {expected}")
    if df.height == 0:
        errors.append("no rows")
    return errors 

def check_vocabulary(df: pl.DataFrame, source: str) -> list[str]:
    errors = []
    allowed = {
        "metric": set(schema.METRICS),
        "period_type": set(schema.PERIOD_TYPES),
        "geo_level": set(schema.GEO_LEVELS),
        "source": {source},
    }
    for col, ok in allowed.items():
        unknown = set(df[col].unique().drop_nulls().to_list()) - ok
        if unknown: 
            errors.append(f"{col} has values outside the vocabulary: {sorted(unknown)}")
    return errors

def check_nulls(df: pl.DataFrame) -> list[str]: 
    errors = []
    for col in schema.COLUMNS:
        if col in NULLABLE:
            continue 
        n = df[col].null_count()
        if n:
            errors.append(f"{col} has {n} nulls")

    # NaN is not null in polars: a float column can be "complete" and still hold garbage. 
    nans = df.filter(pl.col("value").is_nan())
    if nans.height:
        errors.append(f"value has {nans.height} NaN: {examples(nans)}")
    return errors

def check_grain(df: pl.DataFrame) -> list[str]:
    dupes = df.filter(pl.struct(schema.GRAIN).is_duplicated())
    if dupes.height:
        return [f"{dupes.height} rows share a grain key (duplicate observations): {examples(dupes)}"]
    return []

def check_completeness(df: pl.DataFrame, expected_goes: set[str], expected_metrics: set[str]) -> list[str]:
    errors = []
    present_geos = set(df["geo"].unique().to_list())

    missing_geos = expected_goes - present_geos
    if missing_geos: 
        errors.append(f"geos missing from pull: {sorted(missing_geos)}")

    extra_geos = present_geos - expected_goes
    if extra_geos:
        errors.append(f"unexpected geos in pull: {sorted(extra_geos)}")

    metrics_by_geo = df.group_by("geo").agg(pl.col("metric").unique()).sort("geo")
    for geo, metrics in metrics_by_geo.iter_rows():
        present_metrics = set(metrics)

        missing_metrics = expected_metrics - present_metrics
        if missing_metrics: 
            errors.append(f"{geo}: metrics missing: {sorted(missing_metrics)}")

        extra_metrics = present_metrics - expected_metrics
        if extra_metrics:
            errors.append(f"{geo}: metrics this source shouldn't produce: {sorted(extra_metrics)}")

    return errors

def check_values(df: pl.DataFrame) -> list[str]:
    errors = []
    units = {m.name : m.unit for m in schema.METRICS.values()}

    # Safe after check_vocabulary: every metric is known, so replace_strict can't miss. 
    with_unit = df.with_columns(pl.col("metric").replace_strict(units).alias("unit"))
    for unit, is_bad in RULES.items():
        bad = with_unit.filter((pl.col("unit") == unit) & is_bad)
        if bad.height:
            errors.append(f"{bad.height} impossible {unit} values: {examples(bad)}")
    return errors

def validate(df: pl.DataFrame, source: str, *, expected_geos: set[str], expected_metrics: set[str]) -> None:
    # Schema first and alone: with a missing column or wrong dtypes, every later check 
    # would fail for the wrong reason and bury the real one.
    errors = check_schema(df)
    if not errors: 
        errors += check_vocabulary(df, source)

    # Values need a clean vocabulary (replace_strict); skip them if vocabulary failed.
    if not errors: 
        errors += check_nulls(df)
        errors += check_grain(df)
        errors += check_completeness(df, expected_geos, expected_metrics)
        errors += check_values(df)
    if errors: 
        raise QualityError(f"{source}: {len(errors)} quality failure(s):\n " + "\n ".join(errors))