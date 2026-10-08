"""
Lightweight NLP toolkit (pure Python, no heavy dependencies).

Implements:
  * tokenisation, stop-word removal and a tiny stemmer
  * TF-IDF vector space model with cosine similarity
  * intent classification  (question / quiz / progress / recommend / plan ...)
  * subject detection from a keyword lexicon
  * safe arithmetic + "x% of y" solver
  * semantic retrieval over the offline knowledge base
"""
import ast
import json
import math
import operator
import os
import re
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

STOPWORDS = set(
    "a an the is are was were be been being am do does did of to in on at for with by from "
    "and or but if then so as it its this that these those i me my we you your he she they "
    "them please can could should would will shall may might tell give about".split()
)


# --------------------------------------------------------------------------- #
# Text processing
# --------------------------------------------------------------------------- #
def stem(word):
    for suffix in ("ing", "edly", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


def tokenize(text, drop_stop=True):
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    if drop_stop:
        tokens = [t for t in tokens if t not in STOPWORDS]
    return [stem(t) for t in tokens]


class TfidfIndex:
    """Minimal TF-IDF index with cosine similarity search."""

    def __init__(self, documents):
        # documents: list of (doc_id, text)
        self.ids = [d[0] for d in documents]
        tokenised = [tokenize(d[1]) for d in documents]
        n = len(tokenised)
        df = Counter()
        for toks in tokenised:
            df.update(set(toks))
        self.idf = {t: math.log((1 + n) / (1 + c)) + 1.0 for t, c in df.items()}
        self.vectors = [self._vector(toks) for toks in tokenised]

    def _vector(self, tokens):
        tf = Counter(tokens)
        vec = {t: (1 + math.log(c)) * self.idf.get(t, 1.0) for t, c in tf.items()}
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        return {t: v / norm for t, v in vec.items()}

    def search(self, text, top_k=3):
        q = self._vector(tokenize(text))
        scored = []
        for doc_id, vec in zip(self.ids, self.vectors):
            score = sum(w * vec.get(t, 0.0) for t, w in q.items())
            if score > 0:
                scored.append((doc_id, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]


# --------------------------------------------------------------------------- #
# Intent classification
# --------------------------------------------------------------------------- #
INTENT_EXAMPLES = {
    "greeting": ["hi", "hello", "hey there", "good morning", "good evening", "namaste", "vanakkam"],
    "thanks": ["thanks", "thank you", "thank you so much", "great help"],
    "quiz": [
        "start a quiz", "give me a quiz", "test me", "conduct a test", "practice questions",
        "mock test", "ask me questions", "quiz me on polity", "i want to practice",
    ],
    "progress": [
        "show my progress", "how am i doing", "my performance", "my score",
        "analyze my performance", "what are my weak areas", "my weak topics",
    ],
    "recommend": [
        "recommend study material", "suggest books", "what should i study next",
        "learning resources", "suggest videos", "recommend notes",
    ],
    "plan": ["make a study plan", "create a timetable", "prepare schedule for exam", "30 day plan", "study roadmap"],
}
_INTENT_INDEX = TfidfIndex(
    [(f"{intent}:{i}", ex) for intent, exs in INTENT_EXAMPLES.items() for i, ex in enumerate(exs)]
)


def detect_intent(message):
    """Return (intent, confidence). Long, content-rich messages default to 'question'."""
    tokens = tokenize(message, drop_stop=False)
    if not tokens:
        return "question", 0.0
    if len(tokens) > 12:
        return "question", 0.0
    hits = _INTENT_INDEX.search(message, top_k=1)
    if hits:
        label, score = hits[0]
        threshold = 0.55 if len(tokens) <= 4 else 0.45
        if score >= threshold:
            return label.split(":")[0], round(score, 2)
    return "question", 0.0


# --------------------------------------------------------------------------- #
# Subject detection
# --------------------------------------------------------------------------- #
SUBJECT_LEXICON = {
    "Quantitative Aptitude": "percent percentage profit loss interest ratio proportion average speed distance train boat "
                             "work wage lcm hcf algebra equation simplify mensuration area volume probability permutation "
                             "number series age mixture discount",
    "Reasoning": "reasoning syllogism coding decoding blood relation direction analogy odd series puzzle seating clock calendar rank",
    "English": "grammar tense synonym antonym idiom phrase vocabulary sentence preposition article passage essay noun verb adjective",
    "Indian Polity": "constitution article amendment parliament president fundamental rights preamble lok sabha rajya sabha "
                     "supreme court governor panchayat directive election",
    "History": "history mughal maurya gupta chola mahatma gandhi revolt 1857 independence british empire dynasty battle freedom",
    "Geography": "geography river mountain plateau monsoon soil climate ocean latitude longitude earth continent himalaya",
    "Economy": "economy gdp inflation rbi repo budget tax gst fiscal monetary bank poverty planning niti",
    "General Science": "physics chemistry biology force energy atom cell vitamin photosynthesis element gas acid newton light heat",
    "Computer Awareness": "computer cpu ram software hardware internet network binary byte memory excel windows",
    "Tamil Nadu": "tamil thirukkural sangam silappathikaram kambar bharathiyar tnpsc chennai cauvery",
}
_SUBJECT_TOKENS = {s: {stem(t) for t in w.split()} for s, w in SUBJECT_LEXICON.items()}


def detect_subject(message):
    toks = set(tokenize(message))
    best, best_hits = None, 0
    for subject, vocab in _SUBJECT_TOKENS.items():
        hits = len(toks & vocab)
        if hits > best_hits:
            best, best_hits = subject, hits
    return best


# --------------------------------------------------------------------------- #
# Does the question need fresh, real-world information?
# --------------------------------------------------------------------------- #
_OFFICES = (r"cm|chief minister|pm|prime minister|president|vice president|governor|minister|speaker|chief justice|"
            r"cji|ceo|chairman|chairperson|secretary|dgp|mla|mp|commissioner|ambassador|governor of rbi|rbi governor")
_LIVE_PATTERNS = [
    r"\b(current|currently|present|presently|latest|recent|recently|newest|today|tonight|yesterday|tomorrow|"
    r"right now|as of|this (year|month|week)|nowadays|breaking|live)\b",
    r"\bnow\b",
    r"\b20(2[3-9]|3\d)\b",
    r"\bwho (is|are|was|won|became|has)\b.*\b(" + _OFFICES + r")\b",
    r"\b(" + _OFFICES + r")\b.*\bof\b",
    r"\b(news|election|elections|results?|winner|won|cutoff|cut off|notification|vacancy|vacancies|recruitment|"
    r"admit card|answer key|exam date|schedule|syllabus change|budget|gdp|inflation|repo rate|price|rate of|"
    r"score|ranking|rank|champion|world cup|ipl|olympics|award|nobel|launched|released|appointed|elected|"
    r"sworn|resigned|current affairs)\b",
]
_LIVE_RE = [re.compile(p, re.I) for p in _LIVE_PATTERNS]
_STATIC_HINTS = re.compile(r"\b(first|founder|founded|history of|ancient|medieval|define|definition|formula|"
                           r"derive|prove|theorem|solve|calculate|explain how|difference between)\b", re.I)


def needs_live_info(message):
    """True when the answer can change with time (office holders, news, results, notifications ...)."""
    text = message.strip()
    if len(text) < 6:
        return False
    if _STATIC_HINTS.search(text) and not re.search(r"\b(current|latest|present|now|today|20(2[3-9]|3\d))\b", text, re.I):
        return False
    return any(r.search(text) for r in _LIVE_RE)


# --------------------------------------------------------------------------- #
# Safe maths solver
# --------------------------------------------------------------------------- #
_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Pow: operator.pow, ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 100:
            raise ValueError("exponent too large")
        return _OPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.operand))
    raise ValueError("unsupported expression")


