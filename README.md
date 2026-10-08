# Intelligent Tutor - AI-Based Learning System

An AI and NLP powered tutor that answers student questions, conducts government-exam quizzes,
evaluates performance, finds weak areas and recommends what to study next.

```
Student asks -> AI understands -> Gives explanation -> Conducts quizzes
            -> Analyzes performance -> Finds weak areas -> Recommends suitable content
```

## Features

| Area | What it does |
|---|---|
| AI tutor chat | Answers any subject, LKG to PhD (level selector), step-by-step with exam tips |
| NLP engine | Intent detection, subject detection, TF-IDF retrieval, safe maths solver (`core/nlp.py`) |
| Government exam practice | 120+ questions for UPSC, SSC, Banking, RRB, TNPSC across 10 subjects |
| Adaptive quizzes | Picks weak topics and the right difficulty using recency-weighted mastery |
| Revision mode | Re-asks questions you got wrong (spaced repetition style) |
| Mock tests | Timed, mixed-subject, question palette, answer review at the end |
| Performance analytics | Accuracy, streak, daily goal, mastery radar, score trend, weak / strong topics |
| Recommendations | Books, official portals and courses matched to weak topics |
| Study plan | 7 / 14 / 30 day plan generated from the learner's weak areas |
| Extras | Voice input, "Explain in depth" for wrong answers, offline fallback, responsive UI |

## Run it

```bash
python -m venv venv
venv\Scripts\activate          # Windows   (Mac/Linux: source venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env         # Mac/Linux: cp .env.example .env
python app.py
```
Open **http://127.0.0.1:5000**.

**Full AI mode:** put your `ANTHROPIC_API_KEY` in `.env`. The tutor can then answer any question.
**Without a key** the app still runs in offline mode: quizzes, analytics, plans and recommendations
work fully, and chat answers come from the built-in knowledge base (about 25 exam topics).

Run the automated checks: `python test_smoke.py`

## Project structure

```
intelligent-tutor/
  app.py                  Flask server and REST API
  core/
    nlp.py                Tokeniser, TF-IDF, intent + subject detection, maths solver, knowledge base
    tutor.py              Routes a message: local handlers, maths, LLM or offline answer
    quiz.py               Question bank, adaptive selection, answer evaluation
    analytics.py          Mastery model, weak areas, streak, dashboard
    recommender.py        Material recommendations and study plans
    database.py           SQLite schema and helpers
  data/
    questions.json        Government-exam question bank
    knowledge_base.json   Offline concept notes
    materials.json        Books, portals, courses by subject
  templates/index.html    Single-page UI
  static/css/style.css    Design system
  static/js/app.js        Front-end logic (chat, quiz, charts)
  test_smoke.py           Automated tests
```

## How the adaptive engine works

1. Every answer is stored as an attempt (subject, topic, difficulty, correct, time).
2. **Mastery** of a topic = recency-weighted accuracy: newer attempts count more (decay 0.85) and a
   prior of 1.5 pseudo-attempts at 50% stops one lucky answer from marking a topic strong.
3. Topics are labelled **weak** (< 55%), **developing** (55-75%) or **strong** (>= 75%) after 2 attempts.
4. The next question is sampled with weight `1 + 3 x (1 - mastery)`, boosted when its difficulty
   matches the target level (easy below 45% mastery, medium below 75%, hard above), and reduced if it
   was seen recently.

## REST API

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/login` | Create or load a learner |
| POST | `/api/chat` | Ask the tutor |
| POST | `/api/quiz/start` | Start practice, revision or mock session |
| POST | `/api/quiz/answer` | Submit an answer, get explanation |
| POST | `/api/quiz/finish` | Session summary and recommendations |
| POST | `/api/quiz/review` | In-depth explanation of a question |
| GET | `/api/dashboard` | Analytics for the progress page |
| GET | `/api/plan` | Personalised study plan |
| GET | `/api/materials` | Library of resources |

## Technologies

Python 3, Flask, SQLite, Anthropic Claude API (LLM), custom NLP (TF-IDF, cosine similarity),
HTML5, CSS3, vanilla JavaScript, SVG charts.

## Honest limits and future work

- The question bank is a starter set; add more entries to `data/questions.json` (same format).
- Current-affairs questions are not included because they go out of date; connect a news source to add them.
- Future work: user passwords, previous-year-paper import, Tamil and Hindi interface, PDF upload for
  "chat with my notes", leaderboard.
