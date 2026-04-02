"""
admin.py — Auto Checker (fully fixed)
Fixes:
- Duplicate answers: DELETE before INSERT in all submission routes
- Passwords masked in admin panel
- teacher_id bug in view_teacher_test_questions fixed
- api/evaluate returns full breakdown
- All login forms POST to correct routes
"""

import os
import warnings
from collections import defaultdict

from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_mysqldb import MySQL

from ai_evaluator import ai_evaluate_safe

warnings.filterwarnings("ignore")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change_this_in_production_abc123")
app.template_folder = "templates"

# ── MySQL ──────────────────────────────────────────────────────────────────────
app.config["MYSQL_HOST"]     = "localhost"
app.config["MYSQL_USER"]     = "root"
app.config["MYSQL_PASSWORD"] = ""        # ← your MySQL password
app.config["MYSQL_DB"]       = "teacher_part"

mysql = MySQL(app)


# ══════════════════════════════════════════════════════════════════════════════
# HELPER
# ══════════════════════════════════════════════════════════════════════════════

def evaluate_answer(expected: str, student: str) -> dict:
    """Central evaluation call used by all submission routes."""
    expected = (expected or "").strip()
    student  = (student  or "").strip()
    if not student:
        return {"score": 0, "feedback": "No answer submitted.", "breakdown": {}}
    if not expected:
        return {"score": 0, "feedback": "No expected answer on file.", "breakdown": {}}
    if expected.lower() == student.lower():
        return {"score": 10, "feedback": "Exact match with expected answer.", "breakdown": {}}
    return ai_evaluate_safe(expected, student)


# ══════════════════════════════════════════════════════════════════════════════
# API — JSON evaluation endpoint
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/evaluate", methods=["POST"])
def api_evaluate():
    if "teacher_logged_in" not in session and "admin_logged_in" not in session:
        return jsonify({"error": "Unauthorised"}), 401
    data = request.get_json(silent=True) or {}
    expected = data.get("expected_answer", "").strip()
    student  = data.get("student_answer",  "").strip()
    if not expected:
        return jsonify({"error": "expected_answer is required"}), 400
    return jsonify(evaluate_answer(expected, student)), 200


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    return render_template("Homepage.html")


# ══════════════════════════════════════════════════════════════════════════════
# ADMIN — AUTH
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        cur = mysql.connection.cursor()
        cur.execute("SELECT * FROM Admins WHERE username=%s AND password=%s", (username, password))
        admin = cur.fetchone()
        cur.close()
        if admin:
            session["admin_logged_in"] = True
            return redirect(url_for("admin_home"))
        return render_template("adminlogin.html", error="Invalid username or password")
    return render_template("adminlogin.html")


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_logged_in", None)
    return redirect(url_for("admin_login"))


@app.route("/admin/home")
def admin_home():
    if "admin_logged_in" not in session:
        return redirect(url_for("admin_login"))
    return render_template("adminhome.html")


