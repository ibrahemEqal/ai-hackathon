import csv
import os
import sqlite3
from flask import Flask, render_template, request, redirect, url_for, flash


DB_NAME = "attendance.db"
CSV_FILE = "students.csv"

app = Flask(__name__)
app.secret_key = "change-this-secret-key"  

def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row  
    return conn


def init_db():
    """إنشاء الجداول + تعبئتها من ملف CSV لو فاضية."""
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

    cur.execute("PRAGMA foreign_keys = ON;")

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS teams (
            id INTEGER PRIMARY KEY,
            team_name TEXT NOT NULL,
            room TEXT NOT NULL
        );
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            team_id INTEGER NOT NULL,
            checked_in INTEGER NOT NULL DEFAULT 0,
            checkin_time TEXT,
            FOREIGN KEY (team_id) REFERENCES teams (id)
        );
        """
    )

    cur.execute("SELECT COUNT(*) FROM students;")
    count = cur.fetchone()[0]

    if count == 0:
        if os.path.exists(CSV_FILE):
            load_from_csv(conn, CSV_FILE)
        else:
            print(f"⚠️ ملف {CSV_FILE} غير موجود، سيتم إنشاء الجداول بدون بيانات.")

    conn.commit()
    conn.close()


def load_from_csv(conn, csv_path):
    """قراءة بيانات من ملف CSV وتعبئتها في الجداول."""
    print(f"📥 تحميل البيانات من {csv_path} ...")
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            team_id = int(row["team_id"])
            team_name = row["team_name"].strip()
            room = row["room"].strip().upper()
            student_name = row["student_name"].strip()

            conn.execute(
                """
                INSERT OR IGNORE INTO teams (id, team_name, room)
                VALUES (?, ?, ?)
                """,
                (team_id, team_name, room),
            )

            conn.execute(
                """
                INSERT INTO students (name, team_id)
                VALUES (?, ?)
                """,
                (student_name, team_id),
            )

    conn.commit()
    print("✅ تم تحميل البيانات من CSV بنجاح.")


init_db()


@app.route("/")
def index():
    return redirect(url_for("checkin"))


@app.route("/checkin", methods=["GET", "POST"])
def checkin():
    conn = get_db_connection()

    if request.method == "POST":
        student_id = request.form.get("student_id")
        team_id = request.form.get("team_id")

        if team_id:
            conn.execute(
                """
                UPDATE students
                SET checked_in = 1,
                    checkin_time = datetime('now', 'localtime')
                WHERE team_id = ?
                """,
                (team_id,),
            )
            conn.commit()
            flash("تم تسجيل حضور الفريق كامل ✅", "success")

        elif student_id:
            conn.execute(
                """
                UPDATE students
                SET checked_in = 1,
                    checkin_time = datetime('now', 'localtime')
                WHERE id = ?
                """,
                (student_id,),
            )
            conn.commit()
            flash("تم تسجيل حضور الطالب بنجاح ✅", "success")

        conn.close()
        return redirect(url_for("checkin"))

    q = request.args.get("q", "").strip()
    room = request.args.get("room", "").strip().upper()

    sql = """
        SELECT
            students.id,
            students.name,
            students.checked_in,
            students.checkin_time,
            teams.id AS team_id,
            teams.team_name,
            teams.room
        FROM students
        JOIN teams ON students.team_id = teams.id
        WHERE 1 = 1
    """
    params = []

    if q:
        sql += """
            AND (
                students.name LIKE ?
                OR teams.team_name LIKE ?
                OR teams.id LIKE ?
            )
        """
        like = f"%{q}%"
        params += [like, like, like]

    if room in ("A", "B", "C", "D"):
        sql += " AND teams.room = ?"
        params.append(room)

    sql += " ORDER BY teams.room, teams.id, students.id"

    students = conn.execute(sql, params).fetchall()
    conn.close()

    return render_template("checkin.html", students=students, q=q, room=room)

@app.route("/students")
def students_list():
    conn = get_db_connection()

    status = request.args.get("status", "all")
    room = request.args.get("room", "").strip().upper()

    sql = """
        SELECT
            students.id,
            students.name,
            students.checked_in,
            students.checkin_time,
            teams.id AS team_id,
            teams.team_name,
            teams.room
        FROM students
        JOIN teams ON students.team_id = teams.id
        WHERE 1 = 1
    """
    params = []

    if status == "present":
        sql += " AND students.checked_in = 1"
    elif status == "absent":
        sql += " AND students.checked_in = 0"

    if room in ("A", "B", "C", "D"):
        sql += " AND teams.room = ?"
        params.append(room)

    sql += " ORDER BY teams.room, teams.id, students.id"

    students = conn.execute(sql, params).fetchall()
    conn.close()

    return render_template(
        "students_list.html",
        students=students,
        status=status,
        room=room,
    )

@app.route("/stats")
def stats():
    conn = get_db_connection()

    total_students = conn.execute(
        "SELECT COUNT(*) AS c FROM students"
    ).fetchone()["c"]

    total_checked_in = conn.execute(
        "SELECT COUNT(*) AS c FROM students WHERE checked_in = 1"
    ).fetchone()["c"]

    per_room = conn.execute(
        """
        SELECT
            teams.room,
            COUNT(students.id) AS total_students,
            SUM(CASE WHEN students.checked_in = 1 THEN 1 ELSE 0 END) AS present_students
        FROM students
        JOIN teams ON students.team_id = teams.id
        GROUP BY teams.room
        ORDER BY teams.room
        """
    ).fetchall()

    conn.close()

    return render_template(
        "stats.html",
        total_students=total_students,
        total_checked_in=total_checked_in,
        per_room=per_room,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

