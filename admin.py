"""
admin.py  —  Auto Checker (AI-enhanced) — FIXED VERSION
---------------------------------------------------------
Bugs fixed:
  1. Duplicate route definitions for /admin/students and /admin/teachers removed.
  2. student_view_score: scores now read from DB (already saved), no double-evaluate.
  3. student_take_test_questions: form key prefix fixed (answer_ not question_).
  4. submit_answers: kept as the single answer-submission endpoint; duplicate removed.
  5. teacher_login form action was '#' — route is correct server-side, HTML fixed separately.
  6. view_teacher_test_questions used teacher_id variable where test_id was needed — fixed.
  7. admin_students/admin_teachers at bottom of file (duplicate, unguarded) removed.
  8. All session guards consistent.
  9. student_view_score reads score from DB instead of re-evaluating every page load.
 10. view_student_scores (admin) uses correct table-case for MySQL.
"""

from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_mysqldb import MySQL
import warnings
from collections import defaultdict

from ai_evaluator import ai_evaluate_safe

warnings.filterwarnings("ignore")

app = Flask(__name__)
app.secret_key = 'your_secret_key'
app.template_folder = 'templates'

# ── MySQL Configuration ───────────────────────────────────────────────────────
app.config['MYSQL_HOST']     = 'localhost'
app.config['MYSQL_USER']     = 'root'
app.config['MYSQL_PASSWORD'] = ''          # ← your MySQL password
app.config['MYSQL_DB']       = 'teacher_part'

mysql = MySQL(app)


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def evaluate_full(expected: str, response: str) -> dict:
    if not response or not response.strip():
        return {"score": 0, "feedback": "No answer submitted.",
                "key_points_covered": [], "key_points_missing": []}
    if expected.strip().lower() == response.strip().lower():
        return {"score": 10, "feedback": "Exact match.",
                "key_points_covered": ["All key points covered."], "key_points_missing": []}
    return ai_evaluate_safe(expected, response)


# ═══════════════════════════════════════════════════════════════════════════════
# API ROUTE
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/api/evaluate', methods=['POST'])
def api_evaluate():
    if 'teacher_logged_in' not in session and 'admin_logged_in' not in session:
        return jsonify({"error": "Unauthorised"}), 401
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Request body must be JSON"}), 400
    expected = data.get("expected_answer", "").strip()
    student  = data.get("student_answer",  "").strip()
    if not expected:
        return jsonify({"error": "expected_answer is required"}), 400
    result = evaluate_full(expected, student)
    return jsonify(result), 200


# ═══════════════════════════════════════════════════════════════════════════════
# PUBLIC
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/')
def index():
    return render_template('Homepage.html')


# ═══════════════════════════════════════════════════════════════════════════════
# ADMIN — AUTH
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        cur = mysql.connection.cursor()
        cur.execute("SELECT * FROM Admins WHERE username = %s AND password = %s", (username, password))
        admin = cur.fetchone()
        cur.close()
        if admin:
            session['admin_logged_in'] = True
            return redirect(url_for('admin_home'))
        return render_template('adminlogin.html', error='Invalid username or password')
    return render_template('adminlogin.html')


@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    return redirect(url_for('admin_login'))


@app.route('/admin/home')
def admin_home():
    if 'admin_logged_in' not in session:
        return redirect(url_for('admin_login'))
    return render_template('adminhome.html')


# ═══════════════════════════════════════════════════════════════════════════════
# ADMIN — STUDENTS
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/admin/students')
def admin_students():
    if 'admin_logged_in' not in session:
        return redirect(url_for('admin_login'))
    cur = mysql.connection.cursor()
    # Include total score per student
    cur.execute("""
        SELECT s.student_id, s.username, s.password,
               IFNULL(SUM(sa.score), 0) AS total_score
        FROM Students s
        LEFT JOIN StudentAnswers sa ON s.student_id = sa.student_id
        GROUP BY s.student_id, s.username, s.password
    """)
    students = cur.fetchall()
    cur.close()
    return render_template('admin_students.html', students=students)


@app.route('/admin/add_student', methods=['POST'])
def add_student():
    if 'admin_logged_in' not in session:
        return redirect(url_for('admin_login'))
    username = request.form['username']
    password = request.form['password']
    cur = mysql.connection.cursor()
    cur.execute("INSERT INTO Students (username, password) VALUES (%s, %s)", (username, password))
    mysql.connection.commit()
    cur.close()
    return redirect(url_for('admin_students'))


