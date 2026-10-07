# Progress — east-side-almanac

**Current phase:** 1 — Local pipelines in Docker
**Current step:** 1.7 — clean-clone check, then Phase 2
**Last worked:** 2026-10-07

## Done

### Phase 0 — AWS guardrails

- 0.1 Budget: `account-budget`, $5/month. Alerts: ACTUAL 80/100%, FORECASTED 80/100%,
  emailed directly with no SNS.
- 0.2 Cost Anomaly Detection: kept the auto-created `Default-Services-Monitor` and
  `Default-Services-Subscription`. Threshold changed from ($100 AND 40%) to an absolute $1
  (impact % is undefined when expected spend is ~$0). Daily email summary.
- 0.3 Region: us-east-1.
- 0.4 Project role: `east-side-almanac-operator`, assumed via the `almanac` CLI profile with MFA.
  `anthony-admin` was removed from the `admin` group and can now only `sts:AssumeRole` this role.
  Access key rotated.
- 0.5 FRED key: `/east-side-almanac/fred/api_key`, SecureString, Standard tier, `alias/aws/ssm`.
- 0.6 Repo skeleton: `app/`, `infra/`, `tests/`, `docs/`, `.gitignore`.

### Phase 1 — Local pipelines in Docker

- 1.1 Multi-stage Dockerfile. Builder: `python:3.12-slim` + uv 0.12.23,
  `uv sync --locked --no-install-project` with a cache mount and bind mounts
  (dependency layer keyed only on the lockfile). Runtime: same base via shared `ARG BASE`,
  copies only `/app/.venv` and `app/`. Runs as UID 10001 `almanac`; `/app` is root-owned and
  read-only; `/data` is the only writable path. `.dockerignore` excludes `.venv`, `.git`,
  `data`, `infra`, `**/__pycache__`. Image: 138 MB compressed / 586 MB on disk.
- 1.2 Base image pinned by multi-arch index digest. polars 2.0 uses the default
  `polars-runtime-32`; no rt64/compat needed.
- 1.3 CLI: `python -m app {fred,redfin,lmu-pdfs}`, argparse subcommands, lazy job imports.
  `ENTRYPOINT ["python", "-m", "app"]`, `CMD ["--help"]`.
- 1.4 Config from env only: `ALMANAC_OUTPUT_ROOT` (required, no default), `FRED_API_KEY`
  (fred only). `ConfigError` → one log line, exit 1.
- 1.5 `docker-compose.yml`: `docker compose run --rm --build app <job>`, `./data` → `/data`.
  Docker Desktop translates bind-mount ownership; Linux/CI won't.
- 1.6a fred: 7 series, 5-year lookback, 5,719 rows per pull, `curated/fred/YYYY-MM-DD.parquet`.
  Same-day rerun overwrites the file (one vintage per pull date). Row counts match calendar math.
- 1.6b fred raw: original JSON per series at `raw/fred/YYYY-MM-DD/<series>.json`, written
  before parsing via `app/storage.write_bytes`. No API key in the response body.
  Raw confirms the parser: DGS10 count 1502 vs 1440 rows = 62 "." holidays.
- 1.6c redfin: 7 cities by Region ID (18242 Woodbury, 8750 Lake Elmo, 12183 Oakdale,
  10305 Maplewood, 16123 Stillwater, 3510 Cottage Grove, 12062 North St. Paul).
  14 level metrics, windows 2012-01 → 2026-06, 17,052 rows per pull, 0 NA.
  Full 1.1 GB raw CSV per pull via `storage.copy_file`.
- 1.6d lmu-pdfs: `maar.stats.10kresearch.com/docs/lmu/{YYYY-MM}/x/{City}`, 7 cities × 32 rows
  (9 metrics × 2 months + 7 × 2 rolling-12). Verified on 14 fixtures (2026-07, 2026-08)
  and a live August run (224 rows).

## In flight

- 1.7 Clean-clone check: fresh clone, all three jobs, second same-day run leaves one file each.

## Blocked / open questions

