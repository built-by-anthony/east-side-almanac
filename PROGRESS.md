# Progress — east-side-almanac

**Current phase:** 1 — Local pipelines in Docker
**Current step:** 1.1 — multi-stage Dockerfile, non-root
**Last worked:** 2026-10-07

## Done

### Phase 0 — AWS guardrails
- 0.1 Budget: `account-budget`, $5/month. Alerts: ACTUAL 80/100%, FORECASTED 80/100%, emailed directly with no SNS.
- 0.2 Cost Anomaly Detection: kept the account's auto-Monitor` and `Default-Services-Subscription`. Changedthe threshold from ($100 AND 40%) to an absolute $1 (impact % is undefined when expected spend is ~$0). Daily email summary.
- 0.3 Region: us-east-1.
- 0.4 Project role: `east-side-almanac-operator`, assumed via the `almanac` CLI profile with MFA. `anthony-admin` was removed from the `admin` group and can now only `sts:AssumeRole` this role. Access key rotated.
- 0.5 FRED key: `/east-side-almanac/fred/api_key`, Sec`alias/aws/ssm`.
- 0.6 Repo skeleton: `app/`, `infra/`, `tests/`, `docs/`, `.gitignore`.

## In flight

- 1.1 Multi-stage Dockerfile (uv builder → slim runtime), non-root user

## Blocked / open questions

- Phase 5: existing `tofu-state-805595753711` bucket. Share it under a project key, or give this project its own backend?

## Decisions

- Scope: data asset. Analytics parked until there's re
- Region: us-east-1 (pick one and never move)
- Secrets: SSM Parameter Store SecureString, not Secre
- No SQL engine: readers use polars over curated Parquet
- Revisions: append-only vintages, keyed on pulled_at
- Access: the IAM user can only assume the operator ro that user and requires MFA (`Boolaws:MultiFactorAuthPresent`, not `BoolIfExists`).
- CLI MFA uses `mfa/microsoft-auth`; passkeys (u2f) don't work with the CLI.
- Operator role has AdministratorAccess for now; least privilege comes in Phase 5.
- Python 3.12; uv for dependency management and locking (`uv.lock`, hashes by default).
- Base image: `python:3.12-slim` (glibc, so polars usepine.