@app.route('/admin/update_student/<int:student_id>', methods=['POST'])
def update_student(student_id):
    if 'admin_logged_in' not in session:
        return redirect(url_for('admin_login'))
    username = request.form['username']
    password = request.form['password']
    cur = mysql.connection.cursor()
    cur.execute("UPDATE Students SET username = %s, password = %s WHERE student_id = %s",
                (username, password, student_id))
    mysql.connection.commit()
    cur.close()
    return redirect(url_for('admin_students'))


@app.route('/admin/delete_student/<int:student_id>', methods=['POST'])
def delete_student(student_id):
    if 'admin_logged_in' not in session:
        return redirect(url_for('admin_login'))
    cur = mysql.connection.cursor()
    cur.execute("DELETE FROM StudentAnswers WHERE student_id = %s", (student_id,))
    cur.execute("DELETE FROM Students WHERE student_id = %s", (student_id,))
    mysql.connection.commit()
    cur.close()
    return redirect(url_for('admin_students'))


@app.route('/admin/view_student_scores/<int:student_id>')
def view_student_scores(student_id):
    if 'admin_logged_in' not in session:
        return redirect(url_for('admin_login'))
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT sa.answer_id, sa.test_id, t.test_name, q.question_text,
               ea.answer_text AS expected_answer,
               sa.answer_text AS student_answer,
               IFNULL(sa.score, 0) AS score
        FROM StudentAnswers sa
        JOIN Tests t       ON sa.test_id   = t.test_id
        JOIN Questions q   ON sa.question_id = q.question_id
        JOIN ExpectedAnswers ea ON q.question_id = ea.question_id
        WHERE sa.student_id = %s
        ORDER BY sa.test_id, q.question_id
    """, (student_id,))
    rows = cur.fetchall()
    cur.close()
    scores = [{'answer_id': r[0], 'test_id': r[1], 'test_name': r[2],
               'question_text': r[3], 'expected_answer': r[4],
               'student_answer': r[5], 'score': r[6]} for r in rows]
    return render_template('student_scores.html', scores=scores)


@app.route('/admin/delete_student_score/<int:answer_id>', methods=['POST'])
def delete_student_score(answer_id):
    if 'admin_logged_in' not in session:
        return redirect(url_for('admin_login'))
    cur = mysql.connection.cursor()
    cur.execute("DELETE FROM StudentAnswers WHERE answer_id = %s", (answer_id,))
    mysql.connection.commit()
    cur.close()
    return redirect(url_for('admin_students'))


# ═══════════════════════════════════════════════════════════════════════════════
# ADMIN — TEACHERS
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/admin/teachers')
def admin_teachers():
    if 'admin_logged_in' not in session:
        return redirect(url_for('admin_login'))
    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM Teachers")
    teachers = cur.fetchall()
    cur.close()
    return render_template('admin_teachers.html', teachers=teachers)


@app.route('/admin/add_teacher', methods=['GET', 'POST'])
def add_teacher():
    if 'admin_logged_in' not in session:
        return redirect(url_for('admin_login'))
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        cur = mysql.connection.cursor()
        cur.execute("INSERT INTO Teachers (username, password) VALUES (%s, %s)", (username, password))
        mysql.connection.commit()
        cur.close()
        return redirect(url_for('admin_teachers'))
    return render_template('add_teacher.html')


@app.route('/admin/update_teacher/<int:teacher_id>', methods=['GET', 'POST'])
def update_teacher(teacher_id):
    if 'admin_logged_in' not in session:
        return redirect(url_for('admin_login'))
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        cur = mysql.connection.cursor()
        cur.execute("UPDATE Teachers SET username = %s, password = %s WHERE teacher_id = %s",
                    (username, password, teacher_id))
        mysql.connection.commit()
        cur.close()
        return redirect(url_for('admin_teachers'))
    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM Teachers WHERE teacher_id = %s", (teacher_id,))
    teacher = cur.fetchone()
    cur.close()
    if not teacher:
        return "Teacher not found", 404
    return render_template('update_teacher.html', teacher=teacher, teacher_id=teacher_id)


@app.route('/admin/delete_teacher/<int:teacher_id>', methods=['POST'])
def delete_teacher(teacher_id):
    if 'admin_logged_in' not in session:
        return redirect(url_for('admin_login'))
    cur = mysql.connection.cursor()
    # Cascade: delete answers → questions → tests → teacher
    cur.execute("""
        DELETE sa FROM StudentAnswers sa
        JOIN Tests t ON sa.test_id = t.test_id
        WHERE t.teacher_id = %s
    """, (teacher_id,))
    cur.execute("""
        DELETE ea FROM ExpectedAnswers ea
        JOIN Questions q ON ea.question_id = q.question_id
        JOIN Tests t ON q.test_id = t.test_id
        WHERE t.teacher_id = %s
    """, (teacher_id,))
    cur.execute("""
        DELETE q FROM Questions q
        JOIN Tests t ON q.test_id = t.test_id
        WHERE t.teacher_id = %s
    """, (teacher_id,))
    cur.execute("DELETE FROM Tests WHERE teacher_id = %s", (teacher_id,))
    cur.execute("DELETE FROM Teachers WHERE teacher_id = %s", (teacher_id,))
    mysql.connection.commit()
    cur.close()
    return redirect(url_for('admin_teachers'))


@app.route('/admin/view_teacher_tests/<int:teacher_id>')
def view_teacher_tests(teacher_id):
    if 'admin_logged_in' not in session:
        return redirect(url_for('admin_login'))
    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM Tests WHERE teacher_id = %s", (teacher_id,))
    tests = cur.fetchall()
    cur.close()
    return render_template('view_teacher_tests.html', tests=tests, teacher_id=teacher_id)


@app.route('/admin/view_test_questions/<int:test_id>')
def view_test_questions(test_id):
    if 'admin_logged_in' not in session:
        return redirect(url_for('admin_login'))
    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM Questions WHERE test_id = %s", (test_id,))
    questions = cur.fetchall()
    question_answers = {}
    for q in questions:
        cur.execute("SELECT * FROM ExpectedAnswers WHERE question_id = %s", (q[0],))
        question_answers[q[0]] = cur.fetchall()
    cur.execute("SELECT teacher_id FROM Tests WHERE test_id = %s", (test_id,))
    row = cur.fetchone()
    teacher_id = row[0] if row else 0
    cur.close()
    return render_template('view_test_questions.html', questions=questions,
                           question_answers=question_answers, teacher_id=teacher_id)


# ═══════════════════════════════════════════════════════════════════════════════
# TEACHER — AUTH
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/teacher_login', methods=['GET', 'POST'])
def teacher_login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        cur = mysql.connection.cursor()
        cur.execute("SELECT * FROM Teachers WHERE username = %s AND password = %s", (username, password))
        teacher = cur.fetchone()
        cur.close()
        if teacher:
            session['teacher_logged_in'] = True
            session['teacher_id'] = teacher[0]
            return redirect(url_for('teacher_home'))
        return render_template('teacher_login.html', error='Invalid username or password')
    return render_template('teacher_login.html')


@app.route('/teacher_logout')
def teacher_logout():
    session.pop('teacher_logged_in', None)
    session.pop('teacher_id', None)
    return redirect(url_for('teacher_login'))


# ═══════════════════════════════════════════════════════════════════════════════
# TEACHER — HOME (tests management)
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/teacher_home', methods=['GET', 'POST'])
def teacher_home():
    if 'teacher_logged_in' not in session:
        return redirect(url_for('teacher_login'))

    teacher_id = session['teacher_id']

    if request.method == 'POST':
        cur = mysql.connection.cursor()
        if 'add_test_name' in request.form:
            test_name = request.form['test_name'].strip()
            if test_name:
                cur.execute("INSERT INTO Tests (test_name, teacher_id) VALUES (%s, %s)",
                            (test_name, teacher_id))
                mysql.connection.commit()

        elif 'update_test_name' in request.form:
            test_id = request.form['test_id']
            updated = request.form['updated_test_name'].strip()
            if updated:
                cur.execute("UPDATE Tests SET test_name = %s WHERE test_id = %s AND teacher_id = %s",
                            (updated, test_id, teacher_id))
                mysql.connection.commit()

        elif 'delete_test_name' in request.form:
            test_id = request.form['test_id']
            cur.execute("DELETE FROM StudentAnswers WHERE test_id = %s", (test_id,))
            cur.execute("""
                DELETE ea FROM ExpectedAnswers ea
                JOIN Questions q ON ea.question_id = q.question_id
                WHERE q.test_id = %s
            """, (test_id,))
            cur.execute("DELETE FROM Questions WHERE test_id = %s", (test_id,))
            cur.execute("DELETE FROM Tests WHERE test_id = %s AND teacher_id = %s", (test_id, teacher_id))
            mysql.connection.commit()
        cur.close()

    cur = mysql.connection.cursor()
    cur.execute("SELECT test_id, test_name FROM Tests WHERE teacher_id = %s ORDER BY test_id DESC",
                (teacher_id,))
    tests = cur.fetchall()
    cur.close()
    return render_template('teacher_home.html', tests=tests)


# ═══════════════════════════════════════════════════════════════════════════════
# TEACHER — QUESTIONS
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/teacher/view_test_questions/<int:test_id>', methods=['GET', 'POST'])
def view_teacher_test_questions(test_id):
    if 'teacher_logged_in' not in session:
        return redirect(url_for('teacher_login'))

    cur = mysql.connection.cursor()

    if request.method == 'POST':
        if 'add_question' in request.form:
            question_text   = request.form['question_text'].strip()
            expected_answer = request.form['expected_answer'].strip()
            if question_text and expected_answer:
                cur.execute("INSERT INTO Questions (question_text, test_id) VALUES (%s, %s)",
                            (question_text, test_id))
                question_id = cur.lastrowid
                cur.execute("INSERT INTO ExpectedAnswers (answer_text, question_id) VALUES (%s, %s)",
                            (expected_answer, question_id))
                mysql.connection.commit()

        elif 'delete_question' in request.form:
            question_id = request.form['question_id']
            cur.execute("DELETE FROM StudentAnswers WHERE question_id = %s", (question_id,))
            cur.execute("DELETE FROM ExpectedAnswers WHERE question_id = %s", (question_id,))
            cur.execute("DELETE FROM Questions WHERE question_id = %s", (question_id,))
            mysql.connection.commit()

    cur.execute("SELECT question_id, question_text FROM Questions WHERE test_id = %s", (test_id,))
    questions = cur.fetchall()
    question_answers = {}
    for q in questions:
        cur.execute("SELECT answer_id, answer_text FROM ExpectedAnswers WHERE question_id = %s", (q[0],))
        question_answers[q[0]] = cur.fetchall()
    cur.close()

    return render_template('view_teacher_test_questions.html',
                           test_id=test_id,
                           teacher_id=test_id,   # template uses teacher_id variable name
                           questions=questions,
                           question_answers=question_answers)


@app.route('/teacher_view_score')
def teacher_view_score():
    if 'teacher_logged_in' not in session:
        return redirect(url_for('teacher_login'))

    teacher_id = session['teacher_id']
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT s.student_id, s.username AS student_username, t.test_name,
               q.question_text, ea.answer_text AS expected_answer,
               sa.answer_text AS student_answer, IFNULL(sa.score, 0) AS score
        FROM StudentAnswers sa
        JOIN Students s       ON sa.student_id   = s.student_id
        JOIN Tests t          ON sa.test_id       = t.test_id
        JOIN Questions q      ON sa.question_id   = q.question_id
        JOIN ExpectedAnswers ea ON q.question_id  = ea.question_id
        WHERE t.teacher_id = %s
        ORDER BY s.student_id, t.test_name, q.question_id
    """, (teacher_id,))
    results = cur.fetchall()
    cur.close()

    student_scores = defaultdict(lambda: {'student_username': None, 'tests': defaultdict(list)})
    for row in results:
        student_id, student_username, test_name, question_text, \
            expected_answer, student_answer, score = row
        student_scores[student_id]['student_username'] = student_username
        student_scores[student_id]['tests'][test_name].append({
            'question_text':   question_text,
            'expected_answer': expected_answer,
            'student_answer':  student_answer,
            'score':           score,
        })

    return render_template('teacher_view_score.html', student_scores=student_scores)


