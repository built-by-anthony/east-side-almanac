"""
Cross-source reconciliation: Redfin vs NorthstarMLS LMU, on metrics both define the same way. 

Reads curated/ only and writes nothing. A disagreement doesn't make either source wrong; 
both stored what they published. So this never blocks or deletes: it exits non-zero
(disagreement over THRESHOLD_PCT, or nothing comparable) so Phrase 4 alerting sees it.
"""
import logging 

import polars as pl 

from app import reader, schema 

log = logging.getLogger(__name__)

# Provisional: max observed |gap| on 2026-10-08 was 9.1% (Cottage Grove inventory, 40 pairs).
# Revisit once monthly runs add history.
THRESHOLD_PCT = 12.0

# Comparable only where sources agree on BOTH the definition and the city boundary.
# Stillwater, North St. Paul, Lake Elmo: boundary/sample differences, see docs/reconciliation.md.
COMPARABLE_GEOS = ("Cottage Grove", "Maplewood", "Oakdale", "Woodbury")

# Redfin's rolling-3-month value is a 3-month TOTAL (confirmed 2026-10-08: whole numbers,
# and months_of_supply ~ inventory / (homes_sold / 3)), so compare to the sum of LMU's 3 months.
# new_listings is excluded: cross_source_comparable=False in app.schema.
SUMMED = ("homes_sold",)

# End-of-period levels: Redfin's window ends the same day as LMU's third month. Compare directly
END_OF_PERIOD = ("inventory",)

for name in SUMMED + END_OF_PERIOD:
    if not schema.METRICS[name].cross_source_comparable:
        raise RuntimeError(f"reconcile: {name} is marked not comparable across sources")
for name in SUMMED:
    if not schema.METRICS[name].summable:
        raise RuntimeError(f"reconcile: {name} is in SUMMED but its stat isn't 'count'")

KEY = ["geo", "metric", "window_start"]

class ReconcileError(RuntimeError):
    """Sources disagree, or nothing was comparable."""

def lmu_as_windows(lmu: pl.DataFrame) -> pl.DataFrame:
    monthly = lmu.filter(pl.col("period_type") == "month")

    # Month m belongs to the windows starting m, m-1, and m-2. Fan out, then sum per window, 
    # keeping only windows where all three months are present. 
    summed = (
        monthly.filter(pl.col("metric").is_in(SUMMED))
        .with_columns(
            pl.concat_list([pl.col("period_start").dt.offset_by(f"-{k}mo") for k in range(3)])
            .alias("window_start")
        )
        .explode("window_start")
        .group_by(KEY)
        .agg(pl.col("value").sum(), pl.len().alias("months"))
        .filter(pl.col("months") == 3)
        .select(*KEY, "value")
    )

    # Month m's end-of-month inventory = the window starting m-2's end-of-window inventory. 
    level = (
        monthly.filter(pl.col("metric").is_in(END_OF_PERIOD))
        .select("geo", "metric", pl.col("period_start").dt.offset_by("-2mo").alias("window_start"), "value")
    )
    return pl.concat([summed, level])

def compare(redfin: pl.DataFrame, lmu: pl.DataFrame) -> pl.DataFrame: 
    """Pure: latest-vintage frames in, one row per comparable (geo, metric, window) out."""
    r = (
        redfin.filter(pl.col("metric").is_in(SUMMED + END_OF_PERIOD))
        .filter(pl.col("geo").is_in(COMPARABLE_GEOS))
        .select("geo", "metric", pl.col("period_start").alias("window_start"), pl.col("value").alias("redfin"))
    )
    l = lmu_as_windows(lmu).rename({"value": "lmu"})
    return (
        r.join(l, on=KEY, how="inner")
        .with_columns(((pl.col("lmu") - pl.col("redfin")) / pl.col("redfin") * 100).round(1).alias("diff_pct"))
        .sort("metric", "geo", "window_start")
    )

def run() -> None:
    pairs = compare(reader.latest(reader.load("redfin")), reader.latest(reader.load("northstar_lmu")))
    if pairs.height == 0:
        raise ReconcileError("no comparable Redfin/LMU pairs: a job stopped, a metric was renamed, or periods shifted")
    bad = pairs.filter(pl.col("diff_pct").abs() > THRESHOLD_PCT)
    log.info("reconcile: %d pairs compared, %d over %.0f%%", pairs.height, bad.height, THRESHOLD_PCT)
    for row in bad.iter_rows(named=True):
        log.warning(
            "reconcile: %s %s window %s: redfin %.0f, lmu %.0f (%+.1f%%)",
            row["geo"], row["metric"], row["window_start"], row["redfin"], row["lmu"], row["diff_pct"],
        )
    if bad.height:
        raise ReconcileError(f"{bad.height} of {pairs.height} pairs disagree by more than {THRESHOLD_PCT}%")