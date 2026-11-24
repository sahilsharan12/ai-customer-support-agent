# AI Customer Support Agent

FastAPI backend and browser dashboard for customer chat, order history, returns, refund review, and audit history. LangGraph routes chat through account preferences, policy retrieval, order support, and return confirmation. Ollama serves `qwen3:1.7b` locally. The default policy search uses the bundled Markdown files and needs only that one Ollama model.

## Start on Windows

Use PowerShell from the project root. If `.venv-windows` is already set up, skip environment creation.

```powershell
py -3.12 -m venv .venv-windows
.\.venv-windows\Scripts\python.exe -m pip install -r requirements-dev.txt
```

On a fresh checkout, create a local configuration and generate a signing secret. Keep an existing `.env` in place.

```powershell
if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
    $jwtSigningSecret = .\.venv-windows\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
    (Get-Content .env) -replace '^JWT_SECRET_KEY=$', "JWT_SECRET_KEY=$jwtSigningSecret" | Set-Content -Encoding ascii .env
    Remove-Variable jwtSigningSecret
}
```

Start the Ollama desktop app or run `ollama serve` in a separate terminal. Check `ollama list` and run `ollama pull qwen3:1.7b` only if the model is absent. Then start the API.

```powershell
.\.venv-windows\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --no-access-log
```