def _fmt(x):
    if isinstance(x, float) and x.is_integer():
        return str(int(x))
    return f"{x:.6g}" if isinstance(x, float) else str(x)


def solve_math(message):
    """Return a worked answer string for simple arithmetic questions, else None."""
    text = message.lower().replace(",", "")
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:%|percent)\s*of\s*(\d+(?:\.\d+)?)", text)
    if m:
        p, n = float(m.group(1)), float(m.group(2))
        return (f"**{_fmt(p)}% of {_fmt(n)}** = ({_fmt(p)} / 100) x {_fmt(n)} = **{_fmt(p * n / 100)}**\n\n"
                f"*Exam shortcut:* 10% of a number is the number shifted one place; build any percentage from 10%, 5% and 1%.")
    m = re.search(r"(?:square root|sqrt)\s*(?:of)?\s*(\d+(?:\.\d+)?)", text)
    if m:
        n = float(m.group(1))
        return f"The square root of {_fmt(n)} is **{_fmt(math.sqrt(n))}**."
    expr = text
    for word in ("what is", "calculate", "compute", "solve", "evaluate", "find", "the value of", "="):
        expr = expr.replace(word, " ")
    expr = expr.replace("?", " ").replace("^", "**").replace("\u00d7", "*").replace("\u00f7", "/")
    expr = re.sub(r"(?<=\d)\s*x\s*(?=\d)", "*", expr).strip()
    if re.fullmatch(r"[\d\s+\-*/().]+", expr) and re.search(r"\d", expr) and re.search(r"[+\-*/]", expr):
        try:
            value = _eval(ast.parse(expr.strip(), mode="eval"))
            return f"`{expr.strip()}` = **{_fmt(value)}**"
        except Exception:
            return None
    return None


# --------------------------------------------------------------------------- #
# Offline knowledge base
# --------------------------------------------------------------------------- #
class KnowledgeBase:
    def __init__(self, path=None):
        path = path or os.path.join(ROOT, "data", "knowledge_base.json")
        with open(path, encoding="utf-8") as fh:
            self.entries = {e["id"]: e for e in json.load(fh)}
        self.index = TfidfIndex(
            [(e["id"], f'{e["title"]} {e["title"]} {" ".join(e["keywords"])} {e["content"]}')
             for e in self.entries.values()]
        )

    GENERIC = {"india", "indian", "who", "what", "which", "explain", "describe", "define", "meaning"}

    def lookup(self, query, min_score=0.2):
        # Ignore very generic words so "who is the PM of India" cannot match the geography notes.
        words = [w for w in re.findall(r"[a-z0-9]+", query.lower()) if w not in self.GENERIC]
        if not words:
            return None, 0.0
        hits = self.index.search(" ".join(words), top_k=1)
        if hits and hits[0][1] >= min_score:
            return self.entries[hits[0][0]], hits[0][1]
        return None, 0.0