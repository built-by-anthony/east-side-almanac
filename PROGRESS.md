# Progress — east-side-almanac

**Current phase:** 2 — Data model and quality rules
**Current step:** 2.3 — quality checks that fail the run
**Last worked:** 2026-10-08

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
  `uv sync --locked --no-install-project --no-dev` with a cache mount and bind mounts
  (dependency layer keyed only on the lockfile). Runtime: same base via shared `ARG BASE`,
  copies only `/app/.venv` and `app/`. Runs as UID 10001 `almanac`; `/app` is root-owned and
  read-only; `/data` is the only writable path. `.dockerignore` excludes `.venv`, `.git`,
  `data`, `infra`, `**/__pycache__`. Image: 138 MB compressed / 586 MB on disk.
- 1.2 Base image pinned by multi-arch index digest (Python 3.12.15). polars 2.0 uses the
  default `polars-runtime-32`; no rt64/compat needed.
- 1.3 CLI: `python -m app {fred,redfin,lmu-pdfs}`, argparse subcommands, lazy job imports.
  `ENTRYPOINT ["python", "-m", "app"]`, `CMD ["--help"]`.
- 1.4 Config from env only: `ALMANAC_OUTPUT_ROOT` (required, no default), `FRED_API_KEY`
  (fred only), `LMU_REPORT_MONTH` (optional, `YYYY-MM`). `ConfigError` → one log line, exit 1.
- 1.5 `docker-compose.yml`: `docker compose run --rm --build app <job>`, `./data` → `/data`.
  `FRED_API_KEY` and `LMU_REPORT_MONTH` pass through from the shell (no values in the file).
  Docker Desktop translates bind-mount ownership; Linux/CI won't.
- 1.6a fred: 7 series, window starts Jan 1 of (year − 5), `curated/fred/YYYY-MM-DD.parquet`.
  5,719 rows at the 1.6a pull; 5,722 on 2026-10-07 (+1 each on DGS10, DGS2, DFF);
  5,724 at 17:02 UTC on 2026-10-08 (Thursday mortgage release). Count grows as sources
  publish and drops ~20% each Jan 1 when the window start jumps a year.
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
- 1.7 Clean-clone check (2026-10-07): fresh clone, `--no-cache` build, all three jobs run
  twice. One file and one `pulled_at` per source: fred 5,722 · redfin 17,052 · lmu 224
  (`LMU_REPORT_MONTH=2026-08`; September not yet published). Default LMU run correctly fails
  the month check; `LMU_REPORT_MONTH=nope` → one ConfigError line, exit 1.

### Phase 2 — Data model and quality rules

- 2.0 Partitioning: skipped `partition_by`. Kept one file per source per pull date (see Decisions).
- 2.1 Vocabulary in `app/schema.py`: `COLUMNS`, `CITIES`, `GEO_LEVELS`, `SOURCES`,
  `PERIOD_TYPES`, and 26 `Metric`s (name, unit, stat, description). `Metric.__post_init__`
  validates unit/stat against the `Literal`s; `require_known()` checks every job's mapping at
  import. Verified: all 26 metrics produced, none unknown (2026-10-08).
- 2.2 Vintages: `source_as_of` column (LMU footer "Current as of", Redfin `Last-Modified`,
  FRED null). `tests/test_vintages.py` runs the real LMU job offline against fixtures:
  same-day rerun → 1 file, last write wins; next day → 2 files, 448 rows, latest-per-period
  read = 224 unique. `run(now=)` injectable. pytest is a dev dependency; `--no-dev` keeps it
  out of the image (verified `ModuleNotFoundError`). `.python-version` pins 3.12.

## In flight

- 2.2 wrap-up: watch `test_same_day_rerun_keeps_one_vintage` fail with a timestamped path,
  then revert.
- 2.3 Quality checks that fail the run. Decide where the Redfin vs LMU disagreement check
  runs (it needs both sources; the jobs run on different schedules).

## Blocked / open questions

- Phase 5: existing `tofu-state-805595753711` bucket. Share it under a project key, or give
  this project its own backend?
- Phase 2 data dictionary: CPIAUCSL and UNRATE have no 2025-10 observation (FRED returns ".").
  Real source gap; not filled in.
- Phase 2 data dictionary: "latest vintage" means max `pulled_at` per period, not the latest
  file. FRED's Jan 1 window jump drops a year from the newest pull; per-file reads lose it.
- Phase 2 data dictionary: FRED responses carry `realtime_start` 2026-09-30 on a 2026-10-08
  pull. Query-level real-time period, not per-value publication; not used. True per-value
  vintages need ALFRED (Phase 7).
- `sale_price_per_sqft` (LMU): median or mean? 10K Research doesn't say. Affects `stat` only.
- Phase 2/3: `storage` S3 branches are untested until Phase 3; cover with a fake S3 client.
- Phase 2: Redfin is rolling 3-month, LMU is monthly. Counts (`stat="count"`, `summable`) can
  be summed over 3 months to compare; medians and means can't. The >5% check must use this.
- Phase 2: `curated/lmu/<day>.parquet` collides if two report months are pulled the same day
  (backfill). Put the report month in the path. Also align `curated/lmu/` with source
  `northstar_lmu`.
