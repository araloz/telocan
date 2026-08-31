-- Telecom project schema

CREATE TABLE customers (
    id            SERIAL PRIMARY KEY,
    first_name    TEXT NOT NULL,
    last_name     TEXT NOT NULL,
    phone_number  TEXT NOT NULL UNIQUE,
    national_id   TEXT NOT NULL UNIQUE,
    city          TEXT NOT NULL,
    signup_date   DATE NOT NULL DEFAULT CURRENT_DATE,
    status        TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended', 'cancelled'))
);

CREATE TABLE packages (
    id             SERIAL PRIMARY KEY,
    name           TEXT NOT NULL,
    category       TEXT NOT NULL CHECK (category IN ('mobile', 'combo', 'addon')),
    line_type      TEXT NOT NULL DEFAULT 'both' CHECK (line_type IN ('prepaid', 'postpaid', 'both')),
    internet_gb    INTEGER NOT NULL DEFAULT 0,
    sms_count      INTEGER NOT NULL DEFAULT 0,
    voice_minutes  INTEGER NOT NULL DEFAULT 0,
    monthly_price  NUMERIC(10, 2) NOT NULL, -- for is_recurring = FALSE rows, this is a one-time price, not monthly
    is_active      BOOLEAN NOT NULL DEFAULT TRUE,
    is_recurring   BOOLEAN NOT NULL DEFAULT TRUE -- FALSE = one-time add-on (e.g. "Ekstra 1 GB"), not a recurring plan
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

-- App users (people who log into the Telocan web app itself -- separate from `customers`,
-- which represents telecom customers in the simulated dataset).
CREATE TABLE users (
    id            SERIAL PRIMARY KEY,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    first_name    TEXT NOT NULL DEFAULT '',
    last_name     TEXT NOT NULL DEFAULT '',
    is_admin      BOOLEAN NOT NULL DEFAULT FALSE,
    created_at    TIMESTAMP NOT NULL DEFAULT NOW()
);

-- One row per chat session, owned by a user.
CREATE TABLE conversations (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    created_at  TIMESTAMP NOT NULL DEFAULT NOW()
);

-- One row per question/answer pair within a conversation.
CREATE TABLE chat_messages (
    id               SERIAL PRIMARY KEY,
    conversation_id  INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    question         TEXT NOT NULL,
    sql_query        TEXT,
    result_rows      JSONB,
    created_at       TIMESTAMP NOT NULL DEFAULT NOW()
);

-- User-submitted reports flagging a bad answer. Stores a snapshot of the question/SQL/rows so
-- the report survives even if the underlying conversation is later deleted.
CREATE TABLE reports (
    id            SERIAL PRIMARY KEY,
    user_id       INTEGER NOT NULL REFERENCES users(id),
    question      TEXT NOT NULL,
    sql_query     TEXT,
    result_rows   JSONB,
    is_fixed      BOOLEAN NOT NULL DEFAULT FALSE,
    created_at    TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Every question asked, successful or not -- for spotting failure patterns proactively,
-- separate from user-submitted reports (which only capture what someone bothered to flag).
CREATE TABLE query_log (
    id            SERIAL PRIMARY KEY,
    user_id       INTEGER NOT NULL REFERENCES users(id),
    question      TEXT NOT NULL,
    sql_query     TEXT,
    success       BOOLEAN NOT NULL,
    error_message TEXT,
    created_at    TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Single-use, time-limited tokens for the "forgot password" email flow.
CREATE TABLE password_resets (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    token       TEXT NOT NULL UNIQUE,
    expires_at  TIMESTAMP NOT NULL,
    used        BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMP NOT NULL DEFAULT NOW()
);
