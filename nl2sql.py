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
packages(id, name, category, internet_gb, sms_count, voice_minutes, monthly_price, is_active, is_recurring)
  - category: 'mobile' (voice/SMS only, internet_gb is always 0), 'combo' (bundled voice+SMS+internet),
    'addon' (one-time top-up, see is_recurring below). Phone packages only, no home internet.
  - is_recurring: TRUE = a normal recurring monthly plan; FALSE = a one-time add-on/top-up
    (e.g. "Ekstra 1 GB"), not billed monthly. Turkish: "tekrarlanan" = recurring, "tek seferlik"
    / "tekrarlanmayan" = non-recurring/one-time. monthly_price holds the one-time price for
    is_recurring = FALSE rows.
subscriptions(id, customer_id, package_id, start_date, end_date, status)
  - status: 'active', 'cancelled'
usage_records(id, subscription_id, period_month, internet_used_mb, sms_used, minutes_used)
invoices(id, customer_id, period_month, amount, is_paid, due_date)

Rules:
- If the question is NOT about this telecom database (e.g. asks for code in a programming
  language, general knowledge, jokes, math unrelated to this data, or any other unrelated
  topic), output EXACTLY the single word UNRELATED and nothing else -- no SQL, no explanation,
  no markdown. Do not try to cleverly answer an unrelated question using SQL tricks (e.g.
  generate_series to "count" for someone) -- if it isn't a real question about the schema
  above, it's UNRELATED.
- Otherwise, output ONLY a single valid PostgreSQL SELECT statement. No explanation, no markdown fences.
- Never generate INSERT, UPDATE, DELETE, DROP, or any statement that modifies data.
- Map user terms: "kontrollu"/"prepaid" -> line_type = 'prepaid'; "faturali"/"postpaid" -> line_type = 'postpaid'.
- Always join through subscriptions when a question spans customers and packages/usage.
- If the question is ambiguous, make the most reasonable assumption and just generate the query.
- When filtering by a package name or any other free-text name the user refers to informally
  (e.g. "genc paketi" for "Genc Paketi"), NEVER use exact equality (=). Use a case-insensitive
  partial match instead: column ILIKE '%keyword%'. Exact equality will miss real rows because
  users rarely type the full, exactly-cased name stored in the database.
- IMPORTANT: all text stored in the database (names, etc.) uses PLAIN ASCII ONLY -- Turkish
  diacritics are never stored. Before building an ILIKE pattern from a Turkish question, convert
  any Turkish characters to their plain ASCII equivalents: ı/İ->i/I, ş/Ş->s/S, ğ/Ğ->g/G,
  ü/Ü->u/U, ö/Ö->o/O, ç/Ç->c/C. E.g. "sınırsız konuşma" -> "sinirsiz konusma". Never put
  diacritics inside an ILIKE pattern -- they will never match.
- IMPORTANT: when building an ILIKE pattern for a package/name lookup, use ONLY the core
  distinctive keyword likely to actually appear in the stored name (e.g. "sinirsiz", "premium",
  "ekstra", "genc") -- NEVER glue on adjacent descriptive/feature words from the question (e.g.
  "dakika"/minutes, "paketi"/package) that describe a FEATURE rather than being part of the
  actual name. "sınırsız dakika" (unlimited minutes) is a feature description, not a name --
  search ILIKE '%sinirsiz%' alone, don't search for '%sinirsiz dakika%'. If a feature question
  has no matching name keyword at all, filter on the actual numeric column instead (e.g.
  ORDER BY voice_minutes DESC for "which package has the most minutes").
- IMPORTANT: period_month exists ONLY on invoices and usage_records -- never on customers or
  subscriptions. subscriptions.start_date is a DIFFERENT concept (when the plan began) and must
  NEVER be used as a substitute for period_month. When asked about a customer's "period day"
  (e.g. "periyodu ayın 25i olan müşteriler" = customers whose period day is the 25th), filter
  EXTRACT(DAY FROM period_month) = <day> on invoices (join customer_id directly) or
  usage_records (join through subscriptions to reach customer_id).
- IMPORTANT: invoices has ONLY customer_id as a foreign key -- there is NO invoices.subscription_id
  column and invoices are never joined directly to packages or subscriptions. If a question needs
  both invoice data and package/subscription data for the same customer, join invoices and
  subscriptions separately, both through customer_id -- do not invent a subscription_id column
  on invoices.
- IMPORTANT: when using GROUP BY together with an aggregate function (COUNT, SUM, AVG, etc.),
  GROUP BY the table's primary key column (e.g. p.id), never a non-unique column like name.
  PostgreSQL allows selecting other ungrouped columns from that same row when grouped by its
  primary key, but grouping by anything else (like name) requires every other selected column
  to be aggregated too, or the query errors.

