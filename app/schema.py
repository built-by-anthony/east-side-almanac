"""The asset's vocabulary: what the fact table can contain. Source-agnostic.

Each job maps its own source labels ont these names and calles require_known(),
so a type of an unregistered metric fails at import, before any I/O.

Names are permanent once they reach S3: remaining splits history. Add, never rename.
name rule statistic first, unit last ("median_sale_price_per_sqft", "avg_sale_to_list_pct").
"""
from dataclasses import dataclass
from typing import Iterable, Literal, get_args

# The fact table, in column order. Grain: every column except val ues and source_as_of
# source_as_of is an attribute of the vintage (when the source published it), not part of the key.
# Null when the source gives no per-pull publication date (FRED: see data dictionary).
COLUMNS = ["geo", "geo_level", "metric", "period_start", "period_type", "value", "source", "pulled_at", "source_as_of"]
GRAIN = ["geo", "geo_level", "metric", "period_start", "period_type", "source"]

CITIES = ("Woodbury", "Lake Elmo", "Oakdale", "Maplewood", "Stillwater", "Cottage Grove", "North St. Paul")
GEO_LEVELS = ("city", "national")
SOURCES = ("fred", "redfin", "northstar_lmu")

# Rolling windows overlap: never sum across consecutive rows.  
PERIOD_TYPES = ("day", "week", "month", "rolling_3_month", "rolling_12_month")
Unit = Literal["usd", "usd_per_sqft", "count", "pct", "days", "months", "index"]

# What kind of number it is. Only "count" can be summed across preiods; the rest can't. 
# "unverified": the source doesn't say; resolve before relying on it in comparisons. 
Stat = Literal["count", "median", "mean", "share", "ratio", "rate", "index", "unverified"]


@dataclass(frozen=True)
class Metric:
    name       : str
    unit       : Unit 
    stat       : Stat
    description: str
    cross_source_comparable: bool = True

    @property
    def summable(self) -> bool: 
        return self.stat == "count"
    
    def __post_init__(self) -> None:
        # Literal is only checked by type checkers; enforce it at import too.
        if self.unit not in get_args(Unit):
            raise ValueError(f"{self.name}: unknown unit {self.unit!r}")
        if self.stat not in get_args(Stat):
            raise ValueError(f"{self.name}: unknown stat {self.stat!r}")

METRICS: dict[str, Metric] = {m.name: m for m in [
    # FRED (national)
    Metric("treasury_10y_yield", "pct", "rate", "10-year Treasury constant maturity yield (DGS10)."),
    Metric("treasury_2y_yield", "pct", "rate", "2-year Treasury constant maturity yield (DGS2)."),
    Metric("mortgage_30y_fixed_rate", "pct", "rate", "Freddie Mac 30-year fixed average (MORTGAGE30US). Weekly, dated Thursday."),
    Metric("mortgage_15y_fixed_rate", "pct", "rate", "Freddie Mac 15-year fixed average (MORTGAGE15US). Weekly, dated Thursday."),
    Metric("fed_funds_effective_rate", "pct", "rate", "Effective federal funds rate (DFF). Daily, includes weekends."),
    Metric("cpi_all_items_sa", "index", "index", "CPI-U all items, seasonally adjusted, 1982-84=100 (CPIAUCSL)."),
    Metric("unemployment_rate", "pct", "share", "Civilian unemployment rate, seasonally adjusted (UNRATE)."),

    # Shared by redfin and northstar_lmu (same concept; window differs by period_type)
    Metric("homes_sold", "count", "count", "Closed sales in the period."),
    Metric("new_listings", "count", "count",
           "Listings that came on market in the period. NOT comparable across sources: LMU runs "
           "+7% to +31% above Redfin in every city checked, while homes_sold and inventory agree "
           "(reconcile, 2026-10-08). Cause unverified; see docs/reconciliation.md.",
           cross_source_comparable=False),
    Metric("inventory", "count", "count", "Homes for sale at the end of the period."),
    Metric("median_sale_price", "usd", "median", "Median closed sale price."),

    # Redfin only
    Metric("active_listings", "count", "count", "Listings active at any point during the period (not inventory)."),
    Metric("pending_sales", "count", "count", "Listings that went pending in the period."),
    Metric("median_days_on_market", "days", "median",
           "Redfin: median days from listing to under contract, for homes that went under contract in the period."),    Metric("avg_sale_to_list_pct", "pct", "mean", "Average sale price / final list price. 95.45 means 95.45%."),
    Metric("share_sold_above_list_pct", "pct", "share", "Share of sales above original list price."),
    Metric("off_market_in_two_weeks_pct", "pct", "share", "Share of listings off market within two weeks."),
    Metric("median_new_listing_price", "usd", "median", "Median list price of new listings."),
    Metric("median_new_listing_price_per_sqft", "usd_per_sqft", "median", "Median list $/sqft of new listings."),
    Metric("median_sale_price_per_sqft", "usd_per_sqft", "median", "Median sale $/sqft."),
    Metric("months_of_supply_closed_pace", "months", "ratio",
        "Redfin: ≈ end-of-period inventory / (3-month closed sales ÷ 3). Exact formula undocumented; "
        "recomputing from inventory and homes_sold differs by up to ~0.1. Use the published value."),

    # NorthstarMLS LMU only. Definitions from MAAR Monthly Indicators (10K Research, Aug 2026).
    Metric("avg_sale_price", "usd", "mean", "Average closed sale price."),
    Metric("sale_price_per_sqft", "usd_per_sqft", "unverified",
           "10K Research: 'price per square foot of homes sold'; median vs mean not stated."),
    Metric("avg_sale_to_original_list_pct", "pct", "mean",
           "Average of sale price / ORIGINAL list price (10K Research). Redfin's avg_sale_to_list_pct uses final list."),
    Metric("avg_cumulative_days_on_market", "days", "mean",
           "Average cumulative days from listing to offer accepted (10K Research). Not comparable to Redfin's median."),
    Metric("months_of_supply_pending_12m", "months", "ratio",
           "10K Research: end-of-month inventory / avg monthly pending sales, trailing 12 months."),
]}


def require_known(names: Iterable[str], where: str) -> None: 
    """Fail fast if a job maps onto a metric the vocabulary doesn't define."""
    unknown = sorted(set(names) - METRICS.keys())
    if unknown:
        raise RuntimeError(f"{where}: metrics not in app.schema.METRICS: {unknown}")
    