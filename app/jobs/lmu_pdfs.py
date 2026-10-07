import logging 
from app import config

log = logging.getLogger(__name__)

def run() -> None: 
    # Each job checks only what it needs. redfin must not fail because FRED_API_KEY is unset. 
    curated = config.curated_root()
    log.info("lmu_pdf would write to %s (not implemented yet)", curated)