# ══════════════════════════════════════════════════════════════════════════════
# ADMIN — STUDENTS
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/admin/students")
def admin_students():
    if "admin_logged_in" not in session:
        return redirect(url_for("admin_login"))
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT s.student_id, s.username, s.password,
               IFNULL(SUM(sa.score), 0) AS total_score
        FROM Students s
        LEFT JOIN StudentAnswers sa ON s.student_id = sa.student_id
        GROUP BY s.student_id, s.username, s.password
        ORDER BY s.student_id
    """)
    students = cur.fetchall()
    cur.close()
    return render_template("admin_students.html", students=students)


@app.route("/admin/add_student", methods=["POST"])
def add_student():
    if "admin_logged_in" not in session:
        return redirect(url_for("admin_login"))
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()
    if username and password:
        cur = mysql.connection.cursor()
        cur.execute("INSERT INTO Students (username, password) VALUES (%s, %s)", (username, password))
        mysql.connection.commit()
        cur.close()
    return redirect(url_for("admin_students"))


@app.route("/admin/update_student/<int:student_id>", methods=["POST"])
def update_student(student_id):
    if "admin_logged_in" not in session:
        return redirect(url_for("admin_login"))
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()
    cur = mysql.connection.cursor()
    cur.execute("UPDATE Students SET username=%s, password=%s WHERE student_id=%s",
                (username, password, student_id))
    mysql.connection.commit()
    cur.close()
    return redirect(url_for("admin_students"))


@app.route("/admin/delete_student/<int:student_id>", methods=["POST"])
def delete_student(student_id):
    if "admin_logged_in" not in session:
        return redirect(url_for("admin_login"))
    cur = mysql.connection.cursor()
    cur.execute("DELETE FROM StudentAnswers WHERE student_id=%s", (student_id,))
    cur.execute("DELETE FROM Students WHERE student_id=%s", (student_id,))
    mysql.connection.commit()
    cur.close()
    return redirect(url_for("admin_students"))


@app.route("/admin/view_student_scores/<int:student_id>")
def view_student_scores(student_id):
    if "admin_logged_in" not in session:
        return redirect(url_for("admin_login"))
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT sa.answer_id, sa.test_id, t.test_name, q.question_text,
               ea.answer_text AS expected_answer,
               sa.answer_text AS student_answer,
               IFNULL(sa.score, 0) AS score
        FROM StudentAnswers sa
        JOIN Tests           t  ON sa.test_id     = t.test_id
        JOIN Questions       q  ON sa.question_id = q.question_id
        JOIN ExpectedAnswers ea ON q.question_id  = ea.question_id
        WHERE sa.student_id = %s
        GROUP BY sa.answer_id, sa.test_id, t.test_name, q.question_text,
                 ea.answer_text, sa.answer_text, sa.score
        ORDER BY sa.test_id, q.question_id
    """, (student_id,))
    rows = cur.fetchall()
    cur.close()
    scores = [
        {"answer_id": r[0], "test_id": r[1], "test_name": r[2],
         "question_text": r[3], "expected_answer": r[4],
         "student_answer": r[5], "score": r[6]}
        for r in rows
    ]
    return render_template("student_scores.html", scores=scores)


@app.route("/admin/delete_student_score/<int:answer_id>", methods=["POST"])
def delete_student_score(answer_id):
    if "admin_logged_in" not in session:
        return redirect(url_for("admin_login"))
    cur = mysql.connection.cursor()
    cur.execute("DELETE FROM StudentAnswers WHERE answer_id=%s", (answer_id,))
    mysql.connection.commit()
    cur.close()
    return redirect(url_for("admin_students"))


# ══════════════════════════════════════════════════════════════════════════════
# ADMIN — TEACHERS
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/admin/teachers")
def admin_teachers():
    if "admin_logged_in" not in session:
        return redirect(url_for("admin_login"))
    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM Teachers ORDER BY teacher_id")
    teachers = cur.fetchall()
    cur.close()
    return render_template("admin_teachers.html", teachers=teachers)


