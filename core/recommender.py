"""Learning-material recommendations and personalised study plans."""
import json
import os

from . import analytics

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(ROOT, "data", "materials.json"), encoding="utf-8") as _fh:
    MATERIALS = json.load(_fh)


def all_materials():
    return MATERIALS


def for_subject(subject):
    for m in MATERIALS:
        if m["subject"] == subject:
            return m["items"]
    return []


def recommend(user_id, limit=4):
    """Materials for the learner's weakest topics, each with the reason it was picked."""
    weak = analytics.weak_topics(user_id, limit=limit)
    picks, seen = [], set()
    for w in weak:
        for item in for_subject(w["subject"])[:2]:
            key = (w["subject"], item["title"])
            if key in seen:
                continue
            seen.add(key)
            picks.append({**item, "subject": w["subject"],
                          "reason": f'Your {w["topic"]} accuracy is {w["accuracy"]}%'})
    return picks[:limit]


def study_plan(user_id, days=7):
    """Round-robin plan: weakest topics get the most sessions; every day ends with a revision quiz."""
    stats = analytics.topic_stats(user_id)
    ordered = [s for s in stats if s["status"] in ("weak", "developing")] or stats
    if not ordered:
        ordered = [{"subject": m["subject"], "topic": m["topics"][0], "status": "new"} for m in MATERIALS]
    plan = []
    for d in range(days):
        focus = ordered[d % len(ordered)]
        second = ordered[(d + 1) % len(ordered)]
        plan.append({
            "day": d + 1,
            "focus": f'{focus["subject"]}: {focus["topic"]}',
            "tasks": [
                f'Read the concept notes on {focus["topic"]} (30 min)',
                f'Solve 10 adaptive questions in {focus["subject"]}',
                f'Revise {second["topic"]} with a 5-question quiz',
                "Review yesterday's mistakes in Revision mode",
            ],
        })
    if days >= 7:
        plan[-1]["tasks"].append("Take a full mock test and compare with your first score")
    return plan
