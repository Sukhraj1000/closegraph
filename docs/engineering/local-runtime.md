# Local development runtime

The local stack has one PostgreSQL container and five host processes: the API, one Dagster gRPC code location, its daemon, its webserver, and Vite. The API accepts loopback peers only. Docker Compose provisions PostgreSQL; it does not containerize the API.

The host processes run under macOS Seatbelt. Their environment is built from explicit local configuration and their network access is limited to the listed loopback ports. They cannot access the Docker socket or external provider endpoints. Dagster multiprocessing may create POSIX semaphores only in the namespace derived from this runtime state directory. The gRPC entry point sets that namespace before spawning workers; unrelated semaphore names remain denied. Docker runs only from the user-invoked parent controller. This setup requires macOS; there is no unsandboxed fallback.

| Service | Address |
| --- | --- |
| Application | http://127.0.0.1:24173 |
| API health | http://127.0.0.1:24180/api/health |
| Dagster webserver | http://127.0.0.1:24181 |
| Dagster code location | 127.0.0.1:24182 |
| PostgreSQL | 127.0.0.1:55432 |

Install Python 3.12, uv, Node.js compatible with the locked web package, and Docker Desktop with Compose. From the repository root, install the locked dependencies:

```sh
uv sync --locked --project apps/api
npm ci --prefix apps/web
```

Initialize local credentials and start:

```sh
python3.12 scripts/local_runtime.py init
python3.12 scripts/local_runtime.py up
python3.12 scripts/local_runtime.py status
```

`init` generates separate random passwords for `accountant`, `account_manager`, `fund_manager` and `investor`, plus PostgreSQL. Sign in with the username and its own password; there is no account chooser. Credentials are in the owner-only `.local/dev-runtime/.env`, using `CLOSEGRAPH_ACCOUNTANT_PASSWORD`, `CLOSEGRAPH_ACCOUNT_MANAGER_PASSWORD`, `CLOSEGRAPH_FUND_MANAGER_PASSWORD` and `CLOSEGRAPH_INVESTOR_PASSWORD`. Upgrading retains existing passwords and moves their configuration to the business account names. The retired login names are disabled. These are local development accounts.

At startup, existing collection ownership is migrated in an append-only revision before jobs start. Uploaded files and immutable historical snapshots stay unchanged. Active processing must finish before this migration runs. Existing assignments and contributors move together, so independent approval remains enforced. Rules whose assigned people changed require reevaluation. Back up the database and data directory before updating an existing runtime.

The API starts first, applies the checked-in database migrations, and seeds two separate empty packs: synthetic-pack for the native workflow and synthetic-pdf-pack for PDF evidence. The accountant and account manager identities have explicit grants to both; their source evidence and pack histories remain separate. Financial pack state resides in PostgreSQL; evidence bytes reside in the runtime data directory. Dagster uses its local default SQLite metadata storage below `.local/dev-runtime/dagster`. Its generated workspace contains exactly one explicit gRPC location, `closegraph.pipeline.location`; the daemon and webserver share that workspace. Vite proxies `/api` to the loopback API.

`up` waits for the database and all five host services. It checks the API health route, HTTP availability for Vite and Dagster, the gRPC listener, and current error-free heartbeats for all daemon types required by the instance. An existing healthy owned service is reused. A port occupied by another process causes startup to fail without stopping that process. Startup failure stops only the host services started by that invocation, retaining database data and logs.

Stop and restart:

```sh
python3.12 scripts/local_runtime.py down
python3.12 scripts/local_runtime.py up
```

`down` stops recorded processes only when both their PID and recorded start identity still match. It stops the managed PostgreSQL container and retains its volume. Repeated shutdown is safe. `down --keep-db` leaves PostgreSQL running. It never removes volumes. Logs are retained under `.local/dev-runtime/logs`; `status` shows their paths and per-service running/health state.

For existing loopback PostgreSQL, initialize and edit the private environment so `CLOSEGRAPH_DATABASE_URL`, PostgreSQL username/password/database, and `CLOSEGRAPH_POSTGRES_PORT` agree, then use:

```sh
python3.12 scripts/local_runtime.py up --no-db
```

The URL's published port must match `CLOSEGRAPH_POSTGRES_PORT`. The API applies migrations with those credentials. `--no-db` avoids Docker invocation and does not make an externally managed database this runtime's responsibility.

An explicit configuration file is supported with `--env-file /absolute/path/to/private.env`; copy `.env.example`, replace the placeholders, and use `chmod 600` on the resulting file. The parser accepts whitelisted `NAME=value` entries, optionally JSON-quoted, and never sources shell expressions. The data directory must lie inside the selected state directory. Global options precede the command:

```sh
python3.12 scripts/local_runtime.py --state-dir /absolute/path/to/runtime --env-file /absolute/path/to/private.env up
```

The default `.local/dev-runtime` is separate from other `.local` runtime data. The application ports are fixed; two full stacks cannot use these ports at the same time. PostgreSQL's port and Compose project name are configurable. Changing PostgreSQL passwords after initial database creation requires updating the database role too; changing an environment variable alone does not rotate an existing PostgreSQL volume's password.

Provider keys and GitHub/Codex credentials are not runtime settings and must not be placed in this environment. The host service environment does not inherit them. A configured provider transport is a separate trusted coordinator concern; starting this stack does not enable live provider requests.

Run the controller's tests without starting Docker or any server:

```sh
python3.12 scripts/local_runtime.py self-test
```

These tests verify idempotent initialization/shutdown, private credentials, literal environment parsing, child environment isolation, PID-reuse protection, and the explicit loopback service commands. They do not establish that Docker or the complete application is healthy on a particular machine. The runtime health checks provide that evidence when `up` succeeds.

PDF reporting evidence defaults to DISABLED. To inspect the exact captured synthetic
response, explicitly set CLOSEGRAPH_PDF_MODE=CAPTURED_REPLAY and
CLOSEGRAPH_PDF_CAPTURE_DIR to the capture directory containing receipt.json,
parse-response.json and synthetic.pdf. The files must lie inside the project or
runtime directories readable by the host service sandbox. After changing provider configuration, run `down --keep-db` then `up`; `up` reuses healthy processes and does not reload their environment. Upload the exact
synthetic.pdf using the reporting-evidence role with a fresh upload receipt to ingest a new source version. Rechecking only recomputes existing observations and preserves their earlier provider state. Hashes and provider job identity
must match the capture; a different PDF is unavailable, with no silent network
fallback. Canonical observation mode is REPLAY, and evidence metadata labels it
CAPTURED_REPLAY while preserving the historical LIVE capture provenance.
The raw response is stored by content hash with the pack's scoped evidence.
PDF observations currently have no approved financial interpretation mapping,
so their source coverage remains blocked and the original-page citation can be
inspected without claiming a trusted financial value.

A trusted caller may inject a LIVE provider through build_services(pdf_provider=...).
Selecting LIVE without that transport reports live_transport_unavailable. The local
runtime never loads a provider key or broadens its network boundary.