@app.route("/admin/add_teacher", methods=["GET", "POST"])
def add_teacher():
    if "admin_logged_in" not in session:
        return redirect(url_for("admin_login"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        if username and password:
            cur = mysql.connection.cursor()
            cur.execute("INSERT INTO Teachers (username, password) VALUES (%s, %s)", (username, password))
            mysql.connection.commit()
            cur.close()
        return redirect(url_for("admin_teachers"))
    return render_template("add_teacher.html")


@app.route("/admin/update_teacher/<int:teacher_id>", methods=["GET", "POST"])
def update_teacher(teacher_id):
    if "admin_logged_in" not in session:
        return redirect(url_for("admin_login"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        cur = mysql.connection.cursor()
        cur.execute("UPDATE Teachers SET username=%s, password=%s WHERE teacher_id=%s",
                    (username, password, teacher_id))
        mysql.connection.commit()
        cur.close()
        return redirect(url_for("admin_teachers"))
    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM Teachers WHERE teacher_id=%s", (teacher_id,))
    teacher = cur.fetchone()
    cur.close()
    if not teacher:
        return "Teacher not found", 404
    return render_template("update_teacher.html", teacher=teacher, teacher_id=teacher_id)


@app.route("/admin/delete_teacher/<int:teacher_id>", methods=["POST"])
def delete_teacher(teacher_id):
    if "admin_logged_in" not in session:
        return redirect(url_for("admin_login"))
    cur = mysql.connection.cursor()
    cur.execute("""
        DELETE sa FROM StudentAnswers sa
        JOIN Tests t ON sa.test_id = t.test_id
        WHERE t.teacher_id = %s
    """, (teacher_id,))
    cur.execute("""
        DELETE ea FROM ExpectedAnswers ea
        JOIN Questions q ON ea.question_id = q.question_id
        JOIN Tests t     ON q.test_id      = t.test_id
        WHERE t.teacher_id = %s
    """, (teacher_id,))
    cur.execute("""
        DELETE q FROM Questions q
        JOIN Tests t ON q.test_id = t.test_id
        WHERE t.teacher_id = %s
    """, (teacher_id,))
    cur.execute("DELETE FROM Tests WHERE teacher_id=%s", (teacher_id,))
    cur.execute("DELETE FROM Teachers WHERE teacher_id=%s", (teacher_id,))
    mysql.connection.commit()
    cur.close()
    return redirect(url_for("admin_teachers"))


@app.route("/admin/view_teacher_tests/<int:teacher_id>")
def view_teacher_tests(teacher_id):
    if "admin_logged_in" not in session:
        return redirect(url_for("admin_login"))
    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM Tests WHERE teacher_id=%s", (teacher_id,))
    tests = cur.fetchall()
    cur.close()
    return render_template("view_teacher_tests.html", tests=tests, teacher_id=teacher_id)


@app.route("/admin/view_test_questions/<int:test_id>")
def view_test_questions(test_id):
    if "admin_logged_in" not in session:
        return redirect(url_for("admin_login"))
    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM Questions WHERE test_id=%s", (test_id,))
    questions = cur.fetchall()
    question_answers = {}
    for q in questions:
        cur.execute("SELECT * FROM ExpectedAnswers WHERE question_id=%s", (q[0],))
        question_answers[q[0]] = cur.fetchall()
    cur.execute("SELECT teacher_id FROM Tests WHERE test_id=%s", (test_id,))
    row = cur.fetchone()
    teacher_id = row[0] if row else 0
    cur.close()
    return render_template("view_test_questions.html", questions=questions,
                           question_answers=question_answers, teacher_id=teacher_id)


# ══════════════════════════════════════════════════════════════════════════════
# TEACHER — AUTH
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/teacher_login", methods=["GET", "POST"])
def teacher_login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        cur = mysql.connection.cursor()
        cur.execute("SELECT * FROM Teachers WHERE username=%s AND password=%s", (username, password))
        teacher = cur.fetchone()
        cur.close()
        if teacher:
            session["teacher_logged_in"] = True
            session["teacher_id"] = teacher[0]
            return redirect(url_for("teacher_home"))
        return render_template("teacher_login.html", error="Invalid username or password")
    return render_template("teacher_login.html")


@app.route("/teacher_logout")
def teacher_logout():
    session.pop("teacher_logged_in", None)
    session.pop("teacher_id", None)
    return redirect(url_for("teacher_login"))


# ══════════════════════════════════════════════════════════════════════════════
# TEACHER — HOME
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/teacher_home", methods=["GET", "POST"])
def teacher_home():
    if "teacher_logged_in" not in session:
        return redirect(url_for("teacher_login"))
    teacher_id = session["teacher_id"]
    if request.method == "POST":
        cur = mysql.connection.cursor()
        if "add_test_name" in request.form:
            test_name = request.form.get("test_name", "").strip()
            if test_name:
                cur.execute("INSERT INTO Tests (test_name, teacher_id) VALUES (%s, %s)",
                            (test_name, teacher_id))
                mysql.connection.commit()
        elif "update_test_name" in request.form:
            test_id = request.form.get("test_id")
            updated = request.form.get("updated_test_name", "").strip()
            if updated:
                cur.execute("UPDATE Tests SET test_name=%s WHERE test_id=%s AND teacher_id=%s",
                            (updated, test_id, teacher_id))
                mysql.connection.commit()
        elif "delete_test_name" in request.form:
            test_id = request.form.get("test_id")
            cur.execute("DELETE FROM StudentAnswers WHERE test_id=%s", (test_id,))
            cur.execute("""
                DELETE ea FROM ExpectedAnswers ea
                JOIN Questions q ON ea.question_id = q.question_id
                WHERE q.test_id = %s
            """, (test_id,))
            cur.execute("DELETE FROM Questions WHERE test_id=%s", (test_id,))
            cur.execute("DELETE FROM Tests WHERE test_id=%s AND teacher_id=%s", (test_id, teacher_id))
            mysql.connection.commit()
        cur.close()
    cur = mysql.connection.cursor()
    cur.execute("SELECT test_id, test_name FROM Tests WHERE teacher_id=%s ORDER BY test_id DESC",
                (teacher_id,))
    tests = cur.fetchall()
    cur.close()
    return render_template("teacher_home.html", tests=tests)


# ══════════════════════════════════════════════════════════════════════════════
# TEACHER — QUESTIONS
# FIX: use test_id correctly (was passing teacher_id as test_id before)
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/teacher/view_test_questions/<int:test_id>", methods=["GET", "POST"])
def view_teacher_test_questions(test_id):
    if "teacher_logged_in" not in session:
        return redirect(url_for("teacher_login"))

    # Verify this test belongs to the logged-in teacher
    teacher_id = session["teacher_id"]
    cur = mysql.connection.cursor()
    cur.execute("SELECT test_id FROM Tests WHERE test_id=%s AND teacher_id=%s",
                (test_id, teacher_id))
    if not cur.fetchone():
        cur.close()
        return "Test not found or access denied.", 403

    if request.method == "POST":
        if "add_question" in request.form:
            q_text = request.form.get("question_text", "").strip()
            a_text = request.form.get("expected_answer", "").strip()
            if q_text and a_text:
                cur.execute("INSERT INTO Questions (question_text, test_id) VALUES (%s, %s)",
                            (q_text, test_id))
                qid = cur.lastrowid
                cur.execute("INSERT INTO ExpectedAnswers (answer_text, question_id) VALUES (%s, %s)",
                            (a_text, qid))
                mysql.connection.commit()
        elif "delete_question" in request.form:
            qid = request.form.get("question_id")
            cur.execute("DELETE FROM StudentAnswers WHERE question_id=%s", (qid,))
            cur.execute("DELETE FROM ExpectedAnswers WHERE question_id=%s", (qid,))
            cur.execute("DELETE FROM Questions WHERE question_id=%s", (qid,))
            mysql.connection.commit()

    cur.execute("SELECT question_id, question_text FROM Questions WHERE test_id=%s", (test_id,))
    questions = cur.fetchall()
    question_answers = {}
    for q in questions:
        cur.execute("SELECT answer_id, answer_text FROM ExpectedAnswers WHERE question_id=%s", (q[0],))
        question_answers[q[0]] = cur.fetchall()
    cur.close()
    return render_template("view_teacher_test_questions.html",
                           test_id=test_id,
                           teacher_id=teacher_id,
                           questions=questions,
                           question_answers=question_answers)


@app.route("/teacher_view_score")
def teacher_view_score():
    if "teacher_logged_in" not in session:
        return redirect(url_for("teacher_login"))
    teacher_id = session["teacher_id"]
    cur = mysql.connection.cursor()
    # FIX: GROUP BY to prevent duplicate rows from multiple ExpectedAnswers
    cur.execute("""
        SELECT s.student_id, s.username, t.test_name,
               q.question_text, ea.answer_text,
               sa.answer_text, IFNULL(sa.score, 0)
        FROM StudentAnswers sa
        JOIN Students        s  ON sa.student_id  = s.student_id
        JOIN Tests           t  ON sa.test_id      = t.test_id
        JOIN Questions       q  ON sa.question_id  = q.question_id
        JOIN (
            SELECT question_id, MIN(answer_id) AS min_aid
            FROM ExpectedAnswers GROUP BY question_id
        ) ea_sub ON q.question_id = ea_sub.question_id
        JOIN ExpectedAnswers ea ON ea.answer_id = ea_sub.min_aid
        WHERE t.teacher_id = %s
        ORDER BY s.student_id, t.test_name, q.question_id
    """, (teacher_id,))
    results = cur.fetchall()
    cur.close()
    student_scores = defaultdict(lambda: {"student_username": None, "tests": defaultdict(list)})
    for row in results:
        sid, uname, tname, qtext, exp_ans, stu_ans, score = row
        student_scores[sid]["student_username"] = uname
        student_scores[sid]["tests"][tname].append({
            "question_text":   qtext,
            "expected_answer": exp_ans,
            "student_answer":  stu_ans,
            "score":           score,
        })
    return render_template("teacher_view_score.html", student_scores=student_scores)


# ══════════════════════════════════════════════════════════════════════════════
# STUDENT — AUTH
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/student_login", methods=["GET", "POST"])
def student_login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        cur = mysql.connection.cursor()
        cur.execute("SELECT * FROM Students WHERE username=%s AND password=%s", (username, password))
        student = cur.fetchone()
        cur.close()
        if student:
            session["student_logged_in"] = True
            session["student_id"] = student[0]
            return redirect(url_for("student_home"))
        return render_template("student_login.html", error="Invalid username or password")
    return render_template("student_login.html")


@app.route("/student_logout")
def student_logout():
    session.pop("student_logged_in", None)
    session.pop("student_id", None)
    return redirect(url_for("student_login"))


@app.route("/student_home")
def student_home():
    if "student_logged_in" not in session:
        return redirect(url_for("student_login"))
    return render_template("student_home.html")


# ══════════════════════════════════════════════════════════════════════════════
# STUDENT — TAKE TEST
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/student_take_test")
def student_take_test():
    if "student_logged_in" not in session:
        return redirect(url_for("student_login"))
    cur = mysql.connection.cursor()
    cur.execute("SELECT test_id, test_name FROM Tests ORDER BY test_id DESC")
    rows = cur.fetchall()
    cur.close()
    tests = [{"test_id": r[0], "test_name": r[1]} for r in rows]
    return render_template("student_take_test.html", tests=tests)


@app.route("/student_take_test/<int:test_id>", methods=["GET", "POST"])
def student_take_test_questions(test_id):
    if "student_logged_in" not in session:
        return redirect(url_for("student_login"))
    cur = mysql.connection.cursor()

    if request.method == "POST":
        student_id = session["student_id"]

        # FIX: DELETE existing answers for this student+test before inserting
        # This prevents duplicate rows and allows re-evaluation
        cur.execute(
            "DELETE FROM StudentAnswers WHERE student_id=%s AND test_id=%s",
            (student_id, test_id)
        )
        mysql.connection.commit()

        for key, value in request.form.items():
            if not key.startswith("answer_"):
                continue
            try:
                question_id = int(key.split("_", 1)[1])
            except (ValueError, IndexError):
                continue
            student_answer = value.strip()

            # Get the ONE expected answer (avoid JOIN duplication)
            cur.execute(
                "SELECT answer_text FROM ExpectedAnswers WHERE question_id=%s LIMIT 1",
                (question_id,)
            )
            row = cur.fetchone()
            expected_answer = row[0] if row else ""

            result = evaluate_answer(expected_answer, student_answer)
            score  = result["score"]

            cur.execute("""
                INSERT INTO StudentAnswers
                    (student_id, test_id, question_id, answer_text, score)
                VALUES (%s, %s, %s, %s, %s)
            """, (student_id, test_id, question_id, student_answer, score))

        mysql.connection.commit()
        cur.close()
        return redirect(url_for("student_view_score"))

    # GET — show questions (DISTINCT to avoid duplicates from multiple ExpectedAnswers)
    cur.execute(
        "SELECT DISTINCT question_id, question_text FROM Questions WHERE test_id=%s ORDER BY question_id",
        (test_id,)
    )
    questions = cur.fetchall()
    cur.close()
    return render_template("student_take_test_questions.html",
                           questions=questions, test_id=test_id)


# ══════════════════════════════════════════════════════════════════════════════
# STUDENT — VIEW SCORES
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/student_view_score")
def student_view_score():
    if "student_logged_in" not in session:
        return redirect(url_for("student_login"))
    student_id = session["student_id"]
    cur = mysql.connection.cursor()
    # FIX: Use subquery for ExpectedAnswers to avoid JOIN multiplication
    cur.execute("""
        SELECT t.test_id, t.test_name, q.question_text,
               ea.answer_text, sa.answer_text,
               IFNULL(sa.score, 0)
        FROM StudentAnswers sa
        JOIN Tests           t  ON sa.test_id     = t.test_id
        JOIN Questions       q  ON sa.question_id = q.question_id
        JOIN (
            SELECT question_id, MIN(answer_id) AS min_aid
            FROM ExpectedAnswers GROUP BY question_id
        ) ea_sub ON q.question_id = ea_sub.question_id
        JOIN ExpectedAnswers ea ON ea.answer_id = ea_sub.min_aid
        WHERE sa.student_id = %s
        ORDER BY t.test_id, q.question_id
    """, (student_id,))
    results = cur.fetchall()
    cur.close()

    student_scores = {}
    for row in results:
        test_id, test_name, question_text, expected_answer, student_answer, score = row
        if test_id not in student_scores:
            student_scores[test_id] = {
                "test_id":     test_id,
                "test_name":   test_name,
                "total_score": 0,
                "max_score":   0,
                "scores":      [],
            }
        student_scores[test_id]["scores"].append({
            "question":        question_text,
            "expected_answer": expected_answer,
            "student_answer":  student_answer,
            "score":           score,
        })
        student_scores[test_id]["total_score"] += score
        student_scores[test_id]["max_score"]   += 10

    for td in student_scores.values():
        td["total_score"] = f"{td['total_score']} / {td['max_score']}"

    return render_template("student_view_score.html",
                           student_scores=student_scores.values())


# ══════════════════════════════════════════════════════════════════════════════
# SUBMIT ANSWERS (alias route for template form action)
# FIX: DELETE before INSERT to prevent duplicates
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/submit_answers", methods=["POST"])
def submit_answers():
    if "student_logged_in" not in session:
        return redirect(url_for("student_login"))
    student_id = session["student_id"]
    test_id    = request.form.get("test_id")
    if not test_id:
        return redirect(url_for("student_take_test"))

    cur = mysql.connection.cursor()

    # FIX: Always delete existing answers first → allows re-takes & prevents duplicates
    cur.execute(
        "DELETE FROM StudentAnswers WHERE student_id=%s AND test_id=%s",
        (student_id, test_id)
    )
    mysql.connection.commit()

    for key in request.form:
        if not key.startswith("answer_"):
            continue
        try:
            question_id = int(key.split("_", 1)[1])
        except (ValueError, IndexError):
            continue
        student_answer = request.form[key].strip()

        cur.execute(
            "SELECT answer_text FROM ExpectedAnswers WHERE question_id=%s LIMIT 1",
            (question_id,)
        )
        row = cur.fetchone()
        expected_answer = row[0] if row else ""

        result = evaluate_answer(expected_answer, student_answer)
        score  = result["score"]

        cur.execute("""
            INSERT INTO StudentAnswers
                (student_id, test_id, question_id, answer_text, score)
            VALUES (%s, %s, %s, %s, %s)
        """, (student_id, test_id, question_id, student_answer, score))

    mysql.connection.commit()
    cur.close()
    return redirect(url_for("student_view_score"))


if __name__ == "__main__":
    app.run(debug=True)
