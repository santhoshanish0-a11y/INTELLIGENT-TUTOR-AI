"""Question bank, adaptive selection and answer evaluation."""
import json
import os
import random

from . import analytics, database as db

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

EXAMS = {
    "UPSC": "UPSC Civil Services (Prelims GS and CSAT)",
    "SSC": "SSC CGL / CHSL / MTS",
    "BANKING": "Banking (IBPS / SBI PO and Clerk)",
    "RRB": "Railway RRB NTPC / Group D",
    "TNPSC": "TNPSC Group 1, 2, 4",
    "GENERAL": "All government exams",
}
_ALL_BASIC = {"UPSC", "SSC", "BANKING", "RRB", "TNPSC"}
SUBJECT_EXAMS = {
    "Quantitative Aptitude": _ALL_BASIC,
    "Reasoning": _ALL_BASIC,
    "English": _ALL_BASIC,
    "Indian Polity": {"UPSC", "SSC", "RRB", "TNPSC", "BANKING"},
    "History": {"UPSC", "SSC", "RRB", "TNPSC"},
    "Geography": {"UPSC", "SSC", "RRB", "TNPSC"},
    "Economy": {"UPSC", "SSC", "BANKING", "TNPSC"},
    "General Science": {"UPSC", "SSC", "RRB", "TNPSC"},
    "Computer Awareness": {"SSC", "BANKING", "RRB"},
    "Tamil Nadu": {"TNPSC"},
}


def _load():
    with open(os.path.join(ROOT, "data", "questions.json"), encoding="utf-8") as fh:
        raw = json.load(fh)
    bank = {}
    for i, q in enumerate(raw, start=1):
        qid = f"Q{i:03d}"
        bank[qid] = {"id": qid, "subject": q["s"], "topic": q["t"], "difficulty": q["d"],
                     "question": q["q"], "options": q["o"], "answer": q["a"], "explanation": q["x"]}
    return bank


BANK = _load()


def subjects_for(exam):
    return [s for s, exams in SUBJECT_EXAMS.items() if exam == "GENERAL" or exam in exams]


def public(q, index=None):
    """Question without the answer, safe to send to the browser."""
    return {"id": q["id"], "subject": q["subject"], "topic": q["topic"],
            "difficulty": q["difficulty"], "question": q["question"], "options": q["options"]}


def _pool(exam, subject):
    allowed = set(subjects_for(exam))
    return [q for q in BANK.values()
            if q["subject"] in allowed and (subject in (None, "", "All") or q["subject"] == subject)]


def _recent_ids(user_id, n=80):
    rows = db.query("SELECT question_id FROM attempts WHERE user_id=? ORDER BY id DESC LIMIT ?", (user_id, n))
    return [r["question_id"] for r in rows]


def _target_difficulty(mastery):
    return 1 if mastery < 0.45 else 2 if mastery < 0.75 else 3


def select(user_id, exam, subject, count, mode):
    """Pick questions. adaptive = weak topics + right difficulty; revision = past mistakes."""
    pool = _pool(exam, subject)
    if not pool:
        return []
    count = max(1, min(count, len(pool)))
    mastery = analytics.mastery_map(user_id)
    recent = _recent_ids(user_id)
    chosen = []

    if mode == "revision":
        last = {}
        for r in db.query("SELECT question_id, correct FROM attempts WHERE user_id=? ORDER BY id ASC", (user_id,)):
            last[r["question_id"]] = r["correct"]
        wrong = [q for q in pool if last.get(q["id"]) == 0]
        random.shuffle(wrong)
        chosen = wrong[:count]
        mode = "adaptive"

    if mode == "mock":
        by_subject = {}
        for q in pool:
            by_subject.setdefault(q["subject"], []).append(q)
        for qs in by_subject.values():
            random.shuffle(qs)
        while len(chosen) < count and any(by_subject.values()):
            for qs in by_subject.values():
                if qs and len(chosen) < count:
                    chosen.append(qs.pop())
        random.shuffle(chosen)
        return chosen

    remaining = [q for q in pool if q not in chosen]
    while len(chosen) < count and remaining:
        weights = []
        for q in remaining:
            m = mastery.get((q["subject"], q["topic"]), 0.5)
            w = 1 + 3 * (1 - m)                                  # favour weak topics
            gap = abs(q["difficulty"] - _target_difficulty(m))
            w *= (2.0, 1.0, 0.3)[min(gap, 2)]                    # favour the right difficulty
            if q["id"] in recent:
                w *= 0.25 if recent.index(q["id"]) < 30 else 0.6  # avoid just-seen questions
            weights.append(w)
        pick = random.choices(remaining, weights=weights, k=1)[0]
        chosen.append(pick)
        remaining.remove(pick)
    return chosen


def start_session(user_id, exam, subject, count, mode):
    questions = select(user_id, exam, subject, count, mode)
    if not questions:
        return None
    sid = db.execute(
        "INSERT INTO quiz_sessions (user_id, mode, exam, subject, total, created) VALUES (?,?,?,?,?,?)",
        (user_id, mode, exam, subject or "All", len(questions), db.now()))
    return {"session_id": sid, "mode": mode, "questions": [public(q) for q in questions],
            "time_limit": len(questions) * 45 if mode == "mock" else None}


def record_answer(user_id, session_id, question_id, choice, seconds):
    q = BANK.get(question_id)
    if not q:
        raise KeyError("unknown question")
    correct = int(choice == q["answer"])
    db.execute(
        "INSERT INTO attempts (user_id, session_id, question_id, subject, topic, difficulty, correct, seconds, created) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (user_id, session_id, question_id, q["subject"], q["topic"], q["difficulty"], correct, float(seconds or 0), db.now()))
    return {"correct": bool(correct), "answer": q["answer"], "explanation": q["explanation"]}


def finish_session(user_id, session_id):
    rows = db.query("SELECT question_id, correct, seconds FROM attempts WHERE session_id=? AND user_id=?", (session_id, user_id))
    score = sum(r["correct"] for r in rows)
    db.execute("UPDATE quiz_sessions SET score=?, total=?, finished=1 WHERE id=? AND user_id=?",
               (score, max(len(rows), 1), session_id, user_id))
    per_topic = {}
    for r in rows:
        q = BANK[r["question_id"]]
        t = per_topic.setdefault((q["subject"], q["topic"]), [0, 0])
        t[0] += r["correct"]
        t[1] += 1
    breakdown = [{"subject": k[0], "topic": k[1], "correct": v[0], "total": v[1]} for k, v in per_topic.items()]
    breakdown.sort(key=lambda b: b["correct"] / b["total"])
    return {"score": score, "total": len(rows), "percent": round(100 * score / len(rows)) if rows else 0,
            "breakdown": breakdown}
