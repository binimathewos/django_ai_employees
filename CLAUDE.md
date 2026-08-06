# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Django app simulating "AI employees" for a fictional AC retailer (CoolBreeze AC). Customers chat about an order; a support agent (Claude with tools) answers, can escalate to a manager agent, which can consult a risk/fraud agent. Staff watch the whole agent chain live on a dashboard via server-sent events.

## Commands

The virtualenv lives in `env/` (not tracked-friendly, already created locally).

```bash
source env/bin/activate
pip install -r requirements.txt

python manage.py runserver
python manage.py migrate
python manage.py makemigrations <app>
python manage.py createsuperuser
python manage.py loaddata demo_data          # orders/fixtures/demo_data.json
python manage.py loaddata fraud_test_data    # customer with a bad refund pattern, for exercising the risk agent
python manage.py collectstatic               # STATIC_ROOT is ./static, already committed

# Tests (both tests.py files are empty stubs)
python manage.py test
python manage.py test support.tests.SomeTest.test_method
```

Seeding the RAG index (no management command — run from the shell, and only once, since `collection.add` will duplicate chunks on re-run):

```bash
python manage.py shell -c "from support.rag import load_documents; load_documents()"
```

Production entrypoint is `Procfile`: `gunicorn dj_ai_employee_main.wsgi`.

## Configuration

All settings come from `.env` via `python-decouple` (`config(...)`) and are **required** — a missing key raises at import, so Django won't start. Keys: `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS` (comma-separated), `DB_NAME`/`DB_USER`/`DB_PASSWORD`/`DB_HOST`/`DB_PORT`, `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`.

The model id is never hardcoded — `settings.ANTHROPIC_MODEL` is read once at `support/agents.py` import time.

Database: PostgreSQL via `psycopg` 3 (`django.db.backends.postgresql`). Migrated off MySQL on the `postgrase-sql-migration` branch; local dev uses role `ai_employee` owning database `ai_employee_db` on port 5432. `mysqlclient` is gone from `requirements.txt` — don't reintroduce it.

## Architecture

### Agent chain (`support/agents.py`)

Three agents, each a hand-written while-loop over `client.messages.create(...)` — no framework. All three follow the same shape: call the model, append `response.content` as the assistant turn, and if `stop_reason == "tool_use"`, run each `tool_use` block, append the results as one `user` message of `tool_result` blocks, and loop; otherwise join the text blocks and return.

- `run_support_agent(conversation_id, order_id, user_id)` — Maya. Loads prior turns from the `Message` table as its message history. Tools: `SUPPORT_TOOLS`.
- `run_manager_agent(case_summary, conversation_id)` — refund decision maker. Tools: `MANAGER_TOOLS`.
- `run_risk_agent(user_id, conversation_id)` — fraud verdict. Tools: `RISK_TOOLS`.

Agents call each other **through the tool dispatcher, synchronously**: `execute_tool` maps `escalate_to_manager` → `run_manager_agent` and `assess_fraud_risk` → `run_risk_agent`, so the sub-agent's final text is returned to the caller as a tool result. The whole chain runs inside the one HTTP request in `support.views.chat`.

Adding a tool means touching three places: the JSON schema in the relevant `*_TOOLS` list, a branch in `execute_tool`, and the implementation in `support/tools.py` (or a nested agent runner).

### Live streaming (`support/event_queue.py`)

In-process pub/sub: a module-level `subscribers` dict of `{conversation_id: [queue.Queue, ...]}`. Agents call `publish(conversation_id, event)` at every step; `support.views.conversation_stream` subscribes and yields SSE frames to the dashboard. Because it's in-memory and per-process, it only works with a single worker — multiple gunicorn workers will drop events for viewers attached to another process.

Every published event is also persisted as an `AgentLog` row, so `conversation_detail` can replay a finished conversation without SSE. Event types: `tool_call`, `tool_result`, `manager`, `risk`, `final`, plus the `DONE` sentinel.

### RAG (`support/rag.py`)

ChromaDB `PersistentClient` at `./chroma_db` with the default embedding function, collection `coolbreeze_docs`. `load_documents()` reads the PDFs in `support/documents/` (refund policy, warranty policy, product FAQ), chunks at ~500 chars, and adds them. `search_knowledge_base(query)` returns the top 3 chunks joined — reached by the support agent through the `search_knowledge_base` tool.

### Data

- `orders` app owns `Product`, `Order`, `RefundRequest` — the facts the tools read. Customer-facing views (`order_list`, `order_detail`) are `@login_required` and always scoped to `request.user`.
- `support` app owns `Conversation` (one per user+order, via `get_or_create`), `Message`, `AgentLog`. Staff views are `@staff_member_required`.
- Delivery tracking is fake: a hardcoded dict in `support/tracking_data.py` keyed by tracking number.
- `db.sqlite3` at the root is a leftover empty file; the project does not use SQLite.

### Request flow

`POST /support/chat/<order_id>/` (fetch from `templates/order_detail.html`) → save user `Message` → `run_support_agent` runs the full chain synchronously → save assistant `Message` → return `{"reply": ...}`. Meanwhile `GET /support/dashboard/stream/<conversation_id>/` streams the agent's internal steps to `templates/support/conversation_detail.html`.

## Conventions

- Templates live in the root `templates/` dir (`DIRS: ["templates"]`), not per-app.
- Prompts are plain module-level string constants in `support/agents.py`; the support prompt is `.format()`-ed with `order_id` and `user_id`, so any new literal braces in it must be escaped.
- Tools return plain dicts and are JSON-serialized into `tool_result` content; error cases return `{"error": "..."}` rather than raising.
- `test-claude.py` at the root is a scratch API-connectivity check, not part of the app.
