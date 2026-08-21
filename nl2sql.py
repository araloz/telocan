import os
import re
import json
import requests
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

OLLAMA_URL = os.environ["OLLAMA_URL"]
OLLAMA_MODEL = os.environ["OLLAMA_MODEL"]
DATABASE_URL = os.environ["DATABASE_URL"]

SYSTEM_PROMPT = """You are a SQL generation assistant for a telecom company's database (PostgreSQL).

Schema:
customers(id, first_name, last_name, phone_number, national_id, city, signup_date, line_type, status)
  - line_type: 'prepaid' (Turkish: kontrollu) or 'postpaid' (Turkish: faturali)
  - status: 'active', 'suspended', 'cancelled'
packages(id, name, category, internet_gb, sms_count, voice_minutes, monthly_price, is_active)
  - category: 'mobile', 'combo'  (phone packages only, no home internet)
subscriptions(id, customer_id, package_id, start_date, end_date, status)
  - status: 'active', 'cancelled'
usage_records(id, subscription_id, period_month, internet_used_mb, sms_used, minutes_used)
invoices(id, customer_id, period_month, amount, is_paid, due_date)

Rules:
- Output ONLY a single valid PostgreSQL SELECT statement. No explanation, no markdown fences.
- Never generate INSERT, UPDATE, DELETE, DROP, or any statement that modifies data.
- Map user terms: "kontrollu"/"prepaid" -> line_type = 'prepaid'; "faturali"/"postpaid" -> line_type = 'postpaid'.
- Always join through subscriptions when a question spans customers and packages/usage.
- If the question is ambiguous, make the most reasonable assumption and just generate the query.

Date handling (period_month and due_date are DATE columns, always the 1st of the month for period_month):
- date_trunc('month', some_date) is a FUNCTION CALL, never a type or cast. NEVER write `x::date_trunc(...)`.
- IMPORTANT: only add a date/month filter when the question EXPLICITLY mentions a time period
  (e.g. "this month", "last month", "in July", "bu ay", "geçen ay"). If the question does not
  mention any time period, do NOT add a date_trunc filter at all -- match across all periods.
- "this month" / "bu ay" -> date_trunc('month', column) = date_trunc('month', CURRENT_DATE)
- "last month" / "geçen ay" -> date_trunc('month', column) = date_trunc('month', CURRENT_DATE - INTERVAL '1 month')
- "overdue" / "past due" -> due_date < CURRENT_DATE AND is_paid = FALSE

Examples:
Q: which customers have not paid their invoice this month?
A: SELECT c.* FROM customers c JOIN invoices i ON i.customer_id = c.id WHERE i.is_paid = FALSE AND date_trunc('month', i.period_month) = date_trunc('month', CURRENT_DATE);

Q: which customers have not paid their invoices?
A: SELECT c.* FROM customers c JOIN invoices i ON i.customer_id = c.id WHERE i.is_paid = FALSE;

Q: how much internet did customers use last month?
A: SELECT s.customer_id, SUM(u.internet_used_mb) FROM usage_records u JOIN subscriptions s ON s.id = u.subscription_id WHERE date_trunc('month', u.period_month) = date_trunc('month', CURRENT_DATE - INTERVAL '1 month') GROUP BY s.customer_id;

User question: {question}
"""

# Only allow statements that start with SELECT and contain no write/DDL keywords.
FORBIDDEN_KEYWORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|GRANT|REVOKE|CREATE|EXEC|CALL)\b",
    re.IGNORECASE,
)


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:sql)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def generate_sql(question: str) -> str:
    prompt = SYSTEM_PROMPT.format(question=question)
    response = requests.post(
        f"{OLLAMA_URL}/api/generate",
        json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
        timeout=60,
    )
    response.raise_for_status()
    raw = response.json()["response"]
    return _strip_code_fences(raw)


def validate_sql(sql: str) -> None:
    stripped = sql.strip().rstrip(";")
    if not re.match(r"^\s*SELECT\b", stripped, re.IGNORECASE):
        raise ValueError(f"Rejected non-SELECT query: {sql}")
    if ";" in stripped:
        raise ValueError(f"Rejected multi-statement query: {sql}")
    if FORBIDDEN_KEYWORDS.search(stripped):
        raise ValueError(f"Rejected query containing forbidden keyword: {sql}")


def run_query(sql: str) -> list[dict]:
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql)
            rows = cur.fetchall()
            return [dict(row) for row in rows]
    finally:
        conn.close()


def ask_database(question: str) -> dict:
    sql = generate_sql(question)
    validate_sql(sql)
    rows = run_query(sql)
    return {"question": question, "sql": sql, "rows": rows}


if __name__ == "__main__":
    print(f"Connected to Ollama model '{OLLAMA_MODEL}'. Type a question (or 'quit').")
    while True:
        q = input("\n> ")
        if q.strip().lower() in ("quit", "exit"):
            break
        try:
            result = ask_database(q)
            print(f"SQL: {result['sql']}")
            print(f"Rows: {json.dumps(result['rows'], indent=2, default=str)}")
        except Exception as e:
            print(f"Error: {e}")
