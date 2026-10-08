"""Performance analytics: topic mastery, weak-area detection, dashboard data."""
import time
from collections import defaultdict

from . import database as db

DECAY = 0.85          # weight of older attempts shrinks by this factor
PRIOR = 1.5           # pseudo-attempts at 50% so one lucky answer can't mark a topic strong
MIN_ATTEMPTS = 2      # attempts needed before a topic is classified
DAILY_GOAL = 20


def _label(mastery, attempts):
    if attempts < MIN_ATTEMPTS:
        return "new"
    if mastery >= 0.75:
        return "strong"
    if mastery >= 0.55:
        return "developing"
    return "weak"


def topic_stats(user_id):
    """Recency-weighted mastery for every (subject, topic) the learner has attempted."""
    rows = db.query(
        "SELECT subject, topic, correct, seconds FROM attempts WHERE user_id=? ORDER BY created DESC, id DESC",
        (user_id,),
    )
    groups = defaultdict(list)
    for r in rows:
        groups[(r["subject"], r["topic"])].append(r)
    stats = []
    for (subject, topic), items in groups.items():
        weights = [DECAY ** i for i in range(len(items))]
        num = sum(w * it["correct"] for w, it in zip(weights, items))
        mastery = (num + 0.5 * PRIOR) / (sum(weights) + PRIOR)
        attempts = len(items)
        stats.append({
            "subject": subject,
            "topic": topic,
            "attempts": attempts,
            "accuracy": round(100 * sum(i["correct"] for i in items) / attempts),
            "mastery": round(mastery, 3),
            "avg_seconds": round(sum(i["seconds"] for i in items) / attempts, 1),
            "status": _label(mastery, attempts),
        })
    stats.sort(key=lambda s: s["mastery"])
    return stats


def mastery_map(user_id):
    return {(s["subject"], s["topic"]): s["mastery"] for s in topic_stats(user_id)}


def weak_topics(user_id, limit=5):
    return [s for s in topic_stats(user_id) if s["status"] == "weak"][:limit]


def _streak(user_id):
    rows = db.query("SELECT created FROM attempts WHERE user_id=? ORDER BY created DESC", (user_id,))
    days = []       # one entry per calendar day (local time), newest first; works on SQLite and PostgreSQL
    for r in rows:
        d = time.strftime("%Y-%m-%d", time.localtime(r["created"]))
        if not days or days[-1] != d:
            days.append(d)
    if not days:
        return 0
    today = time.strftime("%Y-%m-%d", time.localtime())
    yesterday = time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400))
    if days[0] not in (today, yesterday):
        return 0
    streak, cursor = 0, time.mktime(time.strptime(days[0], "%Y-%m-%d"))
    for d in days:
        if d == time.strftime("%Y-%m-%d", time.localtime(cursor)):
            streak += 1
            cursor -= 86400
        else:
            break
    return streak


def dashboard(user_id):
    totals = db.query(
        "SELECT COUNT(*) AS n, COALESCE(SUM(correct),0) AS c, COALESCE(AVG(seconds),0) AS s FROM attempts WHERE user_id=?",
        (user_id,), one=True)
    midnight = int(time.mktime(time.strptime(time.strftime("%Y-%m-%d"), "%Y-%m-%d")))
    today = db.query("SELECT COUNT(*) AS n FROM attempts WHERE user_id=? AND created>=?", (user_id, midnight), one=True)["n"]
    stats = topic_stats(user_id)
    by_subject = defaultdict(list)
    for s in stats:
        by_subject[s["subject"]].append(s["mastery"])
    subjects = [{"subject": k, "mastery": round(sum(v) / len(v), 3), "topics": len(v)} for k, v in by_subject.items()]
    history = db.query(
        "SELECT id, mode, subject, score, total, created FROM quiz_sessions WHERE user_id=? AND finished=1 ORDER BY id DESC LIMIT 10",
        (user_id,))
    history.reverse()
    return {
        "questions_attempted": totals["n"],
        "accuracy": round(100 * totals["c"] / totals["n"]) if totals["n"] else 0,
        "avg_seconds": round(totals["s"], 1),
        "streak": _streak(user_id),
        "today": today,
        "daily_goal": DAILY_GOAL,
        "topics": stats,
        "subjects": subjects,
        "history": history,
        "weak": [s for s in stats if s["status"] == "weak"][:5],
        "strong": [s for s in reversed(stats) if s["status"] == "strong"][:5],
    }