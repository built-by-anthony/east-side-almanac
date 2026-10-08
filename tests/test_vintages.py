"""Rule 3: one vintage per source per pull date. Same-day reruns replace; a new day appends."""
from datetime import date, datetime, timezone
from pathlib import Path

import polars as pl 
import pytest

from app.jobs import lmu_pdfs

FIXTURES = Path(__file__).parent / "fixtures" / "lmu"
GRAIN = ["geo", "geo_level", "metric", "period_start", "period_type", "source"]

DAY1 = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
DAY1_LATER = datetime(2026, 10, 8, 17, 0, tzinfo=timezone.utc)
DAY2 = datetime(2026, 10, 9, 15, 9, tzinfo=timezone.utc)

def fixture_fetch(session, month: date, city: str) -> bytes: 
    """Stand-in for lmu_pdfs.fetch: same signature, reads the saved PDF instead of the network"""
    return (FIXTURES / f"{month:%Y-%m}" / f"{city}.pdf").read_bytes()

@pytest.fixture
def offline_lmu(monkeypatch, tmp_path): 
    """Run the real job against fixture PDFs, writing into a temp dir. No network."""
    if not (FIXTURES / "2026-08").is_dir():
        pytest.fail("LMU fixtures missing: run tests/fetch_lmu_fixtures.sh")
    monkeypatch.setenv("ALMANAC_OUTPUT_ROOT", str(tmp_path))
    monkeypatch.setenv("LMU_REPORT_MONTH", "2026-08")
    monkeypatch.setattr(lmu_pdfs, "fetch", fixture_fetch)
    return tmp_path 

def read_curated(root: Path) -> tuple[list[Path], pl.DataFrame]: 
    files = sorted((root / "curated" / "lmu").glob("*.parquet"))
    return files, pl.read_parquet(files)

def test_same_day_rerun_keeps_one_vintage(offline_lmu):
    lmu_pdfs.run(now=DAY1)
    lmu_pdfs.run(now=DAY1_LATER)

    files, df = read_curated(offline_lmu)
    assert len(files) == 1
    assert df.height == 224

    # Last write of the d ay wins: the file records the latest look, not the first. 
    assert df["pulled_at"].unique().to_list() == [DAY1_LATER]


def test_next_day_appends_a_vintage(offline_lmu):
    lmu_pdfs.run(now=DAY1) 
    lmu_pdfs.run(now=DAY2)

    files, df = read_curated(offline_lmu)
    assert len(files) == 2
    assert df["pulled_at"].n_unique() == 2
    assert df.height == 448

    # Same report pulled twice: two vintages, one publication. This is what source_as_of is for. 
    assert df["source_as_of"].unique().to_list() == [date(2026, 9, 8)]

    # A latest-vintage read returns exactly one row per grain key
    latest = df.filter(pl.col("pulled_at") == pl.col("pulled_at").max().over(GRAIN))
    assert latest.height == 224
    assert latest.select(GRAIN).is_duplicated().sum() == 0