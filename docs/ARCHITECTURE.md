# Architecture

```
 Browser (HTML / CSS / JS)
        |  JSON over HTTP
        v
 Flask API (app.py)
   |-- core/tutor.py ----> core/nlp.py (intent, subject, TF-IDF, maths)
   |        |-------------> LLM API (full answers)  or  knowledge_base.json (offline)
   |-- core/quiz.py -----> data/questions.json
   |-- core/analytics.py -> mastery, weak areas, streak
   |-- core/recommender.py -> data/materials.json
   '-- core/database.py --> SQLite (users, attempts, quiz_sessions, chat_log)
```

## Request flow for a chat message
1. `detect_intent` (TF-IDF cosine against example phrases) decides: greeting, quiz, progress, recommend, plan or question.
2. `detect_subject` scores the message against a subject lexicon.
3. Maths expressions are solved locally with a safe AST evaluator (no `eval`).
4. Other questions go to the LLM with a system prompt carrying the learner level, exam and weak topics.
5. If no API key or the service fails, the knowledge base is searched with TF-IDF.

## Database tables
- `users(id, name, exam, created)`
- `quiz_sessions(id, user_id, mode, exam, subject, total, score, finished)`
- `attempts(id, user_id, session_id, question_id, subject, topic, difficulty, correct, seconds, created)`
- `chat_log(id, user_id, role, content, intent, subject, created)`

## Security notes
- Correct answers are never sent to the browser before an answer is submitted.
- All dynamic text is HTML-escaped on the client.
- The maths solver whitelists AST node types and caps exponents.
