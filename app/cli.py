import argparse
import importlib
import logging

from app.config import ConfigError

JOBS = {
    "fred"    : "app.jobs.fred", 
    "redfin"  : "app.jobs.redfin", 
    "lmu-pdfs": "app.jobs.lmu_pdfs",
}

log = logging.getLogger(__name__)

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="almanac", description="East Side Almanac ingestion jobs") 

    # One subcommand per job. The chosen name lands in args.job
    sub = parser.add_subparsers(dest="job", required=True)
    for name in JOBS: 
        sub.add_parser(name, help=f"run the {name} ingestion job.")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    log.info("starting job=%s", args.job)
    try:
        # Import only the job being run, so fred nevenr loads pdfplumber.
        importlib.import_module(JOBS[args.job]).run()
    except ConfigError as e: 
        # Config errors are expected operator mistakes: one clear line, exit 1. 
        # Anything else still raises with a full traceback (also exit 1). 
        log.error("%s", e)
        return 1
    log.info("finished job=%s", args.job)
    return 0

