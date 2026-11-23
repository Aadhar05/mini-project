from datetime import datetime, timedelta
from contextlib import contextmanager
import os
import secrets
import sqlite3
from pathlib import Path

from flask import Flask, abort, flash, redirect, render_template, request, session, url_for


BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"
DATABASE = INSTANCE_DIR / "appointments.db"

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)
app.config.update(
    TEACHER_PASSWORD=os.environ.get("TEACHER_PASSWORD", ""),
    SESSION_COOKIE_SAMESITE="Lax",
)


@app.context_processor
def form_security():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return {"csrf_token": session["csrf_token"]}


@app.before_request
def verify_form_token():
    if request.method == "POST":
        expected = session.get("csrf_token")
        submitted = request.form.get("csrf_token", "")
        if not expected or not secrets.compare_digest(expected.encode(), submitted.encode()):
            abort(400, "Reload the page and submit the form again.")


@contextmanager
def get_db_connection():
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database():
    DATABASE.parent.mkdir(parents=True, exist_ok=True)
    with get_db_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """CREATE TABLE IF NOT EXISTS appointments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                appointment_date TEXT NOT NULL,
                notes TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                revision INTEGER NOT NULL DEFAULT 0
            )"""
        )
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(appointments)")}
        if "revision" not in columns:
            connection.execute("ALTER TABLE appointments ADD COLUMN revision INTEGER NOT NULL DEFAULT 0")
        connection.execute("UPDATE appointments SET status = 'pending' WHERE status = 'booked'")


def read_form_date(value):
    return datetime.strptime(value, "%Y-%m-%dT%H:%M")


@app.route("/")
def index():
    now = datetime.now()
    reminder_end = now + timedelta(hours=24)
    with get_db_connection() as connection:
        appointments = connection.execute(
            "SELECT * FROM appointments WHERE status IN ('pending', 'approved') ORDER BY appointment_date"
        ).fetchall()
    upcoming_reminders = [
        item for item in appointments
        if item["status"] == "approved"
        and now <= datetime.fromisoformat(item["appointment_date"]) <= reminder_end
    ]
    return render_template(
        "index.html", appointments=appointments, reminders=upcoming_reminders
    )


@app.route("/add", methods=["GET", "POST"])
def add_appointment():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        date_text = request.form.get("appointment_date", "")
        notes = request.form.get("notes", "").strip()
        try:
            appointment_date = read_form_date(date_text)
        except ValueError:
            flash("Please choose a valid date and time.", "error")
            return render_template("appointment_form.html", appointment=None)
        if not title:
            flash("Please enter an appointment title.", "error")
            return render_template("appointment_form.html", appointment=None)
        with get_db_connection() as connection:
            connection.execute(
                "INSERT INTO appointments (title, appointment_date, notes, status) VALUES (?, ?, ?, 'pending')",
                (title, appointment_date.isoformat(timespec="minutes"), notes),
            )
        flash("Request submitted. It is pending teacher approval.", "success")
        return redirect(url_for("index"))
    return render_template("appointment_form.html", appointment=None)


@app.route("/edit/<int:appointment_id>", methods=["GET", "POST"])
def edit_appointment(appointment_id):
    with get_db_connection() as connection:
        if request.method == "POST":
            connection.execute("BEGIN IMMEDIATE")
        appointment = connection.execute(
            "SELECT * FROM appointments WHERE id = ? AND status IN ('pending', 'approved')",
            (appointment_id,),
        ).fetchone()
        if appointment is None:
            flash("That active appointment was not found.", "error")
            return redirect(url_for("index"))
        if request.method == "POST":
            title = request.form.get("title", "").strip()
            date_text = request.form.get("appointment_date", "")
            notes = request.form.get("notes", "").strip()
            try:
                appointment_date = read_form_date(date_text)
            except ValueError:
                flash("Please choose a valid date and time.", "error")
                return render_template("appointment_form.html", appointment=appointment)
            if not title:
                flash("Please enter an appointment title.", "error")
                return render_template("appointment_form.html", appointment=appointment)
            values = (title, appointment_date.isoformat(timespec="minutes"), notes)
            current = (appointment["title"], appointment["appointment_date"], appointment["notes"] or "")
            if values != current:
                connection.execute(
                    """UPDATE appointments
                       SET title = ?, appointment_date = ?, notes = ?, status = 'pending', revision = revision + 1
                       WHERE id = ?""",
                    (*values, appointment_id),
                )
                flash("Request updated and pending teacher approval.", "success")
            else:
                flash("No changes to save.", "success")
            return redirect(url_for("index"))
    return render_template("appointment_form.html", appointment=appointment)


@app.route("/cancel/<int:appointment_id>", methods=["POST"])
def cancel_appointment(appointment_id):
    with get_db_connection() as connection:
        updated = connection.execute(
            "UPDATE appointments SET status = 'cancelled' WHERE id = ? AND status IN ('pending', 'approved')",
            (appointment_id,),
        )
    if updated.rowcount:
        flash("Appointment cancelled.", "success")
    else:
        flash("That active appointment was not found.", "error")
    return redirect(url_for("index"))


@app.route("/teacher", methods=["GET", "POST"])
def teacher_dashboard():
    configured_password = app.config["TEACHER_PASSWORD"]
    if request.method == "POST":
        password = request.form.get("password", "")
        if configured_password and secrets.compare_digest(configured_password.encode(), password.encode()):
            session.clear()
            session["teacher"] = True
            return redirect(url_for("teacher_dashboard"))
        flash("Teacher password is incorrect.", "error")

    signed_in = bool(configured_password and session.get("teacher"))
    pending_requests = []
    if signed_in:
        with get_db_connection() as connection:
            pending_requests = connection.execute(
                "SELECT * FROM appointments WHERE status = 'pending' ORDER BY appointment_date, id"
            ).fetchall()
    return render_template(
        "teacher.html", signed_in=signed_in, configured=bool(configured_password), appointments=pending_requests,
    )


@app.post("/teacher/approve/<int:appointment_id>")
def approve_appointment(appointment_id):
    if not app.config["TEACHER_PASSWORD"] or not session.get("teacher"):
        abort(403)
    revision = request.form.get("revision", type=int)
    if revision is None:
        abort(400)
    with get_db_connection() as connection:
        updated = connection.execute(
            "UPDATE appointments SET status = 'approved' WHERE id = ? AND status = 'pending' AND revision = ?",
            (appointment_id, revision),
        )
    if updated.rowcount:
        flash("Appointment approved.", "success")
    else:
        flash("This request changed or is no longer pending. Review the current list before approving.", "error")
    return redirect(url_for("teacher_dashboard"))


@app.post("/teacher/logout")
def teacher_logout():
    session.clear()
    return redirect(url_for("teacher_dashboard"))


initialize_database()


if __name__ == "__main__":
    app.run()
