# Telocan

A Turkcell-style telecom demo project: a PostgreSQL database of customers, packages,
subscriptions, usage, and invoices, queried in **natural language (Turkish)** through a locally
running LLM (via [Ollama](https://ollama.com)) that translates questions into SQL. Includes an
MCP server for use with Claude Code/Desktop, and a Flask web app with login, chat history, a
report/feedback loop, and an admin panel.

Everything runs locally and free — no cloud API keys, no paid services.

## Features

- **Natural language → SQL** (`nl2sql.py`): ask a question in Turkish, get a validated read-only
  SQL query run against Postgres, plus the results.
- **MCP server** (`server.py`): exposes the same functionality as an MCP tool, so Claude Code can
  query the database directly.
- **Web app** (`web/`):
  - Email/password login and registration (hashed passwords, session-based auth)
  - Chat interface with a sidebar of past conversations (create, resume, delete)
  - A "report this answer" button on every response, with a toast confirmation
  - An admin panel (`/admin`) for reviewing reports, marking them fixed, and granting admin
    access to other accounts by searching their email

## Tech stack

- **Database**: PostgreSQL
- **LLM**: [Ollama](https://ollama.com) running `qwen2.5-coder` locally
- **Backend**: Python, Flask (web app), the official `mcp` SDK (MCP server), `psycopg2` (DB
  driver)
- **Frontend**: plain HTML/CSS/JS, no build step

## Prerequisites

- PostgreSQL installed and running
- [Ollama](https://ollama.com) installed, with the model pulled:
  ```bash
  ollama pull qwen2.5-coder
  ```
- Python 3.10+

## Setup

1. **Create the database and load the schema/seed data:**
   ```bash
   createdb telecom
   psql -U postgres -d telecom -f schema.sql
   psql -U postgres -d telecom -f seed.sql
   ```

2. **Install Python dependencies:**
   ```bash
   pip install psycopg2-binary python-dotenv requests mcp flask
   ```

3. **Configure environment variables** — copy `.env.example` to `.env` and fill in your own
   values:
   ```bash
   cp .env.example .env
   ```
   ```
   DATABASE_URL=postgresql://postgres:yourpassword@localhost:5432/telecom
   OLLAMA_URL=http://localhost:11434
   OLLAMA_MODEL=qwen2.5-coder
   FLASK_SECRET_KEY=<generate with: python -c "import secrets; print(secrets.token_hex(32))">
   ```

## Running it

### Web app

```bash
cd web
python app.py
```
Open `http://127.0.0.1:5000`, register an account, and start asking questions.

To make an account an admin:
```sql
UPDATE users SET is_admin = TRUE WHERE email = 'you@example.com';
```

### MCP server (for Claude Code / Claude Desktop)

The project includes a `.mcp.json` — open this folder in Claude Code and approve the `telocan`
MCP server when prompted. It exposes one tool, `query_telecom_db(question)`, which does the same
thing as the web app: generates SQL, runs it, and returns the results.

## Project structure

```
Telocan/
  nl2sql.py           # Core: question -> SQL -> validated -> executed -> rows
  server.py           # MCP server wrapping nl2sql.py as a tool
  schema.sql          # Database schema
  seed.sql            # Sample data
  .env.example        # Required environment variables (no secrets)
  web/
    app.py            # Flask app: auth, chat, conversations, reports, admin
    templates/
      index.html      # Main chat UI
      login.html
      register.html
      admin.html      # Reports + admin user management
```

## Notes

- This runs a small (7B) local model, not a frontier hosted model — most questions work
  reliably, but genuinely complex multi-step questions occasionally need a rephrase or a retry.
  This is expected behavior for a free, fully local setup, not a bug.
- All database text (names, cities, etc.) is stored as plain ASCII; the NL→SQL layer handles
  converting Turkish characters for matching.
