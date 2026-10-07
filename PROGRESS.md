# Progress — east-side-almanac

**Current phase:** 1 — Local pipelines in Docker
**Current step:** 1.2 — pinned dependencies
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

- 1.1 Multi-stage Dockerfile. Builder: `python:3.12-slim` + uv 0.12.23, `uv sync --locked --no-install-project` with a cache mount and bind mounts (dependency layer keyed only on the lockfile). Runtime: same base via shared `ARG BASE`, copies only `/app/.venv` and `app/`. Runs as UID 10001 `almanac`; `/app` is root-owned and read-only; `/data` is the only writable path. `.dockerignore` keeps `.venv`, `.git`, `data`, and `__pycache__` out of the build context. Image: 138 MB compressed / 586 MB on disk; dependencies are ~118 MB of that.

## In flight

- 1.2 Pinned dependencies: base image digest vs tag; check which `polars-runtime-*` packages polars 2.0 pulled in

## Blocked / open questions

- Phase 5: existing `tofu-state-805595753711` roject key, or give this project its ownbackend?

## Decisions

- Scope: data asset. Analytics parked until th
- Region: us-east-1 (pick one and never move)
- Secrets: SSM Parameter Store SecureString, not Secrets Manager
- No SQL engine: readers use polars over curated Parquet
- Revisions: append-only vintages, keyed on pulled_at
- Access: the IAM user can only assume the opecy names that user and requires MFA (`Boolaws:MultiFactorAuthPresent`, not `BoolIfExists`).
- CLI MFA uses `mfa/microsoft-auth`; passkeys CLI.
- Operator role has AdministratorAccess for now; least privilege comes in Phase 5.
- Python 3.12; uv for dependency management and locking (`uv.lock`, hashes by default).
- Base image: `python:3.12-slim` (glibc, so po. Not Alpine.
- Images build as arm64 (Apple Silicon). Fargaided in Phase 3.
- Non-root runtime: fixed UID 10001; code is read-only to the app user. The reason is general defense-in-depth (supply chain, any dependency), not one specific library.
