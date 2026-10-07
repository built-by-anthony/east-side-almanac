"""
Runtime configuration. Environment variables only: no files, no flags. 

The same image runs locally and on Fargate, and ECS can only configure a 
container through environment variables, secrets, and the command.
"""
import os
from datetime import date, datetime

OUTPUT_ROOT_VAR = "ALMANAC_OUTPUT_ROOT"

class ConfigError(RuntimeError): 
    """A required environment variable is missing. cli.main() turns this into exit 1."""

def require(name: str, hint: str) -> str:
    # Missing and empty are treated the same: an ECS task definition with 
    # value "" is just as broken as one without the variable.
    value = os.environ.get(name, "").strip()
    if not value: 
        raise ConfigError(f"{name} is not set. {hint}")
    return value 

def output_root() -> str: 
    # No default on purpose: a silent fallback to /data would let a misconfigured
    # Fargate task write to its own temporary disk, exit 0, and lose the data.
    root = require(OUTPUT_ROOT_VAR, "Use /data locally or s3://<bucket> in AWS.")
    # Strip a trailing slash to "s3://bucket/ doesn't produce "s3://bucket//raw".
    return root.rstrip("/")

def lmu_report_month() -> date | None:
    # Unset: the job asks for last month (the scheduled case). Set: a specific
    # report month, for reruns and backfill. Bad input fails fast, never guesses.
    value = os.environ.get("LMU_REPORT_MONTH", "").strip()
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m").date()
    except ValueError:
        raise ConfigError(f"LMU_REPORT_MONTH={value!r} is not YYYY-MM.") from None

# raw/ and curated/ are fixed parts of the asset's layout, not configuration.
# f-strings, not os.path.join: these must work for both /data and s3:// roots.
def raw_root() -> str:
    return f"{output_root()}/raw"

def curated_root() -> str: 
    return f"{output_root()}/curated"