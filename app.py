"""Intelligent Tutor - Flask application entry point."""
import os

from flask import Flask, jsonify, render_template, request

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from core import analytics, auth, database as db, quiz, recommender
from core.tutor import LEVELS, tutor

app = Flask(__name__)
db.init_db()
print(f" * Database: {db.backend()}")


def _token():
    header = request.headers.get("Authorization", "")
    return header[7:].strip() if header.lower().startswith("bearer ") else ""


def _user():
    return auth.user_from_token(_token())


def _need_user():
    user = _user()
    if not user:
        return None, (jsonify(error="Please sign in again.", code="signed_out"), 401)
    return user, None


@app.route("/")
def index():
    return render_template("index.html")


@app.get("/api/meta")
def meta():
    return jsonify(exams=quiz.EXAMS, levels=LEVELS, mode=tutor.mode,
                   subjects={e: quiz.subjects_for(e) for e in quiz.EXAMS},
                   bank_size=len(quiz.BANK))


def _credentials():
    data = request.get_json(silent=True) or {}
    return data.get("name"), data.get("password")


def _auth_call(fn):
    name, password = _credentials()
    try:
        return jsonify(fn(name, password))
    except auth.AuthError as e:
        return jsonify(error=e.message, code=e.code), e.status


@app.post("/api/signup")
def signup():
    return _auth_call(auth.sign_up)


@app.post("/api/login")
def login():
    return _auth_call(auth.sign_in)


@app.post("/api/logout")
def logout():
    auth.end_session(_token())
    return jsonify(ok=True)


@app.get("/api/me")
def me():
    user, err = _need_user()
    return err if err else jsonify(user=user)


@app.post("/api/chat")
def chat():
    user, err = _need_user()
    if err:
        return err
    data = request.get_json(force=True)
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify(error="Type a question first."), 400
    return jsonify(tutor.respond(user, message[:4000], data.get("level", "Government exam"), data.get("history", [])))


@app.post("/api/quiz/start")
def quiz_start():
    user, err = _need_user()
    if err:
        return err
    d = request.get_json(force=True)
    exam = d.get("exam") if d.get("exam") in quiz.EXAMS else user["exam"]
    session = quiz.start_session(user["id"], exam, d.get("subject", "All"), int(d.get("count", 10)), d.get("mode", "adaptive"))
    if not session:
        return jsonify(error="No questions found for this selection."), 404
    return jsonify(session)


@app.post("/api/quiz/answer")
def quiz_answer():
    user, err = _need_user()
    if err:
        return err
    d = request.get_json(force=True)
    try:
        result = quiz.record_answer(user["id"], d["session_id"], d["question_id"], d.get("choice"), d.get("seconds", 0))
    except (KeyError, TypeError):
        return jsonify(error="Invalid question."), 400
    return jsonify(result)


@app.post("/api/quiz/finish")
def quiz_finish():
    user, err = _need_user()
    if err:
        return err
    d = request.get_json(force=True)
    summary = quiz.finish_session(user["id"], d["session_id"])
    summary["recommendations"] = recommender.recommend(user["id"])
    return jsonify(summary)


@app.post("/api/quiz/review")
def quiz_review():
    """Ask the tutor to explain a question in depth."""
    user, err = _need_user()
    if err:
        return err
    d = request.get_json(force=True)
    q = quiz.BANK.get(d.get("question_id"))
    if not q:
        return jsonify(error="Unknown question."), 404
    return jsonify(reply=tutor.explain_question(user, q, d.get("choice")))


@app.get("/api/dashboard")
def dashboard():
    user, err = _need_user()
    if err:
        return err
    data = analytics.dashboard(user["id"])
    data["recommendations"] = recommender.recommend(user["id"])
    return jsonify(data)


@app.get("/api/materials")
def materials():
    return jsonify(recommender.all_materials())


@app.get("/api/plan")
def plan():
    user, err = _need_user()
    if err:
        return err
    days = max(3, min(int(request.args.get("days", 7)), 30))
    return jsonify(plan=recommender.study_plan(user["id"], days))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)), debug=True)