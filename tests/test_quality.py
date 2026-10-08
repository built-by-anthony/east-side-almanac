"""Each quality rule must fire on exactly the problem it exists for, with a useful message."""
from datetime import date, datetime, timezone

import polars as pl 
import pytest

from app import schema
from app.quality import EXPECTED_DTYPES, QualityError, validate

PULLED = datetime(2026, 10, 8, 0, tzinfo=timezone.utc)
GEOS = {"Oakdale", "Woodbury"}
METRICS = {"homes_sold", "median_sale_price"}
VALUES = {
    "homes_sold" : 104.0,
    "median_sale_price" : 499_500.0
}

def valid_frame() -> pl.DataFrame: 
    """2 cities x 2 metrics x 1 month: the smallest frame that passes every check."""
    rows = [
        {
            "geo": geo, 
            "geo_level": "city",
            "metric": metric,
            "period_start": date(2026, 8, 1), 
            "period_type": "month",
            "value": VALUES[metric], 
            "source": "northstar_lmu",
            "pulled_at": PULLED, 
            "source_as_of": date(2026, 9, 8),
        }
        for geo in sorted(GEOS)
        for metric in sorted(METRICS)
    ]

    # Explicit schema: the test controls the dtypes instead of trusting inference. 
    return pl.DataFrame(rows, schema = EXPECTED_DTYPES).select(schema.COLUMNS)
    
def run(df: pl.DataFrame) -> None: 
    validate(df, "northstar_lmu", expected_geos=GEOS, expected_metrics=METRICS)

def set_where(df: pl.DataFrame, condition: pl.Expr, column: str, value) -> pl.DataFrame: 
    """Overwrite one column on the rows matching condition; every other row untouched."""
    return df.with_columns(
        pl.when(condition).then(pl.lit(value)).otherwise(pl.col(column)).alias(column)
    )

OAKDALE_PRICE = (pl.col("geo") == "Oakdale") & (pl.col("metric") == "median_sale_price") 
OAKDALE_SALES = (pl.col("geo") == "Oakdale") & (pl.col("metric") == "homes_sold")

def test_valid_frame_passes(): 
    run(valid_frame())

def test_null_source_as_of_is_allowed():
    run(valid_frame().with_columns(pl.lit(None, dtype = pl.Date).alias("source_as_of")))

def drop_column(df):        return df.drop("source_as_of")
def int_values(df):         return df.with_columns(pl.col("value").cast(pl.Int64))
def no_rows(df):            return df.head(0)
def misspell_metric(df):    return set_where(df, OAKDALE_SALES, "metric", "homes_soldd")
def wrong_source(df):       return df.with_columns(pl.lit("redfin").alias("source"))
def null_price(df):         return set_where(df, OAKDALE_PRICE, "value", None)
def nan_price(df):          return set_where(df, OAKDALE_PRICE, "value", float("nan"))
def duplicate_row(df):      return pl.concat([df, df.head(1)])
def drop_oakdale(df):       return df.filter(pl.col("geo") != "Oakdale")
def drop_oakdale_price(df): return df.filter(~OAKDALE_PRICE)
def negative_price(df):     return set_where(df, OAKDALE_PRICE, "value", -1.0)
def fractional_count(df):   return set_where(df, OAKDALE_SALES, "value", 104.5)


BROKEN = [
    pytest.param(drop_column,        r"columns \[",                                                id="missing-column"),
    pytest.param(int_values,         r"column 'value' is Int64",                                   id="wrong-dtype"),
    pytest.param(no_rows,            r"no rows",                                                   id="empty"),
    pytest.param(misspell_metric,    r"metric has values outside the vocabulary: \['homes_soldd'\]", id="unknown-metric"),
    pytest.param(wrong_source,       r"source has values outside the vocabulary",                  id="wrong-source"),
    pytest.param(null_price,         r"value has 1 nulls",                                         id="null-value"),
    pytest.param(nan_price,          r"value has 1 NaN",                                           id="nan-value"),
    pytest.param(duplicate_row,      r"2 rows share a grain key",                                  id="duplicate-grain"),
    pytest.param(drop_oakdale,       r"geos missing from pull: \['Oakdale'\]",                     id="missing-geo"),
    pytest.param(drop_oakdale_price, r"Oakdale: metrics missing: \['median_sale_price'\]",         id="missing-metric"),
    pytest.param(negative_price,     r"1 impossible usd values",                                   id="negative-price"),
    pytest.param(fractional_count,   r"1 impossible count values",                                 id="fractional-count"),
]

@pytest.mark.parametrize("break_it, message", BROKEN)
def test_each_rule_fires(break_it, message):
    with pytest.raises(QualityError, match=message):
        run(break_it(valid_frame()))

def test_failures_are_collected_not_first_only():
    df = set_where(pl.concat([valid_frame(), valid_frame().head(1)]), OAKDALE_PRICE, "value", -1.0)
    with pytest.raises(QualityError, match=r"2 quality failure\(s\)"):
        run(df)