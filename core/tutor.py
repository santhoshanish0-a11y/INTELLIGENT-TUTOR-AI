"""
The tutoring brain.

Pipeline:  message -> NLP (intent + subject) -> route
  * greeting / thanks / progress / quiz / recommend / plan  -> handled locally with UI actions
  * maths expression                                       -> exact local solver
  * everything else                                        -> LLM tutor (any subject, LKG to PhD)
                                                              or, offline, the built-in knowledge base
"""
import json
import os
import time
import urllib.error
import urllib.request

from . import analytics, database as db, nlp, recommender, websearch

try:  # optional dependency
    import anthropic
except ImportError:  # pragma: no cover
    anthropic = None

MODEL = os.environ.get("TUTOR_MODEL", "claude-sonnet-4-6")
KB = nlp.KnowledgeBase()

LEVELS = ["LKG-UKG", "Class 1-5", "Class 6-8", "Class 9-10", "Class 11-12",
          "Undergraduate", "Postgraduate", "PhD / Research", "Government exam"]

SYSTEM_PROMPT = """You are Intelligent Tutor, a patient and encouraging AI teacher.
You can teach any subject from LKG to PhD level and help students prepare for Indian government
exams (UPSC, SSC, Banking, Railways, TNPSC and state PSC exams).

How to answer:
- Adapt vocabulary and depth to the learner level: {level}.
- Lead with the direct answer, then explain step by step. Use short paragraphs, bullets and small tables.
- For maths and reasoning show the working and, where one exists, a faster exam shortcut.
- For government exam learners add a short "Exam tip" (what is commonly asked, a memory trick, or a trap).
- For young children use simple words, examples from daily life and a friendly tone.
- Finish with one quick "Check yourself" question when it helps learning.
- Never invent facts, dates or statistics. If you are unsure, say so.
- Stay on education. Politely decline harmful requests.

Today's date is {today}. Your own knowledge stops before this date, so anything that may have changed since
(office holders, laws, prices, exam notifications, results, news, rankings) must come from the live web
results below, not from memory. When live results are given, trust them over your memory, state the answer
directly, say it is as per the sources, and cite them as [1], [2]. Keep the "Exam tip" for current affairs too.
{live}
Learner profile: preferred exam = {exam}. {weak}"""


class LLMError(Exception):
    """Failure returned by an OpenAI-compatible provider (Groq, OpenRouter, Gemini, Ollama ...)."""

    def __init__(self, status, message):
        super().__init__(message)
        self.status, self.message = status, message


