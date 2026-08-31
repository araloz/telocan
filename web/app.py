import os
import sys

from flask import Flask, jsonify, render_template, request, session, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import json
import psycopg2.extras
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

def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        if not session.get("is_admin"):
            return redirect(url_for("index"))
        return view(*args, **kwargs)

    return wrapped



@app.route("/conversations", methods=["GET", "POST"])
@login_required
def conversations():
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            if request.method == "POST":
                cur.execute(
                    "INSERT INTO conversations (user_id) VALUES (%s) RETURNING id, created_at",
                    (session["user_id"],),
                )
                conv_id, created_at = cur.fetchone()
                conn.commit()
                return jsonify({"id": conv_id, "created_at": created_at.isoformat()})

            cur.execute(
            "SELECT id, created_at FROM conversations WHERE user_id = %s ORDER BY created_at DESC",
            (session["user_id"],),
        )
            rows = cur.fetchall()
            return jsonify([{"id":r[0], "created_at": r[1].isoformat()} for r in rows])
    finally:
        conn.close()


@app.route("/conversations/<int:conv_id>/messages")
@login_required
def conversation_messages(conv_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id FROM conversations WHERE id = %s", (conv_id,))
            owner = cur.fetchone()
            if not owner or owner[0] != session["user_id"]:
                return jsonify({"error":"not found"}),404

            cur.execute("SELECT question, sql_query, result_rows, created_at FROM chat_messages "
                "WHERE conversation_id = %s ORDER BY created_at ASC", (conv_id,),
            )
            rows = cur.fetchall()
            return jsonify([
                {"question": r[0], "sql": r[1], "rows": r[2], "created_at": r[3].isoformat()} 
                for r in rows
            ])
    finally:
        conn.close()


@app.route("/conversations/<int:conv_id>", methods=["DELETE"])
@login_required
def delete_conversation(conv_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute( "DELETE FROM conversations WHERE id = %s AND user_id = %s",
                (conv_id, session["user_id"]),
            )
            deleted = cur.rowcount
            conn.commit()
        if deleted == 0:
            return jsonify({"error":"not found"}),404
        return jsonify({"ok": True})
    finally:
        conn.close()


@app.route("/logout")
def logout():
    session.pop("user_id", None)
    return redirect(url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        first_name = request.form.get("first_name", "").strip()
        last_name = request.form.get("last_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not first_name or not last_name or not email or not password:
            return render_template("register.html", error="Tüm alanlar zorunludur.")

        hashed_password = generate_password_hash(password)

        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                try:
                    cur.execute(
                        "INSERT INTO users (email, password_hash, first_name, last_name) VALUES (%s, %s, %s, %s)",
                        (email, hashed_password, first_name, last_name),
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
                cur.execute("SELECT id, password_hash, first_name, is_admin FROM users WHERE email = %s", (email,))
                row = cur.fetchone()

        finally:
            conn.close()

        if row and check_password_hash(row[1], password):
            session["user_id"] = row[0]
            session["first_name"] = row[2]
            session["is_admin"] = row[3]
            return redirect(url_for("index"))

        return render_template("login.html", error="Geçersiz e-posta veya şifre.")

    return render_template("login.html", error=None)


@app.route("/")
@login_required
def index():
    return render_template("index.html", first_name=session.get("first_name", ""), is_admin=session.get("is_admin", False))



@app.route("/chat", methods=["POST"])
@login_required
def chat():
    data = request.get_json(silent=True) or {}
    question = (data.get("question") or "").strip()
    conversation_id = data.get("conversation_id")
    if not question:
        return jsonify({"error": "Soru gerekli."}), 400

    try:
        result = ask_database(question)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            if not conversation_id:
                cur.execute(
                    "INSERT INTO conversations (user_id) VALUES (%s) RETURNING id",
                    (session["user_id"],),
                )
                conversation_id = cur.fetchone()[0]

            cur.execute(
                "INSERT INTO chat_messages (conversation_id, question, sql_query, result_rows) "
                "VALUES (%s, %s, %s, %s)",
                (conversation_id, result["question"], result["sql"], psycopg2.extras.Json(result["rows"], dumps=lambda obj: json.dumps(obj, default=str))),
            )
            conn.commit()
    finally:
        conn.close()

    result["conversation_id"] = conversation_id
    return jsonify(result)


@app.route("/reports", methods=["POST"])
@login_required
def submit_report():
    data = request.get_json(silent=True) or {}
    question = (data.get("question") or "").strip()
    sql = data.get("sql")
    rows = data.get("rows")

    if not question:
        return jsonify({"error": "Soru gerekli."}), 400

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO reports (user_id, question, sql_query, result_rows) VALUES (%s, %s, %s, %s)",
                (session["user_id"], question, sql, psycopg2.extras.Json(rows, dumps=lambda obj: json.dumps(obj, default=str))),
            )
            conn.commit()

    finally:
        conn.close()

    return jsonify({"ok": True})


@app.route("/admin")
@admin_required
def admin_panel():
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT r.id, u.email, u.first_name, u.last_name, r.question, r.sql_query, r.result_rows, r.created_at, r.is_fixed
                FROM reports r
                JOIN users u ON u.id = r.user_id
                ORDER BY r.created_at DESC
            """)
            rows = cur.fetchall()
    finally:
        conn.close()

    reports = [
        {
            "id": r[0],
            "email": r[1],
            "first_name": r[2],
            "last_name": r[3],
            "question": r[4],
            "sql": r[5],
            "rows": r[6],
            "created_at": r[7],
            "is_fixed": r[8],
        }
        for r in rows
    ]

    return render_template("admin.html", reports=reports)


@app.route("/reports/<int:report_id>/fix", methods=["POST"])
@admin_required
def mark_report_fixed(report_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE reports SET is_fixed = TRUE WHERE id = %s",
                        (report_id,))
            updated = cur.rowcount
            conn.commit()

    finally:
        conn.close()

    if updated == 0:
        return jsonify({"error": "Rapor bulunamadı"}), 404
    return jsonify({"ok":True})


@app.route("/admin/users")
@admin_required
def admin_search_users():
    query = request.args.get("q", "").strip()
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, email, first_name, last_name, is_admin FROM users WHERE email ILIKE %s ORDER BY email",
                (f"%{query}%",),
            )
            rows = cur.fetchall()

    finally:
        conn.close()

    users = [
         {"id": r[0], "email": r[1], "first_name": r[2], "last_name": r[3], "is_admin": r[4]}
        for r in rows
    ]
    return jsonify(users)


@app.route("/admin/users/<int:user_id>/make-admin", methods=["POST"])
@admin_required
def make_admin(user_id):
    conn =get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET is_admin = TRUE WHERE id = %s", (user_id,))
            updated = cur.rowcount
            conn.commit()
    finally:
        conn.close()

    if updated == 0:
        return jsonify({"error":"Kullanıcı bulunamadı."}),404
    return jsonify({"ok":True})


@app.route("/admin/users/<int:user_id>/revoke-admin", methods=["POST"])
@admin_required
def revoke_admin(user_id):
    if user_id == session["user_id"]:
        return jsonify({"error":"Kendi yetkinizi kaldıramazsınız"}), 400

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET is_admin = FALSE WHERE id = %s", (user_id,))
            updated = cur.rowcount
            conn.commit()

    finally:
        conn.close()

    if updated == 0:
        return jsonify({"error": "Kullanıcı bulunamadı."}), 404

    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