- Phase 5: existing `tofu-state-805595753711` bucket. Share it under a project key, or give
  this project its own backend?
- Phase 2 data dictionary: CPIAUCSL and UNRATE have no 2025-10 observation (FRED returns ".").
  Real source gap; not filled in.
- Phase 2 data dictionary: Redfin `active_listings` (listed during window) ≠ `inventory`
  (for sale at end of window).
- Phase 2/3: `storage` S3 branches are untested until Phase 3; cover with a fake S3 client.
- Phase 2: Redfin is rolling 3-month, LMU is monthly. Counts can be summed over 3 months to
  compare; medians can't. The planned >5% disagreement check must account for this.
- Phase 2: re-pulling the same LMU report month on a different day creates an identical
  vintage. Dedupe on the PDF's "Current as of" date?
- Phase 7: dated LMU URLs make history fetchable. How far back?

## Decisions

- Scope: data asset. Analytics parked until there's real history.
- Region: us-east-1 (pick one and never move).
- Secrets: SSM Parameter Store SecureString, not Secrets Manager.
- No SQL engine: readers use polars over curated Parquet.
- Revisions: append-only vintages, keyed on pulled_at.
- Access: the IAM user can only assume the operator role. Trust policy names that user and
  requires MFA (`Bool aws:MultiFactorAuthPresent`, not `BoolIfExists`).
- CLI MFA uses `mfa/microsoft-auth`; passkeys (u2f) don't work with the CLI.
- Operator role has AdministratorAccess for now; least privilege comes in Phase 5.
- Python 3.12; uv for dependency management and locking (`uv.lock`, hashes by default).
- Base image: `python:3.12-slim` (glibc, so polars uses prebuilt wheels). Not Alpine.
  Pinned by index digest; bumped deliberately.
- Images build as arm64 (Apple Silicon). Fargate CPU architecture is decided in Phase 3.
- Non-root runtime: fixed UID 10001; code is read-only to the app user.
  Reason: general defense-in-depth (supply chain, any dependency), not one library.
- FRED key read from env, not fetched from SSM by the app: the execution role injects it,
  so the task role needs no SSM permission.
- Config errors use a `ConfigError` class: one clean log line and exit 1;
  other exceptions keep full tracebacks.
- Local runs via `docker compose run`, not `up`: jobs are one-off and exit.
- `period_type`: `day | week | month | rolling_3_month | rolling_12_month`.
  FRED mortgage rates are weekly, dated on Thursdays (FRED's date, not shifted).
  Rolling windows overlap; never sum across consecutive rows.
- FRED pulls re-read a 5-year window so revisions become new vintages;
  full history comes from the Phase 7 backfill.
- FRED API errors are re-raised without the request URL (the key is a query parameter).
- `raw/` = bronze (source bytes as received, written before parsing).
  `curated/` = silver (typed, conformed to the fact table). No gold in this project.
- Don't store derived series (e.g. FRED's T10Y2Y spread); readers compute them from levels.
- One file per source per pull date: `curated/<source>/YYYY-MM-DD.parquet`.
- Redfin source: `redfin_data_center/housing_market/monthly/all_cities.csv`.
  The legacy `redfin_market_tracker` file froze at 2026-05 after the May 2026 relaunch.
- Redfin: filter on Region ID, not name (names repeat within a state).
- CSV scans use `infer_schema=False` plus explicit strict casts.
- LMU source: MAAR / 10K Research (covers the 16-county region; SPAAR not needed).
- 10K Research returns the latest report for unpublished months (200, no error).
  The parser's month check is the only guard. Schedule lmu-pdfs around the 15th.
- LMU: the prior-year month is stored as a level (captures revisions); change columns dropped.
- Shared metric names where the concept matches: `homes_sold`, `median_sale_price`,
  `new_listings`, `inventory`, `months_of_supply`. Kept distinct where definitions may
  differ: `price_per_sqft`, `pct_of_original_list_received`, `days_on_market`.
- LMU PDFs aren't committed (copyrighted, public repo). `tests/fetch_lmu_fixtures.sh`
  re-downloads them from dated URLs.
