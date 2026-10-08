"""How to read the asset. The latest-vintage rule lives here so every reader applies it the same way."""
import polars as pl 

from app import config, schema 

def load(source: str) -> pl.DataFrame:
    """Every vintage of one source, from local or s3:// curated storage."""
    return pl.read_parquet(f"{config.curated_root()}/{source}/*.parquet")

def latest(df: pl.DataFrame) -> pl.DataFrame: 
    """One row per grain key: the newest vintage.
    
   Ordered by pulled_at, then source_as_of: a same-day backfill of report months M and 
   M+12 yields two rows for month M with the same pulled_at, and only the source's
   publication date says which one is the revision. Null source_as_of sorts first.
    """
    return (
        df.sort("pulled_at", "source_as_of", nulls_last=False)
        .unique(subset=schema.GRAIN, keep="last", maintain_order=True)
    )