class Tutor:
    """
    Picks the first AI backend that is configured in .env:
      1. LLM_BASE_URL + LLM_MODEL (+ LLM_API_KEY)  any OpenAI-compatible service, e.g. Ollama, OpenRouter, Gemini
      2. GROQ_API_KEY                               free tier, no credit card
      3. ANTHROPIC_API_KEY                          Claude (paid)
    With none of them the tutor runs offline on the built-in knowledge base.
    """

    def __init__(self):
        self.client = None
        self.backend = None
        self.provider = "offline"
        self.base_url = self.api_key = ""
        # A Claude model name left over in .env must never be sent to a non-Claude provider.
        override = os.environ.get("LLM_MODEL") or os.environ.get("TUTOR_MODEL")
        self.model = override if override and not override.lower().startswith("claude") else None
        if os.environ.get("LLM_BASE_URL"):
            self.backend, self.provider = "openai", "custom"
            self.base_url, self.api_key = os.environ["LLM_BASE_URL"].rstrip("/"), os.environ.get("LLM_API_KEY", "none")
            self.model = self.model or "llama3.2"
        elif os.environ.get("GROQ_API_KEY"):
            self.backend, self.provider = "openai", "groq"
            self.base_url, self.api_key = "https://api.groq.com/openai/v1", os.environ["GROQ_API_KEY"]
            self.model = self.model or "openai/gpt-oss-120b"
        elif anthropic and os.environ.get("ANTHROPIC_API_KEY"):
            self.backend, self.provider = "anthropic", "anthropic"
            self.client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
            self.model = os.environ.get("TUTOR_MODEL") or MODEL

    @property
    def mode(self):
        return "ai" if self.backend else "offline"

    # ------------------------------------------------------------------ #
    def respond(self, user, message, level="Government exam", history=None):
        intent, confidence = nlp.detect_intent(message)
        subject = nlp.detect_subject(message)
        name = user["name"]
        actions = []

        if intent == "greeting":
            reply = (f"Hello {name}! I'm ready to help. Ask me anything, from a school concept to a "
                     f"research topic, or pick one of the options below.")
            actions = [{"type": "quiz", "label": "Take a quick quiz"}, {"type": "progress", "label": "See my progress"}]
        elif intent == "thanks":
            reply = "You're welcome! Keep going. Short daily practice beats long occasional sessions."
        elif intent == "progress":
            reply = self._progress_reply(user["id"])
            actions = [{"type": "progress", "label": "Open full dashboard"}]
        elif intent == "quiz":
            reply = "Let's test what you know. I'll pick questions from your weaker topics first."
            actions = [{"type": "quiz", "label": "Start adaptive quiz", "subject": subject}]
        elif intent == "recommend":
            reply, actions = self._recommend_reply(user["id"], subject)
        elif intent == "plan":
            reply = "I can build a day-by-day plan from your weak topics."
            actions = [{"type": "plan", "label": "Generate my study plan"}]
        else:
            solved = nlp.solve_math(message)
            if solved:
                reply, intent = solved, "math"
            else:
                reply = self._answer(user, message, level, history or [])
            actions = [{"type": "quiz", "label": "Practice this", "subject": subject}] if subject in {
                s for s in nlp.SUBJECT_LEXICON} else []

        db.execute("INSERT INTO chat_log (user_id, role, content, intent, subject, created) VALUES (?,?,?,?,?,?)",
                   (user["id"], "user", message, intent, subject, db.now()))
        db.execute("INSERT INTO chat_log (user_id, role, content, intent, subject, created) VALUES (?,?,?,?,?,?)",
                   (user["id"], "assistant", reply, intent, subject, db.now()))
        return {"reply": reply, "intent": intent, "subject": subject, "actions": actions, "mode": self.mode}

    # ------------------------------------------------------------------ #
    def _progress_reply(self, user_id):
        d = analytics.dashboard(user_id)
        if not d["questions_attempted"]:
            return "You haven't attempted any questions yet. Take a short quiz and I'll map your strengths and weak areas."
        lines = [f"You have answered **{d['questions_attempted']}** questions with **{d['accuracy']}%** accuracy "
                 f"and a **{d['streak']}-day** streak."]
        if d["weak"]:
            lines.append("**Needs work:** " + ", ".join(f"{w['topic']} ({w['accuracy']}%)" for w in d["weak"][:3]))
        if d["strong"]:
            lines.append("**Strong:** " + ", ".join(s["topic"] for s in d["strong"][:3]))
        return "\n\n".join(lines)

    def _recommend_reply(self, user_id, subject):
        picks = recommender.recommend(user_id)
        if not picks and subject:
            picks = [{**i, "subject": subject, "reason": f"Core resource for {subject}"} for i in recommender.for_subject(subject)]
        if not picks:
            return ("Take a quiz first so I can see your weak areas. Meanwhile, the Library tab lists "
                    "standard books and official resources for every subject."), [{"type": "library", "label": "Open Library"}]
        lines = ["Here is what I recommend:"] + [f"- **{p['title']}** ({p['type']}): {p['reason']}" for p in picks]
        return "\n".join(lines), [{"type": "library", "label": "Open Library"}]

    # ------------------------------------------------------------------ #
    def _answer(self, user, message, level, history):
        live = self._live_lookup(message)
        if self.backend:
            try:
                reply = self._llm(user, message, level, history, live)
            except Exception as exc:  # network, quota, bad key ...
                return self._offline(message, note=self._explain_error(exc), live=live)
            return reply + self._sources_footer(live)
        return self._offline(message, live=live)

    @staticmethod
    def _live_lookup(message):
        """For time-sensitive questions fetch fresh web results before answering."""
        if not nlp.needs_live_info(message):
            return {"needed": False, "results": [], "provider": None}
        results, provider = websearch.search(websearch.build_query(message))
        return {"needed": True, "results": results, "provider": provider}

    @staticmethod
    def _live_block(live):
        today = time.strftime("%d %B %Y")
        if not live["needed"]:
            return ""
        if live["results"]:
            return (f"\nLIVE WEB RESULTS (retrieved {today} via {live['provider']}):\n"
                    + websearch.format_for_prompt(live["results"]) + "\n")
        return ("\nThe learner asked something time-sensitive but live web search returned nothing "
                "(no internet or search blocked). Do NOT state a current office holder, figure, date or result "
                "as fact. Say clearly that you could not verify it live, give only stable background, and name "
                "the official source to check.\n")

    @staticmethod
    def _sources_footer(live):
        links = websearch.sources_markdown(live["results"]) if live["results"] else ""
        if not links:
            return ""
        return f"\n\n**Sources (live web, checked {time.strftime('%d %B %Y')}):**\n{links}"

    @staticmethod
    def _explain_error(exc):
        """Turn an API failure into a plain-language message the learner can act on."""
        detail = str(getattr(exc, "message", "") or exc)
        low = detail.lower()
        if "credit balance" in low:
            hint = "Your Anthropic account has no credit. Add a small amount under Billing in the Console, then try again."
        elif "model" in low and ("not found" in low or "invalid" in low):
            hint = "The model name is not available for your account. Set TUTOR_MODEL in .env to another model and restart."
        elif "api key" in low or "authentication" in low or "x-api-key" in low:
            hint = "The API key was rejected. Check that it is pasted correctly in .env with no spaces or quotes."
        elif getattr(exc, "status", None) == 429 or "rate limit" in low or "quota" in low:
            hint = "Free-tier limit reached. Wait a minute (or until tomorrow) and try again."
        elif getattr(exc, "status", None) in (401, 403):
            hint = "The API key was rejected. Check that it is pasted correctly in .env with no spaces or quotes."
        else:
            hint = "Check your internet connection and API key."
        return f"**The AI service could not answer ({type(exc).__name__}).** {hint}\n\n*Details: {detail[:300]}*"

    def _llm(self, user, message, level, history, live=None):
        weak = analytics.weak_topics(user["id"], 3)
        weak_txt = ("Weak topics: " + ", ".join(w["topic"] for w in weak) + ".") if weak else ""
        system = SYSTEM_PROMPT.format(level=level, exam=user.get("exam", "GENERAL"), weak=weak_txt,
                                      today=time.strftime("%A, %d %B %Y"),
                                      live=self._live_block(live or {"needed": False}))
        msgs = [{"role": h["role"], "content": h["content"]} for h in history[-10:]
                if h.get("role") in ("user", "assistant") and h.get("content")]
        msgs.append({"role": "user", "content": message})
        if self.backend == "openai":
            return self._chat_openai(system, msgs)
        resp = self.client.messages.create(model=self.model, max_tokens=1200, system=system, messages=msgs)
        return "".join(b.text for b in resp.content if getattr(b, "text", None))

    PREFERRED = ("openai/gpt-oss-120b", "llama-3.3-70b-versatile", "openai/gpt-oss-20b", "qwen/qwen3-32b",
                 "llama-3.1-8b-instant", "meta-llama/llama-4-scout")
    SKIP = ("whisper", "guard", "tts", "embed", "orpheus", "playai", "safeguard", "compound", "moderation", "rerank")

    def _request(self, path, payload=None):
        req = urllib.request.Request(
            self.base_url + path, data=json.dumps(payload).encode() if payload else None,
            method="POST" if payload else "GET",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}",
                     "User-Agent": "IntelligentTutor/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "ignore")
            try:
                raw = json.loads(raw)["error"]["message"]
            except Exception:
                pass
            raise LLMError(e.code, raw) from None
        except urllib.error.URLError as e:
            raise LLMError(0, f"Cannot reach {self.base_url}: {e.reason}") from None

    def _discover_model(self):
        """Ask the provider which models this key can use and pick the best chat model."""
        ids = [m["id"] for m in self._request("/models").get("data", []) if "id" in m]
        chat = [i for i in ids if not any(k in i.lower() for k in self.SKIP)]
        for want in self.PREFERRED:
            if want in chat:
                return want
        if chat:
            return chat[0]
        raise LLMError(404, "No chat models are available for this API key.")

    def _chat_openai(self, system, msgs):
        """Minimal client for any OpenAI-compatible /chat/completions endpoint (standard library only)."""
        def call():
            return self._request("/chat/completions", {
                "model": self.model, "max_tokens": 2000, "temperature": 0.3,
                "messages": [{"role": "system", "content": system}] + msgs})
        try:
            data = call()
        except LLMError as e:
            if e.status in (400, 404) and "model" in e.message.lower() and not getattr(self, "_rediscovered", False):
                self._rediscovered = True          # model name is stale: find a working one once, then retry
                self.model = self._discover_model()
                data = call()
            else:
                raise
        return data["choices"][0]["message"]["content"] or "(The model returned an empty answer. Please try again.)"

    def _offline(self, message, note=None, live=None):
        head = (note + "\n\n") if note else ""
        if live and live["results"]:
            # time-sensitive question and the AI is unavailable: show the fresh search results directly
            items = "\n".join(f"- **{r['title'][:90]}**: {r['snippet'][:260]}" + (f" ([open]({r['url']}))" if r["url"] else "")
                              for r in live["results"][:4])
            return (f"{head}**Latest from the web** (checked {time.strftime('%d %B %Y')}):\n\n{items}\n\n"
                    f"*The AI is not connected, so these are raw search results. Check the official source before relying on them.*")
        if live and live["needed"]:
            return (f"{head}This question depends on current information, and I could not reach the web to check it. "
                    f"Please verify it on the official website or a trusted news source.")
        entry, score = KB.lookup(message)
        if entry:
            return (f"{head}**{entry['title']}**\n\n{entry['content']}\n\n"
                    f"*Answered from the built-in knowledge base (offline mode).*")
        return (f"{head}I don't have this topic in my offline knowledge base. To answer **any** question "
                f"from LKG to PhD, add a free `GROQ_API_KEY` to the `.env` file and restart the server. "
                f"Meanwhile try topics like percentages, interest, syllogism, Preamble, Fundamental Rights, "
                f"Mauryan Empire, rivers of India or Thirukkural.")

    def explain_question(self, user, q, choice):
        """Deeper explanation of a quiz question, with an LLM when available."""
        picked = q["options"][choice] if choice is not None and 0 <= choice < 4 else "no answer"
        if self.backend:
            prompt = (f"Explain this exam question to a learner who chose '{picked}'.\n"
                      f"Question: {q['question']}\nOptions: {q['options']}\nCorrect: {q['options'][q['answer']]}\n"
                      "Say why the correct option is right, why the chosen option is wrong, and give a faster method or memory trick.")
            try:
                return self._llm(user, prompt, "Government exam", [])
            except Exception:
                pass
        return (f"**Correct answer:** {q['options'][q['answer']]}\n\n{q['explanation']}\n\n"
                f"*Connect an AI provider in .env for a personalised, step-by-step explanation.*")


tutor = Tutor()