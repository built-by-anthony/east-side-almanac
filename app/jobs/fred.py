import logging

from app import config

log = logging.getLogger(__name__)

FRED_KEY_VAR = "FRED_API_KEY"

def run() -> None: 
    # Read config when the job runs, not at import time, so tests can set env per test.
    curated = config.curated_root()

    # Injected by the ECS task definition's `secrets` block in AWS (so the task role
    # needs no SSM permission). Locally, your shell fetches it from SSM and psses -e FRED_KEY_API.
    api_key = config.require(
        FRED_KEY_VAR,
        "Locally: export it from SSM and pass -e FRED_API_KEY. In AWS: task definition `secrets`." 
    )

    # Never log api_key, not even a prefix. 
    log.info("fred: would write to %s (not implemented yet)", curated)