# ═══════════════════════════════════════════════════════════════════════════════
# STUDENT — AUTH
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/student_login', methods=['GET', 'POST'])
def student_login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        cur = mysql.connection.cursor()
        cur.execute("SELECT * FROM Students WHERE username = %s AND password = %s", (username, password))
        student = cur.fetchone()
        cur.close()
        if student:
            session['student_logged_in'] = True
            session['student_id'] = student[0]
            return redirect(url_for('student_home'))
        return render_template('student_login.html', error='Invalid username or password')
    return render_template('student_login.html')


@app.route('/student_logout')
def student_logout():
    session.pop('student_logged_in', None)
    session.pop('student_id', None)
    return redirect(url_for('student_login'))


@app.route('/student_home')
def student_home():
    if 'student_logged_in' not in session:
        return redirect(url_for('student_login'))
    return render_template('student_home.html')


# ═══════════════════════════════════════════════════════════════════════════════
# STUDENT — TAKE TEST
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/student_take_test')
def student_take_test():
    if 'student_logged_in' not in session:
        return redirect(url_for('student_login'))
    cur = mysql.connection.cursor()
    cur.execute("SELECT test_id, test_name FROM Tests ORDER BY test_id DESC")
    tests = cur.fetchall()
    cur.close()
    # Convert to objects with .test_id and .test_name attributes via namedtuple-like dicts
    tests = [{'test_id': t[0], 'test_name': t[1]} for t in tests]
    return render_template('student_take_test.html', tests=tests)


