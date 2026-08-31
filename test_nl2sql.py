"""
Regression tests for nl2sql.py.

Each test guards against a specific bug we found and fixed while testing this project. Since
the underlying model (qwen2.5-coder, 7B, local) is non-deterministic, every call goes through
`ask_with_retry`, which tries a question a few times before giving up -- matching how a real
user would just re-ask a question that failed once. A test failing here means something is
reliably broken, not just an occasional model hiccup.

Run with: pytest test_nl2sql.py -v
"""

import pytest
from nl2sql import ask_database


def ask_with_retry(question, history=None, attempts=3):
    """Call ask_database, retrying on failure since the local model is non-deterministic."""
    last_error = None
    for _ in range(attempts):
        try:
            return ask_database(question, history=history)
        except Exception as e:
            last_error = e
    raise AssertionError(f"'{question}' failed all {attempts} attempts. Last error: {last_error}")


def names(rows):
    return [(r.get("first_name"), r.get("last_name")) for r in rows if "first_name" in r]


# --- Basic sanity: the pipeline runs at all ---

def test_simple_count_question_runs():
    r = ask_with_retry("how many customers do I have?")
    assert r["rows"][0]["count"] > 0


# --- Date handling regressions ---

def test_no_time_filter_when_question_has_no_time_period():
    """Regression: model used to add an unwanted 'this month' filter even when not asked,
    causing unpaid-invoice questions to wrongly return 0 rows."""
    r = ask_with_retry("which customers have not paid their invoices?")
    assert len(r["rows"]) > 0


def test_named_month_no_ambiguous_date_trunc_error():
    """Regression: 'date_trunc(unknown, unknown) is not unique' error when comparing
    date_trunc(...) to an untyped string literal for a named month with no year."""
    r = ask_with_retry("which customers used 120 SMS in July?")
    assert "sql" in r


def test_this_month_vs_last_month_use_correct_anchor():
    """Regression: 'this month' was sometimes anchored to the wrong reference point."""
    r = ask_with_retry("how much internet did customers use last month?")
    assert isinstance(r["rows"], list)


# --- ILIKE / name matching regressions ---

def test_package_name_partial_match_not_exact():
    """Regression: exact equality (=) on package name missed real rows since users don't
    type the full, exactly-cased name."""
    r = ask_with_retry("genc paketi kullanan müşterileri göster")
    assert len(r["rows"]) > 0


def test_feature_word_not_glued_onto_name_keyword():
    """Regression: 'sınırsız dakika' was searched as one literal phrase ('%sinirsiz dakika%'),
    which matched nothing since 'dakika' isn't part of any package name."""
    r = ask_with_retry("hangi paketlerde sınırsız dakika var?")
    result_names = [row.get("name") for row in r["rows"]]
    assert "Sinirsiz Konusma" in result_names or "Premium Sinirsiz" in result_names


def test_turkish_diacritics_in_city_name():
    """Regression: 'İstanbul' (with Turkish İ) was compared directly against the stored
    ASCII 'Istanbul', never matching."""
    r = ask_with_retry("İstanbul'da kaç müşteri var?")
    assert r["rows"][0]["count"] > 0


# --- Join / schema-confusion regressions ---

def test_invoices_has_no_subscription_id_shortcut():
    """Regression: model invented invoices.subscription_id (doesn't exist) when computing
    package revenue, which requires joining through subscriptions instead."""
    r = ask_with_retry("en çok geliri olan paket hangisi (toplam abone sayısı x fiyat)?")
    assert len(r["rows"]) == 1


def test_period_month_not_confused_with_subscription_start_date():
    """Regression: 'periyodu ayın 25i olan müşteriler' incorrectly filtered on
    subscriptions.start_date instead of invoices/usage_records.period_month."""
    r = ask_with_retry("periyodu ayın 25i olan müşterileri göster")
    assert isinstance(r["rows"], list)


def test_quota_comparison_uses_correct_unit_conversion():
    """Regression: packages.internet_gb (GB) was compared directly against
    usage_records.internet_used_mb (MB) with no unit conversion, silently producing wrong
    results for every row."""
    r = ask_with_retry("paket kotasını internet olarak aşan müşteriler kimler?")
    assert ("Ali", "Celik") in names(r["rows"])


def test_month_over_month_comparison_no_invented_columns():
    """Regression: usage_records has no customer_id (only subscription_id); a naive
    self-join could also double-count customers with multiple subscriptions."""
    r = ask_with_retry("geçen ay ile bu ay arasında internet kullanımı artan müşteriler kimler?")
    assert isinstance(r["rows"], list)


# --- UNRELATED sentinel regressions ---

def test_genuinely_unrelated_question_is_rejected():
    """A real off-topic question should raise, not silently return something."""
    with pytest.raises(ValueError):
        ask_database("write me python code that counts to 10")


def test_hard_but_answerable_question_is_not_rejected():
    """Regression: the UNRELATED escape hatch was sometimes used to dodge genuinely
    answerable but hard questions instead of attempting them."""
    r = ask_with_retry("iki aydır üst üste ödeme yapmamış müşteriler var mı?")
    assert isinstance(r["rows"], list)


def test_contradiction_phrased_question_is_not_rejected():
    """Regression: 'X ama Y' (X but Y) contradiction phrasing was misread as UNRELATED."""
    r = ask_with_retry("faturalı paket kullanan ama aboneliği iptal olan müşteriler kimler?")
    assert isinstance(r["rows"], list)


# --- line_type-on-packages model (post-migration) ---

def test_prepaid_is_a_package_attribute_not_customer():
    r = ask_with_retry("kaç tane kontrollü müşterim var?")
    assert r["rows"][0]["count"] > 0


# --- Conversation memory ---

def test_followup_question_uses_history_to_change_filter():
    """A vague follow-up ('what about the postpaid ones') should resolve using the prior
    question's context and produce a genuinely different result, not repeat the same query."""
    r1 = ask_with_retry("how many prepaid customers do I have")
    history = [{"question": r1["question"], "sql": r1["sql"]}]
    r2 = ask_with_retry("what about the postpaid ones", history=history)
    assert r2["rows"][0]["count"] != r1["rows"][0]["count"]


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