- Phase 4: schedule FRED after the morning releases (daily series lag ~1 day; mortgage
  rates publish Thursday midday ET). Missing-data check must not alert on that lag or on
  the Jan 1 row-count drop.
- Phase 6: run pytest in the built image or with uv on the runner? Local uv is 3.12.14, the
  image is 3.12.15.
- Phase 7: dated LMU URLs make history fetchable. How far back?
- Cleanup: `lmu_pdfs.py` `run()` comment says reports publish "around the 8th"; the schedule
  decision says the 15th. `config.py` ConfigError docstring says "missing" only; it also
  covers malformed values.

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
- Python 3.12 (`requires-python = ">=3.12,<3.13"`, `.python-version`); uv for dependency
  management and locking (`uv.lock`, hashes by default). Dev group: pytest.
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
- Both checkouts share the `almanac:dev` tag; always `run --build` when switching between them.
- `period_type`: `day | week | month | rolling_3_month | rolling_12_month`.
  FRED mortgage rates are weekly, dated on Thursdays (FRED's date, not shifted).
  Rolling windows overlap; never sum across consecutive rows.
- FRED pulls re-read from Jan 1 of (year − 5) so revisions become new vintages
  (CPI seasonal factors reach back ~5 years); full history comes from the Phase 7 backfill.
- FRED API errors are re-raised without the request URL (the key is a query parameter).
- `raw/` = bronze (source bytes as received, written before parsing).
  `curated/` = silver (typed, conformed to the fact table). No gold in this project.
- Don't store derived series (e.g. FRED's T10Y2Y spread); readers compute them from levels.
- Layout: one file per source per pull date, `curated/<source>/YYYY-MM-DD.parquet`. No
  `partition_by`: month partitions × FRED's daily full-window re-reads ≈ 17,500 files/yr.
  At MB scale, row-group stats replace directory pruning. Revisit if a real reader is slow.
- Logical run = source + pull date (UTC). Same-day rerun replaces (last write wins); a new day
  appends a vintage. Idempotency = vintage count, not identical bytes.
- `source_as_of` (Date, nullable): when the source published. An attribute of the vintage,
  not part of the grain. `pulled_at` = when we learned (transaction time); `source_as_of` =
  publication time. Stateless jobs; readers dedupe identical publications if they want.
- Snapshot vintages, not change-only: stateless jobs, missed runs stay visible, duplicate
  rows cost ~nothing at this size.
- Redfin source: `redfin_data_center/housing_market/monthly/all_cities.csv`.
  The legacy `redfin_market_tracker` file froze at 2026-05 after the May 2026 relaunch.
  `Last-Modified` changes on re-uploads without data changes (seen 2026-10-08).
- Redfin: filter on Region ID, not name (names repeat within a state).
- CSV scans use `infer_schema=False` plus explicit strict casts.
- LMU source: MAAR / 10K Research (covers the 16-county region; SPAAR not needed).
- 10K Research returns the latest report for unpublished months (200, no error).
  The parser's month check is the only guard. Schedule lmu-pdfs around the 15th.
- LMU report month: last month by default; `LMU_REPORT_MONTH=YYYY-MM` overrides it for reruns
  and backfill.
- raw/lmu path month is the *requested* month; the PDF header is authoritative. A failed
  month check leaves a mislabeled raw PDF behind (kept as debugging evidence; raw expires).
- LMU: the prior-year month is stored as a level (captures revisions); change columns dropped.
- LMU PDFs aren't committed (copyrighted, public repo). `tests/fetch_lmu_fixtures.sh`
  re-downloads them from dated URLs.
- Vocabulary (`app/schema.py`): source-agnostic. Mappings from source labels stay in each job.
  Naming rule: statistic first, unit last. Names are permanent once in S3: add, never rename.
- Shared metrics (same definition in both sources): `homes_sold`, `new_listings`, `inventory`
  (active on the last day of the period), `median_sale_price`.
- Kept distinct (definitions differ):
  - Days on market: Redfin `median_days_on_market` (to under contract) vs LMU
    `avg_cumulative_days_on_market` (average, cumulative, to offer accepted).
  - Sale-to-list: Redfin `avg_sale_to_list_pct` (vs final list) vs LMU
    `avg_sale_to_original_list_pct` (vs original list).
  - Months of supply: Redfin `months_of_supply_closed_pace` (≈ inventory / monthly closed
    pace; recomputing differs by ≤0.1, so store as published) vs LMU
    `months_of_supply_pending_12m` (inventory / trailing-12-month avg pending).
  - $/sqft: Redfin `median_sale_price_per_sqft` vs LMU `sale_price_per_sqft` (stat unstated).
- Definition sources: MAAR Monthly Indicators, Aug 2026 (maar.stats.10kresearch.com/docs/mmi);
  Redfin Data Center metrics definitions (redfin.com/news/data-center-metrics-definitions, Jan 2023).
- `Metric.stat` drives comparisons: only `count` is summable; `unverified` is never compared.
- Tests run offline: jobs take `run(now=)`, network replaced by monkeypatching `fetch`.
  Missing fixtures fail the suite (`pytest.fail`), never skip.