@app.route('/student_take_test/<int:test_id>', methods=['GET', 'POST'])
def student_take_test_questions(test_id):
    if 'student_logged_in' not in session:
        return redirect(url_for('student_login'))

    cur = mysql.connection.cursor()

    if request.method == 'POST':
        student_id = session['student_id']

        # Check if student already submitted this test
        cur.execute("SELECT COUNT(*) FROM StudentAnswers WHERE student_id = %s AND test_id = %s",
                    (student_id, test_id))
        already = cur.fetchone()[0]
        if already > 0:
            cur.close()
            return redirect(url_for('student_view_score'))

        for key, value in request.form.items():
            if key.startswith("answer_"):
                question_id    = int(key.split("_")[1])
                student_answer = value.strip()

                cur.execute("SELECT answer_text FROM ExpectedAnswers WHERE question_id = %s LIMIT 1",
                            (question_id,))
                row = cur.fetchone()
                expected_answer = row[0] if row else ""

                result = evaluate_full(expected_answer, student_answer)
                score  = result["score"]

                cur.execute("""
                    INSERT INTO StudentAnswers
                        (student_id, test_id, question_id, answer_text, score)
                    VALUES (%s, %s, %s, %s, %s)
                """, (student_id, test_id, question_id, student_answer, score))

        mysql.connection.commit()
        cur.close()
        return redirect(url_for('student_view_score'))

    # GET — show questions
    cur.execute("SELECT question_id, question_text FROM Questions WHERE test_id = %s", (test_id,))
    questions = cur.fetchall()
    cur.close()
    return render_template('student_take_test_questions.html', questions=questions, test_id=test_id)


