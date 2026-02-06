import csv
import os
from urllib.parse import urlparse

import psycopg2
import psycopg2.extras
from flask import Flask, render_template, request, redirect, url_for, flash
from openpyxl import load_workbook


CSV_FILE = "students.csv"

EXCEL_ROOM_FILES = {
    "Neural": "Neural.xlsx",
    "Qubit": "Qubit.xlsx",
    "Quantum Core": "QuantumCore.xlsx",
    "Intelligence": "Intelligence.xlsx",
}

VALID_ROOMS = tuple(EXCEL_ROOM_FILES.keys())

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")


def get_db_connection():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL not set")

    result = urlparse(db_url)

    return psycopg2.connect(
        dbname=result.path[1:],
        user=result.username,
        password=result.password,
        host=result.hostname,
        port=result.port,
    )


def init_db():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS teams (
            id INTEGER PRIMARY KEY,
            team_name TEXT NOT NULL,
            room TEXT NOT NULL
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS students (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            team_id INTEGER NOT NULL REFERENCES teams(id),
            checked_in BOOLEAN NOT NULL DEFAULT FALSE,
            checkin_time TIMESTAMP,
            university TEXT
        );
    """)

    conn.commit()
    cur.close()
    conn.close()


def clean_cell(x):
    if x is None:
        return ""
    return str(x).strip()


def insert_team_if_needed(cur, team_id, team_name, room):
    cur.execute(
        """
        INSERT INTO teams (id, team_name, room)
        VALUES (%s, %s, %s)
        ON CONFLICT (id) DO NOTHING
        """,
        (team_id, team_name, room),
    )


def insert_student_if_needed(cur, student_name, team_id, university):
    cur.execute(
        """
        INSERT INTO students (name, team_id, university)
        SELECT %s, %s, %s
        WHERE NOT EXISTS (
            SELECT 1 FROM students WHERE name = %s AND team_id = %s
        )
        """,
        (student_name, team_id, university or None, student_name, team_id),
    )


def try_load_from_excels():
    conn = get_db_connection()
    cur = conn.cursor()
    any_file = False

    for room, path in EXCEL_ROOM_FILES.items():
        if not os.path.exists(path):
            continue

        any_file = True
        wb = load_workbook(path, data_only=True)

        for ws in wb.worksheets:
            for row in ws.iter_rows(values_only=True):
                if not row or row[0] is None:
                    continue

                try:
                    team_id = int(str(row[0]).strip())
                except ValueError:
                    continue

                name1 = clean_cell(row[1]) if len(row) > 1 else ""
                uni1 = clean_cell(row[2]) if len(row) > 2 else ""
                name2 = clean_cell(row[3]) if len(row) > 3 else ""
                uni2 = clean_cell(row[4]) if len(row) > 4 else ""

                team_name = clean_cell(row[5]) if len(row) > 5 else f"فريق {team_id}"

                insert_team_if_needed(cur, team_id, team_name, room)

                if name1:
                    insert_student_if_needed(cur, name1, team_id, uni1)
                if name2:
                    insert_student_if_needed(cur, name2, team_id, uni2)

    conn.commit()
    cur.close()
    conn.close()
    return any_file


def load_from_csv():
    conn = get_db_connection()
    cur = conn.cursor()

    with open(CSV_FILE, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            team_id = int(row["team_id"])
            team_name = row.get("team_name", "").strip() or f"فريق {team_id}"
            room = row.get("room", "").strip()
            if room not in VALID_ROOMS:
                room = "Neural"

            student_name = row.get("student_name", "").strip()
            university = row.get("university", "").strip()

            insert_team_if_needed(cur, team_id, team_name, room)
            if student_name:
                insert_student_if_needed(cur, student_name, team_id, university)

    conn.commit()
    cur.close()
    conn.close()


init_db()

if not try_load_from_excels() and os.path.exists(CSV_FILE):
    load_from_csv()


@app.route("/")
def index():
    return redirect(url_for("checkin"))


@app.route("/checkin", methods=["GET", "POST"])
def checkin():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    if request.method == "POST":
        student_id = request.form.get("student_id")
        team_id = request.form.get("team_id")
        action = request.form.get("action", "checkin")

        if team_id and team_id.isdigit():
            if action == "checkout":
                cur.execute(
                    """
                    UPDATE students
                    SET checked_in = FALSE, checkin_time = NULL
                    WHERE team_id = %s AND checked_in = TRUE
                    """,
                    (int(team_id),),
                )
            else:
                cur.execute(
                    """
                    UPDATE students
                    SET checked_in = TRUE, checkin_time = NOW()
                    WHERE team_id = %s AND checked_in = FALSE
                    """,
                    (int(team_id),),
                )

        elif student_id and student_id.isdigit():
            if action == "checkout":
                cur.execute(
                    """
                    UPDATE students
                    SET checked_in = FALSE, checkin_time = NULL
                    WHERE id = %s AND checked_in = TRUE
                    """,
                    (int(student_id),),
                )
            else:
                cur.execute(
                    """
                    UPDATE students
                    SET checked_in = TRUE, checkin_time = NOW()
                    WHERE id = %s AND checked_in = FALSE
                    """,
                    (int(student_id),),
                )

        conn.commit()
        cur.close()
        conn.close()
        return redirect(url_for("checkin"))

    q = request.args.get("q", "").strip()
    room = request.args.get("room", "").strip()

    sql = """
        SELECT
            students.id,
            students.name,
            students.university,
            students.checked_in,
            students.checkin_time,
            teams.id AS team_id,
            teams.team_name,
            teams.room
        FROM students
        JOIN teams ON students.team_id = teams.id
        WHERE 1=1
    """
    params = []

    if q:
        sql += """
            AND (
                students.name ILIKE %s
                OR students.university ILIKE %s
                OR teams.team_name ILIKE %s
                OR CAST(teams.id AS TEXT) ILIKE %s
            )
        """
        like = f"%{q}%"
        params.extend([like, like, like, like])

    if room in VALID_ROOMS:
        sql += " AND teams.room = %s"
        params.append(room)

    sql += " ORDER BY teams.room, teams.id, students.id"

    cur.execute(sql, params)
    students = cur.fetchall()

    cur.close()
    conn.close()

    return render_template("checkin.html", students=students, q=q, room=room, rooms=VALID_ROOMS)


@app.route("/students")
def students_list():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    status = request.args.get("status", "all")
    room = request.args.get("room", "").strip()

    sql = """
        SELECT
            students.id,
            students.name,
            students.university,
            students.checked_in,
            students.checkin_time,
            teams.id AS team_id,
            teams.team_name,
            teams.room
        FROM students
        JOIN teams ON students.team_id = teams.id
        WHERE 1=1
    """
    params = []

    if status == "present":
        sql += " AND students.checked_in = TRUE"
    elif status == "absent":
        sql += " AND students.checked_in = FALSE"

    if room in VALID_ROOMS:
        sql += " AND teams.room = %s"
        params.append(room)

    sql += " ORDER BY teams.room, teams.id, students.id"

    cur.execute(sql, params)
    students = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        "students_list.html",
        students=students,
        status=status,
        room=room,
        rooms=VALID_ROOMS,
    )


@app.route("/stats")
def stats():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    cur.execute("SELECT COUNT(*) AS c FROM students")
    total_students = cur.fetchone()["c"]

    cur.execute("SELECT COUNT(*) AS c FROM students WHERE checked_in = TRUE")
    total_checked_in = cur.fetchone()["c"]

    cur.execute("""
        SELECT
            teams.room,
            COUNT(students.id) AS total_students,
            SUM(CASE WHEN students.checked_in THEN 1 ELSE 0 END) AS present_students
        FROM students
        JOIN teams ON students.team_id = teams.id
        GROUP BY teams.room
        ORDER BY teams.room
    """)

    per_room = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        "stats.html",
        total_students=total_students,
        total_checked_in=total_checked_in,
        per_room=per_room,
        rooms=VALID_ROOMS,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
