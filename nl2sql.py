import os
import re
import json
import time
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
customers(id, first_name, last_name, phone_number, national_id, city, signup_date, status)
  - status: 'active', 'suspended', 'cancelled'
  - customers do NOT have a line_type / prepaid-postpaid attribute -- that lives on packages (see below).
packages(id, name, category, line_type, internet_gb, sms_count, voice_minutes, monthly_price, is_active, is_recurring)
  - category: 'mobile' (voice/SMS only, internet_gb is always 0), 'combo' (bundled voice+SMS+internet),
    'addon' (one-time top-up, see is_recurring below). Phone packages only, no home internet.
  - line_type: 'prepaid' (Turkish: kontrollu), 'postpaid' (Turkish: faturali), or 'both' (works for
    either kind of line). This is a PACKAGE attribute, not a customer attribute -- a customer's
    "prepaid/postpaid" status is really about which package(s) they're subscribed to.
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
- CRITICAL: UNRELATED is ONLY for questions that have nothing to do with customers, packages,
  subscriptions, usage, or invoices. NEVER output UNRELATED just because a question is difficult,
  requires multiple joins/subqueries, or takes real effort to translate -- a hard-but-in-domain
  question (e.g. comparing data across multiple time periods, multi-step aggregations) must
  always get a genuine SQL attempt. Giving up on a hard question is a worse failure than writing
  an imperfect query.
- Otherwise, output ONLY a single valid PostgreSQL SELECT statement. No explanation, no markdown fences.
- Never generate INSERT, UPDATE, DELETE, DROP, or any statement that modifies data.
- Map user terms: "kontrollu"/"prepaid" -> packages.line_type IN ('prepaid', 'both'); "faturali"/"postpaid"
  -> packages.line_type IN ('postpaid', 'both'). 'both' packages count as matching EITHER type, since
  they support both. line_type is ALWAYS on packages, never on customers -- to find "prepaid customers"
  or "faturalı müşteriler", you MUST join customers -> subscriptions -> packages and filter on
  packages.line_type; there is no shortcut column on customers.
- Always join through subscriptions when a question spans customers and packages/usage.
- If the question is ambiguous, make the most reasonable assumption and just generate the query.
- When filtering by a package name or any other free-text name the user refers to informally
  (e.g. "genc paketi" for "Genc Paketi"), NEVER use exact equality (=). Use a case-insensitive
  partial match instead: column ILIKE '%keyword%'. Exact equality will miss real rows because
  users rarely type the full, exactly-cased name stored in the database.
- IMPORTANT: ALL text stored in the database (package names, city names, everything) uses PLAIN
  ASCII ONLY -- Turkish diacritics are never stored. This applies to city too, e.g. "İstanbul" is
  stored as "Istanbul" (plain ASCII I). Before building any string comparison from a Turkish
  question -- whether ILIKE or =  -- convert Turkish characters to plain ASCII equivalents:
  ı/İ->i/I, ş/Ş->s/S, ğ/Ğ->g/G, ü/Ü->u/U, ö/Ö->o/O, ç/Ç->c/C. E.g. "sınırsız konuşma" ->
  "sinirsiz konusma", "İstanbul" -> "Istanbul". Never put diacritics inside a comparison -- they
  will never match. For city, use = with the converted ASCII value (city names are stored exactly,
  no partial matching needed) -- ILIKE is only needed for package names where users type informally.