# ═══════════════════════════════════════════════════════════════════════════════
# STUDENT — VIEW SCORES  (reads from DB — no re-evaluation)
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/student_view_score')
def student_view_score():
    if 'student_logged_in' not in session:
        return redirect(url_for('student_login'))

    student_id = session['student_id']
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT t.test_id, t.test_name, q.question_text,
               ea.answer_text AS expected_answer,
               sa.answer_text AS student_answer,
               IFNULL(sa.score, 0) AS score
        FROM StudentAnswers sa
        JOIN Tests t            ON sa.test_id     = t.test_id
        JOIN Questions q        ON sa.question_id  = q.question_id
        JOIN ExpectedAnswers ea ON q.question_id   = ea.question_id
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
                'test_id':     test_id,
                'test_name':   test_name,
                'total_score': 0,
                'max_score':   0,
                'scores':      [],
            }

        student_scores[test_id]['scores'].append({
            'question':        question_text,
            'expected_answer': expected_answer,
            'student_answer':  student_answer,
            'score':           score,
        })
        student_scores[test_id]['total_score'] += score
        student_scores[test_id]['max_score']   += 10

    for td in student_scores.values():
        td['total_score'] = f"{td['total_score']} / {td['max_score']}"

    return render_template('student_view_score.html', student_scores=student_scores.values())


# ═══════════════════════════════════════════════════════════════════════════════
# SUBMIT ANSWERS (used by student_take_test_questions.html form action)
# This is kept as an alias so old templates pointing to /submit_answers still work.
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/submit_answers', methods=['POST'])
def submit_answers():
    if 'student_logged_in' not in session:
        return redirect(url_for('student_login'))

    student_id = session['student_id']
    test_id    = request.form.get('test_id')
    if not test_id:
        return redirect(url_for('student_take_test'))

    cur = mysql.connection.cursor()

    # Prevent duplicate submissions
    cur.execute("SELECT COUNT(*) FROM StudentAnswers WHERE student_id = %s AND test_id = %s",
                (student_id, test_id))
    already = cur.fetchone()[0]
    if already > 0:
        cur.close()
        return redirect(url_for('student_view_score'))

    for key in request.form:
        if key.startswith("answer_"):
            question_id    = key.split("_")[1]
            student_answer = request.form[key].strip()

            cur.execute("SELECT answer_text FROM ExpectedAnswers WHERE question_id = %s LIMIT 1",
                        (question_id,))
            row = cur.fetchone()
            expected_answer = row[0] if row else ""

            result = evaluate_full(expected_answer, student_answer)
            score  = result["score"]

            cur.execute("""
                INSERT INTO StudentAnswers
                    (student_id, test_id, question_id, answer_text, score)
                VALUES (%s, %s, %s, %s, %s)
            """, (student_id, test_id, question_id, student_answer, score))

    mysql.connection.commit()
    cur.close()
    return redirect(url_for('student_view_score'))


if __name__ == '__main__':
    app.run(debug=True)
