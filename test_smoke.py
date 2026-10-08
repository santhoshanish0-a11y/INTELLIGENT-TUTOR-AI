"""Quick automated checks:  python test_smoke.py"""
import os
import tempfile

os.environ["DATABASE_URL"] = ""      # tests always use a throw-away SQLite file
os.environ["TUTOR_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")

from app import app  # noqa: E402
from core import auth, database as db, nlp  # noqa: E402


def test_nlp():
    assert nlp.detect_intent("hello")[0] == "greeting"
    assert nlp.detect_intent("start a quiz")[0] == "quiz"
    assert nlp.detect_intent("show my progress")[0] == "progress"
    assert nlp.detect_intent("explain the causes of the revolt of 1857 in detail")[0] == "question"
    assert nlp.detect_subject("What is the Preamble of the constitution?") == "Indian Polity"
    assert "36" in nlp.solve_math("what is 15% of 240")
    assert "14" in nlp.solve_math("2 + 3 * 4")
    assert nlp.solve_math("__import__('os')") is None


def signup(c, name="Tester", password="secret99"):
    r = c.post("/api/signup", json={"name": name, "password": password})
    assert r.status_code == 200, r.get_json()
    assert "token" not in r.get_json()            # creating an account does not sign anyone in
    r = c.post("/api/login", json={"name": name, "password": password})
    assert r.status_code == 200, r.get_json()
    return {"Authorization": "Bearer " + r.get_json()["token"]}


def test_auth():
    c = app.test_client()
    # protected endpoints need a valid token
    assert c.get("/api/dashboard").status_code == 401
    assert c.get("/api/dashboard", headers={"Authorization": "Bearer nonsense"}).status_code == 401
    assert c.post("/api/chat", json={"message": "hi", "user_id": 1}).status_code == 401   # old user_id trick no longer works

    # sign-up rules
    assert c.post("/api/signup", json={"name": "A", "password": "secret99"}).status_code == 400
    assert c.post("/api/signup", json={"name": "Anita", "password": "123"}).status_code == 400
    assert c.post("/api/signup", json={"name": "Anita", "password": "password"}).status_code == 400
    h = signup(c, "Anita", "goodpass1")
    assert c.get("/api/me", headers=h).get_json()["user"]["name"] == "Anita"
    assert c.post("/api/signup", json={"name": "anita", "password": "another1"}).status_code == 409   # name taken, any case

    # password is stored hashed, never in plain text, and never returned
    row = db.query("SELECT * FROM users WHERE name='Anita'", one=True)
    assert row["password_hash"].startswith("pbkdf2_sha256$") and "goodpass1" not in row["password_hash"]
    assert "password" not in c.get("/api/me", headers=h).get_data(as_text=True).lower()

    # sign-in: right password works, wrong one does not, names are case-insensitive
    assert c.post("/api/login", json={"name": "ANITA", "password": "goodpass1"}).status_code == 200
    bad = c.post("/api/login", json={"name": "Anita", "password": "nope"})
    assert bad.status_code == 401 and bad.get_json()["error"] == "Wrong name or password."
    assert c.post("/api/login", json={"name": "Nobody", "password": "nope"}).get_json()["error"] == "Wrong name or password."

    # lockout after 5 wrong tries, even with the right password; then it clears
    for _ in range(3):      # one wrong try already made above, so this is try 2, 3 and 4
        assert c.post("/api/login", json={"name": "Anita", "password": "wrong"}).status_code == 401
    locked = c.post("/api/login", json={"name": "Anita", "password": "wrong"})
    assert locked.status_code == 429 and locked.get_json()["code"] == "locked"
    assert c.post("/api/login", json={"name": "Anita", "password": "goodpass1"}).status_code == 429
    db.execute("UPDATE users SET locked_until=0 WHERE name='Anita'")
    assert c.post("/api/login", json={"name": "Anita", "password": "goodpass1"}).status_code == 200

    # sign-out ends the session
    c.post("/api/logout", headers=h)
    assert c.get("/api/me", headers=h).status_code == 401

    # an account from before passwords keeps its progress when it claims a password
    uid = db.execute("INSERT INTO users (name, exam, created) VALUES ('Spidey','RRB',1)")
    db.execute("INSERT INTO attempts (user_id,question_id,subject,topic,difficulty,correct,seconds,created) "
               "VALUES (?,?,?,?,?,?,?,?)", (uid, "Q001", "Quantitative Aptitude", "Percentage", 1, 1, 3, 1))
    r = c.post("/api/login", json={"name": "spidey", "password": "whatever1"})
    assert r.status_code == 409 and r.get_json()["code"] == "no_password"
    h2 = signup(c, "spidey", "newpass12")
    me = c.get("/api/me", headers=h2).get_json()["user"]
    assert me["id"] == uid and me["exam"] == "RRB"
    assert c.get("/api/dashboard", headers=h2).get_json()["questions_attempted"] == 1

    # two users cannot see each other's data
    h3 = signup(c, "Other", "otherpass1")
    assert c.get("/api/dashboard", headers=h3).get_json()["questions_attempted"] == 0


def test_flow():
    c = app.test_client()
    h = signup(c, "Flow", "flowpass1")
    r = c.post("/api/chat", headers=h, json={"message": "Explain the Preamble"}).get_json()
    assert r["reply"] and r["subject"] == "Indian Polity"
    s = c.post("/api/quiz/start", headers=h, json={"exam": "TNPSC", "count": 6}).get_json()
    assert len(s["questions"]) == 6 and "answer" not in s["questions"][0]
    for q in s["questions"]:
        a = c.post("/api/quiz/answer", headers=h, json={"session_id": s["session_id"],
                                                         "question_id": q["id"], "choice": 0, "seconds": 5}).get_json()
        assert "explanation" in a
    f = c.post("/api/quiz/finish", headers=h, json={"session_id": s["session_id"]}).get_json()
    assert f["total"] == 6
    d = c.get("/api/dashboard", headers=h).get_json()
    assert d["questions_attempted"] == 6
    assert len(c.get("/api/plan?days=7", headers=h).get_json()["plan"]) == 7
    assert c.get("/api/materials").status_code == 200


if __name__ == "__main__":
    test_nlp()
    test_auth()
    test_flow()
    print("All smoke tests passed")