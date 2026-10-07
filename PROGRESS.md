
# Progress — east-side-almanac

**Current phase:** 1 — Local pipelines in Docker
**Current step:** 1.6c — redfin job
**Last worked:** 2026-10-07

## Done

### Phase 0 — AWS guardrails

- 0.1 Budget: `account-budget`, $5/month. Alerts: ACTUAL 80/100%, FORECASTED 80/100%, emailed directly with no SNS.
- 0.2 Cost Anomaly Detection: kept the account's auto-created `Default-Services-Monitor` and `Default-Services-Subscription`. Changed the threshold from ($100 AND 40%) to an absolute $1 (impact % is undefined when expected spend is ~$0). Daily email summary.
- 0.3 Region: us-east-1.
- 0.4 Project role: `east-side-almanac-operator`, assumed via the `almanac` CLI profile with MFA. `anthony-admin` was removed from the `admin` group and can now only `sts:AssumeRole` this role. Access key rotated.
- 0.5 FRED key: `/east-side-almanac/fred/api_key`, SecureString, Standard tier, `alias/aws/ssm`.
- 0.6 Repo skeleton: `app/`, `infra/`, `tests/`, `docs/`, `.gitignore`.

### Phase 1 — Local pipelines in Docker

- 1.1 Multi-stage Dockerfile. Builder: `python:3.12-slim` + uv 0.12.23, `uv sync --locked --no-install-project` with a cache mount and bind mounts (dependency layer ). Runtime: same base via shared `ARG BASE`,copies only `/app/.venv` and `app/`. Runs as UID 10001 `almanac`; `/app` is root-owned and read-only; `/data` is the only writable path. `.dockerignore` keeps `.venv`, `.git`, `data`, `infra`, and `**/__pycache__` out of the build context. Image: 138 MB compressed / 586 MB on disk; dependencies are ~118 MB of that.
- 1.2 Base image pinned by multi-arch index digest. polars 2.0 uses the default `polars-runtime-32`; no rt64/compat
  needed.
- 1.3 CLI: `python -m app {fred,redfin,lmu-pdfs}`, argparse subcommands, lazy job imports. `ENTRYPOINT ["python", "-m", "app"]`, `CMD ["--help"]`.
- 1.4 Config from env only: `ALMANAC_OUTPUT_ROOT` (required, no default), `FRED_API_KEY` (fred only). `ConfigError` →
  one log line, exit 1.
- 1.5 `docker-compose.yml`: `docker compose run --rm --build app <job>`, `./data` → `/data`. Docker Desktop translates bind-mount ownership; Linux/CI won't.
- 1.6a fred job: 7 series, 5-year lookback, 5, to `curated/fred/YYYY-MM-DD.parquet`. Asame-day rerun overwrites that file (idempotent: one vintage per pull date). Verified: schema typed, `source` = `fred`, 1 vintage, row counts match calendar math.
- 1.6b fred raw: each series' original JSON saved to `raw/fred/YYYY-MM-DD/<series>.json` before parsing, via `app/storage.write_bytes` (local path or s3://). No API key in the response body. Raw confirms the parser: DGS10 count
  1502 vs 1440 rows = 62 "." holidays.

## In flight

- 1.6c redfin job: stream the gzipped city trae = MN for the 7 cities, raw write must streamtoo

## Blocked / open questions

- Phase 5: existing `tofu-state-805595753711` roject key, or give this project its ownbackend?
- Phase 2 data dictionary: CPIAUCSL and UNRATE have no 2025-10 observation (FRED returns "."). Real source gap; not filled in.
- Phase 2/3: `storage.write_bytes` S3 branch is untested until Phase 3; cover with a fake S3 client in Phase 2 tests.

## Decisions

- Scope: data asset. Analytics parked until there's real history.
- Region: us-east-1 (pick one and never move)
- Secrets: SSM Parameter Store SecureString, not Secrets Manager
- No SQL engine: readers use polars over curated Parquet
- Revisions: append-only vintages, keyed on pu
- Access: the IAM user can only assume the operator role. The trust policy names that user and requires MFA (`Bool aws:MultiFactorAuthPresent`, not `BoolIfExists`).
- CLI MFA uses `mfa/microsoft-auth`; passkeys (u2f) don't work with the CLI.
- Operator role has AdministratorAccess for non Phase 5.
- Python 3.12; uv for dependency management and locking (`uv.lock`, hashes by default).
- Base image: `python:3.12-slim` (glibc, so po. Not Alpine. Pinned by index digest; bumpeddeliberately.
- Images build as arm64 (Apple Silicon). Fargaided in Phase 3.
- Non-root runtime: fixed UID 10001; code is read-only to the app user. The reason is general defense-in-depth (supply chain, any dependency), not one specific library.
- FRED key read from env, not fetched from SSM role injects it, so the task role needs no SSM permission.
- Config errors use a `ConfigError` class so the CLI can log one clean line and exit 1; other exceptions keep full tracebacks.
- Local runs via `docker compose run`, not `up`: jobs are one-off and exit.
- `period_type` is `'day' | 'week' | 'month'`.eekly, dated on Thursdays (FRED's observationdate, not shifted).
- FRED pulls re-read a 5-year window so revisiull history comes from the Phase 7 backfill.
- FRED API errors are re-raised without the request URL, because the key is a query parameter.
- `raw/` = bronze (source bytes as received, written before parsing), `curated/` = silver (typed, conformed to the fact table). No gold in this project.
- Don't store derived series (e.g. FRED's T10Y2Y spread); readers compute them from levels.
