# Testing & verification scripts

End-to-end smoke tests and load tests that exercise the deployed system
through its public HTTP API. Use these to verify a deployment is healthy
or to capture baseline performance numbers.

## Scripts

### `verify_deployment.ps1`

Quick smoke test covering ~10 critical paths:
- `/health` (postgres / redis / broker / vector_store / storage)
- Login + `auth/me`
- Knowledge-base list

Logs to `.tmp/verify_deployment.log` and prints `PASS/FAIL/SKIP` counts.

```powershell
powershell -ExecutionPolicy Bypass -File scripts/testing/verify_deployment.ps1
```

### `loadtest_lightweight.ps1`

50-concurrent PowerShell job load test against the lightweight stack.
Each job issues `$ITERATIONS` GET `/knowledge-bases` calls, capturing
Docker memory + CPU stats at baseline / midpoint / end.

```powershell
powershell -ExecutionPolicy Bypass -File scripts/testing/loadtest_lightweight.ps1
```

Configuration (edit the script):
- `$CONCURRENCY` — number of parallel jobs (default: 50)
- `$ITERATIONS` — requests per job (default: 30)

## Where do logs go?

Both scripts write timestamped logs to `.tmp/` so they don't pollute the
repo. The `.tmp/` directory is in `.gitignore`.