- IMPORTANT: only JOIN a table if the question actually needs a column from it. Do not join
  subscriptions/packages unless you need package/subscription-specific data -- customers.status
  and customers.city are on the customers table directly and never require joining anything else.
  An unnecessary join is a common source of referencing a column on the wrong table alias.
  line_type, however, DOES require joining subscriptions AND packages (it's a packages column,
  not customers) -- never write c.line_type or s.line_type, always p.line_type.
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
- IMPORTANT: when comparing a customer's usage against their package's quota (e.g. "kotasını
  aşan" / exceeded their quota), ALWAYS JOIN packages into the FROM/JOIN clauses directly
  (packages p ON p.id = s.package_id) -- never reference p.<column> without an actual join
  present, and never leave it inside a correlated subquery when a direct join works just as well.
- CRITICAL unit conversion: packages.internet_gb is in GIGABYTES, but usage_records.internet_used_mb
  is in MEGABYTES. NEVER compare them directly -- always convert: multiply internet_gb by 1024
  to get megabytes before comparing to internet_used_mb (e.g. u.internet_used_mb > p.internet_gb * 1024).
  Forgetting this conversion silently produces wrong results for every row, since MB values are
  numerically much larger than GB values even when the actual usage is well under quota.
- IMPORTANT: usage_records has NO customer_id column -- only subscription_id. Always route
  through subscriptions (JOIN subscriptions s ON s.id = u.subscription_id) to reach a customer,
  never invent u.customer_id.
- IMPORTANT: for period-over-period comparisons per customer (e.g. "geçen ay ile bu ay arasında
  artan/azalan", comparing two months/periods), do NOT self-join raw usage_records rows directly
  -- a customer can have multiple subscriptions (a recurring plan plus add-ons), so raw rows can
  multiply or compare the wrong subscription's numbers against another. Instead, aggregate each
  period into its own subquery first (GROUP BY customer_id, SUM the metric per period), then
  join the two aggregated subqueries together and compare the totals.

Examples:
Q: kaç tane kontrollü müşterim var?
A: SELECT COUNT(DISTINCT c.id) FROM customers c JOIN subscriptions s ON s.customer_id = c.id JOIN packages p ON p.id = s.package_id WHERE p.line_type IN ('prepaid', 'both');

Q: genc paketi kullanan müşterileri göster
A: SELECT c.* FROM customers c JOIN subscriptions s ON s.customer_id = c.id JOIN packages p ON p.id = s.package_id WHERE p.name ILIKE '%genc%';

Q: sınırsız konuşma paketi ne kadar
A: SELECT monthly_price FROM packages WHERE name ILIKE '%sinirsiz konusma%';

Q: en çok geliri olan paket hangisi (toplam abone sayısı x fiyat)?
A: SELECT p.name, COUNT(s.id) * p.monthly_price AS total_revenue FROM packages p JOIN subscriptions s ON s.package_id = p.id GROUP BY p.id ORDER BY total_revenue DESC LIMIT 1;

Q: hangi paketlerde sınırsız dakika var?
A: SELECT name FROM packages WHERE name ILIKE '%sinirsiz%';

Q: paket kotasını internet olarak aşan müşteriler kimler?
A: SELECT DISTINCT c.* FROM customers c JOIN subscriptions s ON s.customer_id = c.id JOIN packages p ON p.id = s.package_id JOIN usage_records u ON u.subscription_id = s.id WHERE u.internet_used_mb > p.internet_gb * 1024;

Q: geçen ay ile bu ay arasında internet kullanımı artan müşteriler kimler?
A: SELECT c.* FROM customers c
JOIN (SELECT s.customer_id, SUM(u.internet_used_mb) AS mb FROM usage_records u JOIN subscriptions s ON s.id = u.subscription_id WHERE date_trunc('month', u.period_month) = date_trunc('month', CURRENT_DATE - INTERVAL '1 month') GROUP BY s.customer_id) last_month ON last_month.customer_id = c.id
JOIN (SELECT s.customer_id, SUM(u.internet_used_mb) AS mb FROM usage_records u JOIN subscriptions s ON s.id = u.subscription_id WHERE date_trunc('month', u.period_month) = date_trunc('month', CURRENT_DATE) GROUP BY s.customer_id) this_month ON this_month.customer_id = c.id
WHERE this_month.mb > last_month.mb;

Q: iki aydır üst üste ödeme yapmamış müşteriler var mı?
A: SELECT c.* FROM customers c
WHERE EXISTS (SELECT 1 FROM invoices i WHERE i.customer_id = c.id AND i.is_paid = FALSE AND date_trunc('month', i.period_month) = date_trunc('month', CURRENT_DATE))
AND EXISTS (SELECT 1 FROM invoices i WHERE i.customer_id = c.id AND i.is_paid = FALSE AND date_trunc('month', i.period_month) = date_trunc('month', CURRENT_DATE - INTERVAL '1 month'));
-- Note: anchor "N consecutive months" to CURRENT_DATE and count backwards from there (this
-- month, last month, ...) -- NOT to some arbitrary earlier month -- since the current month's
-- data already exists in this dataset even though the month isn't over.

Q: faturalı paket kullanan ama aboneliği iptal olan müşteriler kimler?
A: SELECT DISTINCT c.* FROM customers c JOIN subscriptions s ON s.customer_id = c.id JOIN packages p ON p.id = s.package_id WHERE p.line_type IN ('postpaid', 'both') AND s.status = 'cancelled';
-- Note: a question phrased as a contradiction/exception ("X ama Y" / "X but Y") is still just a
-- normal multi-condition filter across multiple tables -- it is NOT unrelated or unanswerable
-- just because the combination sounds unusual. line_type is on packages, status is on subscriptions.

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

Follow-up questions: if recent conversation history is provided below, use it ONLY to resolve
what an implicit/incomplete follow-up question refers to (e.g. "peki faturalı olanlar?", "ya
geçen ay?", "onlar kaç kişi?"). Always generate a fresh, complete, self-contained SQL query for
the CURRENT question -- never just repeat a previous query verbatim unless it is genuinely
identical to what's being asked now. If the current question is already complete and
self-contained on its own, ignore the history entirely.
{history}
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


def _format_history(history: list[dict] | None) -> str:
    if not history:
        return ""
    lines = ["Recent conversation history (for understanding follow-up questions):"]
    for h in history:
        lines.append(f"Q: {h['question']}")
        lines.append(f"SQL: {h['sql']}")
    return "\n".join(lines) + "\n"


def generate_sql(question: str, history: list[dict] | None = None) -> str:
    prompt = SYSTEM_PROMPT.format(question=question, history=_format_history(history))
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


def ask_database(question: str, history: list[dict] | None = None) -> dict:
    llm_start = time.monotonic()
    sql = generate_sql(question, history)
    llm_ms = round((time.monotonic() - llm_start) * 1000)

    validate_sql(sql)

    db_start = time.monotonic()
    rows = run_query(sql)
    db_ms = round((time.monotonic() - db_start) * 1000)

    return {
        "question": question,
        "sql": sql,
        "rows": rows,
        "timing": {"llm_ms": llm_ms, "db_ms": db_ms, "total_ms": llm_ms + db_ms},
    }


EXPLAIN_PROMPT = """Aşağıdaki SQL sorgusunu, SQL bilmeyen bir kullanıcıya Türkçe olarak, basit ve
kısa bir şekilde açıkla. Teknik SQL terimleri kullanma (JOIN, WHERE, GROUP BY gibi kelimelerden
kaçın) -- bunun yerine "hangi veriyi getirdiğini" günlük dilde anlat, 2-3 cümleyi geçme.

SQL:
{sql}

Açıklama:
"""


def explain_sql(sql: str) -> str:
    prompt = EXPLAIN_PROMPT.format(sql=sql)
    response = requests.post(
        f"{OLLAMA_URL}/api/generate",
        json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
        timeout=60,
    )
    response.raise_for_status()
    return response.json()["response"].strip()


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
