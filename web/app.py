import os
import sys

from flask import Flask, jsonify, render_template, request, session, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import psycopg2


# nl2sql.py lives one directory up from this file.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nl2sql import ask_database  # noqa: E402

app = Flask(__name__)
app.secret_key = os.environ["FLASK_SECRET_KEY"]  # Set this in your environment for session security


def get_db_connection():
    return psycopg2.connect(os.environ["DATABASE_URL"])  # Set this in your environment


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped


@app.route("/logout")
def logout():
    session.pop("user_id", None)
    return redirect(url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not email or not password:
            return render_template("register.html", error="E-posta ve şifre gerekli.")

        hashed_password = generate_password_hash(password)

        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                try:
                    cur.execute(
                        "INSERT INTO users (email, password_hash) VALUES (%s, %s)",
                        (email, hashed_password),
                    )
                    conn.commit()
                except psycopg2.IntegrityError:
                    conn.rollback()
                    return render_template("register.html", error="Bu e-posta zaten kayıtlı.")
        finally:
            conn.close()

        return redirect(url_for("login"))

    return render_template("register.html", error=None)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT id, password_hash FROM users WHERE email = %s", (email,))
                row = cur.fetchone()

        finally:
            conn.close()

        if row and check_password_hash(row[1], password):
            session["user_id"] = row[0]
            return redirect(url_for("index"))

        return render_template("login.html", error="Geçersiz e-posta veya şifre.")

    return render_template("login.html", error=None)


@app.route("/")
@login_required
def index():
    return render_template("index.html")


@app.route("/chat", methods=["POST"])
@login_required
def chat():
    data = request.get_json(silent=True) or {}
    question = (data.get("question") or "").strip()
    if not question:
        return jsonify({"error": "question is required"}), 400

    try:
        result = ask_database(question)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify(result)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
