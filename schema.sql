-- Telecom project schema

CREATE TABLE customers (
    id            SERIAL PRIMARY KEY,
    first_name    TEXT NOT NULL,
    last_name     TEXT NOT NULL,
    phone_number  TEXT NOT NULL UNIQUE,
    national_id   TEXT NOT NULL UNIQUE,
    city          TEXT NOT NULL,
    signup_date   DATE NOT NULL DEFAULT CURRENT_DATE,
    line_type     TEXT NOT NULL CHECK (line_type IN ('prepaid', 'postpaid')),
    status        TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended', 'cancelled'))
);

CREATE TABLE packages (
    id             SERIAL PRIMARY KEY,
    name           TEXT NOT NULL,
    category       TEXT NOT NULL CHECK (category IN ('mobile', 'combo')),
    internet_gb    INTEGER NOT NULL DEFAULT 0,
    sms_count      INTEGER NOT NULL DEFAULT 0,
    voice_minutes  INTEGER NOT NULL DEFAULT 0,
    monthly_price  NUMERIC(10, 2) NOT NULL,
    is_active      BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE subscriptions (
    id           SERIAL PRIMARY KEY,
    customer_id  INTEGER NOT NULL REFERENCES customers(id),
    package_id   INTEGER NOT NULL REFERENCES packages(id),
    start_date   DATE NOT NULL,
    end_date     DATE,
    status       TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'cancelled'))
);

CREATE TABLE usage_records (
    id                 SERIAL PRIMARY KEY,
    subscription_id    INTEGER NOT NULL REFERENCES subscriptions(id),
    period_month       DATE NOT NULL,
    internet_used_mb   INTEGER NOT NULL DEFAULT 0,
    sms_used           INTEGER NOT NULL DEFAULT 0,
    minutes_used       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE invoices (
    id            SERIAL PRIMARY KEY,
    customer_id   INTEGER NOT NULL REFERENCES customers(id),
    period_month  DATE NOT NULL,
    amount        NUMERIC(10, 2) NOT NULL,
    is_paid       BOOLEAN NOT NULL DEFAULT FALSE,
    due_date      DATE NOT NULL
);