Examples:
Q: genc paketi kullanan müşterileri göster
A: SELECT c.* FROM customers c JOIN subscriptions s ON s.customer_id = c.id JOIN packages p ON p.id = s.package_id WHERE p.name ILIKE '%genc%';

Q: sınırsız konuşma paketi ne kadar
A: SELECT monthly_price FROM packages WHERE name ILIKE '%sinirsiz konusma%';

Q: en çok geliri olan paket hangisi (toplam abone sayısı x fiyat)?
A: SELECT p.name, COUNT(s.id) * p.monthly_price AS total_revenue FROM packages p JOIN subscriptions s ON s.package_id = p.id GROUP BY p.id ORDER BY total_revenue DESC LIMIT 1;

Q: hangi paketlerde sınırsız dakika var?
A: SELECT name FROM packages WHERE name ILIKE '%sinirsiz%';

Q: periyodu ayın 25i olan müşterileri göster
A: SELECT DISTINCT c.* FROM customers c JOIN invoices i ON i.customer_id = c.id WHERE EXTRACT(DAY FROM i.period_month) = 25;

Date handling (period_month and due_date are DATE columns; period_month's day-of-month is NOT always 1, it varies per customer):
- date_trunc('month', some_date) is a FUNCTION CALL, never a type or cast. NEVER write `x::date_trunc(...)`.
- IMPORTANT: only add a date/month filter when the question EXPLICITLY mentions a time period
  (e.g. "this month", "last month", "in July", "bu ay", "geçen ay"). If the question does not
  mention any time period, do NOT add a date_trunc filter at all -- match across all periods.
- "this month" / "bu ay" -> date_trunc('month', column) = date_trunc('month', CURRENT_DATE)
- "last month" / "geçen ay" -> date_trunc('month', column) = date_trunc('month', CURRENT_DATE - INTERVAL '1 month')
- "overdue" / "past due" -> due_date < CURRENT_DATE AND is_paid = FALSE
- For a NAMED month with no year given (e.g. "in July", "temmuz ayında"), NEVER compare
  date_trunc(...) to a string literal date -- this causes a "date_trunc(unknown, unknown) is
  not unique" error because untyped string literals are ambiguous. Instead use
  EXTRACT(MONTH FROM column) = <month_number>. Only filter by year too (EXTRACT(YEAR FROM
  column) = <year>) if a year is explicitly stated in the question.

Examples:
Q: which customers have not paid their invoice this month?
A: SELECT c.* FROM customers c JOIN invoices i ON i.customer_id = c.id WHERE i.is_paid = FALSE AND date_trunc('month', i.period_month) = date_trunc('month', CURRENT_DATE);

Q: which customers have not paid their invoices?
A: SELECT c.* FROM customers c JOIN invoices i ON i.customer_id = c.id WHERE i.is_paid = FALSE;

Q: how much internet did customers use last month?
A: SELECT s.customer_id, SUM(u.internet_used_mb) FROM usage_records u JOIN subscriptions s ON s.id = u.subscription_id WHERE date_trunc('month', u.period_month) = date_trunc('month', CURRENT_DATE - INTERVAL '1 month') GROUP BY s.customer_id;

Q: which customers used 120 SMS in July?
A: SELECT c.* FROM customers c JOIN subscriptions s ON s.customer_id = c.id JOIN usage_records u ON u.subscription_id = s.id WHERE u.sms_used = 120 AND EXTRACT(MONTH FROM u.period_month) = 7;

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


UNANSWERABLE_MESSAGE = (
    "Bu soruyu cevaplayamıyorum. Sadece müşteriler, paketler, abonelikler, "
    "kullanım ve faturalar hakkında sorular sorabilirsiniz."
)


def validate_sql(sql: str) -> None:
    stripped = sql.strip().rstrip(";")
    if stripped.strip().upper() == "UNRELATED":
        print(f"[nl2sql] Model flagged question as unrelated to the schema")
        raise ValueError(UNANSWERABLE_MESSAGE)
    if not re.match(r"^\s*SELECT\b", stripped, re.IGNORECASE):
        print(f"[nl2sql] Rejected non-SELECT query: {sql}")
        raise ValueError(UNANSWERABLE_MESSAGE)
    if ";" in stripped:
        print(f"[nl2sql] Rejected multi-statement query: {sql}")
        raise ValueError(UNANSWERABLE_MESSAGE)
    if FORBIDDEN_KEYWORDS.search(stripped):
        print(f"[nl2sql] Rejected query containing forbidden keyword: {sql}")
        raise ValueError(UNANSWERABLE_MESSAGE)


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