Open the [support dashboard](http://127.0.0.1:8000/dashboard) or [Swagger UI](http://127.0.0.1:8000/docs). Use an account email as the OAuth2 username in Swagger. To test the local model independently, run `.\.venv-windows\Scripts\python.exe test_qwn.py`.

Customers can return to previous conversations, read the policy source filenames attached to chat replies, and save or clear an account-wide reply preference. Say `Remember that I prefer concise replies` in chat, or use Preferences. Dictation and read-aloud use the browser's on-device speech features when available. Dictation may require a browser language pack. Staff can review returns, record inspections, and see aggregate activity. Admins can link accounts, review refunds, and view the audit log.

The default historical order database is `database/olist.db`. If you have the Olist CSVs under `data/raw/olist/archive`, use `python -m database.create_olist_db` to build it. For an existing Olist database, `python -m database.order_indexes` adds order lookup indexes.

## Try returns with recent sample orders

Use a separate order database and a separate writable data directory. These PowerShell variables apply to commands in the current window.

```powershell
if (-not (Test-Path database/demo_orders.db)) {
    .\.venv-windows\Scripts\python.exe -m database.create_demo_db
}
$env:ORDER_DB_PATH = 'database/demo_orders.db'
$env:SUPPORT_DATA_DIR = 'data/demo'
$env:DEMO_REFUNDS_ENABLED = 'true'
.\.venv-windows\Scripts\python.exe -m backend.provision_staff_user
.\.venv-windows\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --no-access-log
```

1. Create an admin in the provisioning prompt, then register a customer with `POST /auth/register`.
2. Authorize in Swagger as admin. Link the customer's account ID to `demo-customer-001` with `PUT /admin/customers/{user_id}/order-profile`. In a real workflow, an admin must independently verify the customer's ownership before using this endpoint.
3. Authorize as the customer. Check `GET /customers/me/orders`, submit a return with `POST /returns`, or ask chat to return `demo-order-1001` because you changed your mind. Reply `confirm` to the chat draft using the same conversation ID.
4. Authorize as admin to review the return, create a refund record, record receipt and inspection, and approve a refund up to the verified payment balance. Each sample order has a BRL 100 payment.

The sample delivery dates are relative to when you create the database. When its seven-day return window expires, create a new sample database with `--output` and update `ORDER_DB_PATH`.

Refund processing defaults to disabled. When enabled in demo mode, its completion response is labelled `mode: demo`. It only writes local records. A real payment provider and order-to-payment mapping are needed for live refunds.

## Tests and optional vector search

```powershell
.\.venv-windows\Scripts\python.exe -m pytest -q
```

Automated tests use disposable databases and stand-in model responses. For a live check of Qwen preparing a draft and the API saving it after confirmation, run `.\.venv-windows\Scripts\python.exe -m backend.new.test_return_tool_calling`.

For the browser smoke test against a real Uvicorn process, install Playwright and use the installed Microsoft Edge or Chrome.

```powershell
.\.venv-windows\Scripts\python.exe -m pip install 'playwright>=1.48,<2'
.\.venv-windows\Scripts\python.exe -m tests.browser_smoke --channel msedge
```

To evaluate the installed intent classifier, run `python -m nlp.evaluate_intents` with the local train and test splits. The script excludes normalized exact matches to training prompts and reports accuracy and macro F1. These rates measure the supplied dataset.

To use Chroma vector search, install the separate `nomic-embed-text` Ollama model, run `python -m rag.ingest`, and set `POLICY_RETRIEVAL=vector`. Use the default `local` mode for lower memory use.

## Agent controls and evaluation

LangGraph runs separate routing, retrieval, model, and tool nodes. The tool loop is bounded to three execution rounds and six calls. The Ollama client retries an eligible transient failure once. The project keeps `qwen3:1.7b` and lightweight local policy retrieval as its defaults.

| Customer request | Handling |
|---|---|
| Verify an order | Scoped read-only tools. Chat formats order results from the database. |
| Ask about a policy | A relevant passage with its source filename. Missing or unavailable evidence opens a staff case. |
| Start a return | The workflow validates eligibility and asks the customer to confirm the saved draft. |
| Request a refund | Opens a refund review case. Staff use the existing return and refund workflow for any financial decision. |
| Cancel an order | Verifies the order and saves a short-lived draft. Confirmation rechecks eligibility and creates a staff case. |
| Change sensitive account data | Sends the request to admin review. Staff need a verified support process for the actual change. |
| Uncertain answer or unavailable model | Opens a staff case and returns a reference. |

In Swagger, customers can check `GET /customers/me/support-cases`. Staff can review queues with `GET /staff/support-cases`. The decision endpoint uses `POST /staff/support-cases/{case_id}/decision`. A support agent can decide low-confidence cases. An admin handles protected cases. Decisions record the reviewer and timestamp. Cancellation and account changes remain review requests with the current historical data source.

The chat path masks common credential and personal-data patterns before saving messages or sending them to Ollama. It validates tool arguments against the route's allowlist and filters private fields out of tool results. A heuristic detector blocks common instruction overrides. Treat it as one layer of protection when working with real customer data.

Run `python -m evaluation.evaluate_policy` to check citations, expected facts, extractive faithfulness, and abstention against the checked-in policy examples. Run `python -m nlp.evaluate_intents` against the local held-out classifier split. These checks report their dataset sizes so the results can be interpreted in context.

The local intent evaluation measured **98.85% accuracy** and **98.74% macro F1** on **3,642** held-out examples. The policy benchmark passed **six evidence-and-citation cases** and **one abstention case**. The policy benchmark measures the project's extractive answers on a small set of examples.

Admins can see assistant metrics at `/admin/metrics`. Counters include tool attempts and successes, model retries and errors, observed token usage, response latency, policy hits, and escalation rate. `SUPPORT_OTEL_CONSOLE=true` enables local OpenTelemetry spans in the server console. Spans contain workflow and status information without prompts, personal identifiers, or credentials.

## Container and deployment

`docker compose up --build` builds and starts the API using the signing secret from `.env`, a persistent volume for support data, and the existing order database mounted read-only. Run Ollama on the host and make it reachable at `host.docker.internal:11434` from Docker. Provision staff inside the container using `docker compose exec support python -m backend.provision_staff_user`.

- `/health` checks the application's SQLite connection. `/ready` additionally checks the order database and configured Ollama model.
- `/staff/analytics` reports durable aggregate counts. `/admin/metrics` reports request counts and latency for the current API process. It resets on restart.
- The supplied container uses one API process with SQLite and in-process rate limits. Before an internet-facing deployment, configure TLS, persistent backups, and shared rate limiting at the gateway if using multiple API instances.
- GitHub Actions is configured for a clean Python installation, API tests, JavaScript syntax validation, and a container build. Run it by pushing to your chosen GitHub repository.
- Live refunds require payment-provider credentials and a verified mapping from orders to original payments.
- The [AWS deployment checklist](docs/aws-deployment.md) covers provisioning and verification once an AWS account, region, and hosting budget are selected.
