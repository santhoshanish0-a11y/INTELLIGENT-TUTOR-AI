"""
Accounts and sign-in (standard library only).

  * Passwords are never stored. Only a salted PBKDF2-SHA256 hash is kept.
  * A successful sign-in returns a random session token. Only the SHA-256 of the token is stored, so a
    leaked database cannot be used to sign in. The browser sends the token with every request.
  * 5 wrong passwords lock that account for 5 minutes.
  * Accounts created before passwords existed can claim their name once by choosing a password,
    which keeps their old progress.
"""
import hashlib
import hmac
import os
import secrets

from . import database as db

ITERATIONS = 240_000
MAX_FAILS = 5
LOCK_SECONDS = 300
SESSION_SECONDS = 30 * 24 * 3600
MIN_PASSWORD, MAX_PASSWORD = 6, 128
COMMON_PASSWORDS = {"123456", "1234567", "12345678", "123456789", "password", "password1", "qwerty",
                    "qwerty123", "111111", "000000", "abc123", "iloveyou", "admin123", "letmein"}


class AuthError(Exception):
    def __init__(self, message, status=400, code=None):
        super().__init__(message)
        self.message, self.status, self.code = message, status, code


# --------------------------------------------------------------------------- #
# Password hashing
# --------------------------------------------------------------------------- #
def hash_password(password, salt=None, iterations=ITERATIONS):
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password, stored):
    try:
        algo, iterations, salt, digest = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        check = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), int(iterations))
        return hmac.compare_digest(check.hex(), digest)
    except (ValueError, AttributeError):
        return False


_DUMMY_HASH = hash_password("not-a-real-password")   # lets unknown names take as long as real ones


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #
def clean_name(name):
    name = " ".join((name or "").split())
    if len(name) < 2:
        raise AuthError("Enter a name with at least 2 characters.")
    if len(name) > 40:
        raise AuthError("Use a name of 40 characters or fewer.")
    return name


def check_password(password, name):
    if not isinstance(password, str) or len(password) < MIN_PASSWORD:
        raise AuthError(f"Use a password with at least {MIN_PASSWORD} characters.")
    if len(password) > MAX_PASSWORD:
        raise AuthError(f"Use a password of {MAX_PASSWORD} characters or fewer.")
    if password.lower() in COMMON_PASSWORDS or password.lower() == name.lower():
        raise AuthError("That password is too easy to guess. Choose something less common.")


# --------------------------------------------------------------------------- #
# Sessions
# --------------------------------------------------------------------------- #
def _token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _public(user):
    return {"id": user["id"], "name": user["name"], "exam": user["exam"]}


def _start_session(user):
    token = secrets.token_urlsafe(32)
    now = db.now()
    db.execute("DELETE FROM sessions WHERE expires < ?", (now,))
    db.execute("INSERT INTO sessions (token_hash, user_id, created, expires) VALUES (?,?,?,?)",
               (_token_hash(token), user["id"], now, now + SESSION_SECONDS))
    return {"token": token, "user": _public(user)}


def user_from_token(token):
    if not token:
        return None
    row = db.query(
        "SELECT u.id, u.name, u.exam FROM sessions s JOIN users u ON u.id = s.user_id "
        "WHERE s.token_hash = ? AND s.expires > ?", (_token_hash(token), db.now()), one=True)
    return row


def end_session(token):
    if token:
        db.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))


# --------------------------------------------------------------------------- #
# Sign up / sign in
# --------------------------------------------------------------------------- #
def _find(name):
    return db.query("SELECT * FROM users WHERE lower(name) = lower(?)", (name,), one=True)


def sign_up(name, password):
    name = clean_name(name)
    check_password(password, name)
    existing = _find(name)
    if existing and existing["password_hash"]:
        raise AuthError("That name is already taken. Sign in with it, or choose another name.", 409, "name_taken")
    if existing:        # account from before passwords: keep its progress, just set the password
        db.execute("UPDATE users SET password_hash=?, failed_attempts=0, locked_until=0 WHERE id=?",
                   (hash_password(password), existing["id"]))
        user = existing
    else:
        uid = db.execute("INSERT INTO users (name, exam, created, password_hash) VALUES (?,?,?,?)",
                         (name, "GENERAL", db.now(), hash_password(password)))
        user = {"id": uid, "name": name, "exam": "GENERAL"}
    # Creating an account does not sign the person in. They go to the Sign in page and enter their details.
    return {"ok": True, "name": user["name"]}


def sign_in(name, password):
    name = " ".join((name or "").split())
    password = password if isinstance(password, str) else ""
    user = _find(name) if name else None
    if not user:
        verify_password(password, _DUMMY_HASH)
        raise AuthError("Wrong name or password.", 401, "bad_credentials")
    if not user["password_hash"]:
        raise AuthError("This account was made before passwords existed. Choose Sign up with the same name "
                        "to set a password and keep your progress.", 409, "no_password")
    now = db.now()
    if user["locked_until"] > now:
        minutes = max(1, -(-(user["locked_until"] - now) // 60))
        raise AuthError(f"Too many wrong passwords. Try again in {minutes} minute{'s' if minutes != 1 else ''}.",
                        429, "locked")
    if not verify_password(password, user["password_hash"]):
        fails = user["failed_attempts"] + 1
        if fails >= MAX_FAILS:
            db.execute("UPDATE users SET failed_attempts=0, locked_until=? WHERE id=?", (now + LOCK_SECONDS, user["id"]))
            raise AuthError(f"Too many wrong passwords. This account is locked for {LOCK_SECONDS // 60} minutes.",
                            429, "locked")
        db.execute("UPDATE users SET failed_attempts=? WHERE id=?", (fails, user["id"]))
        raise AuthError("Wrong name or password.", 401, "bad_credentials")
    db.execute("UPDATE users SET failed_attempts=0, locked_until=0 WHERE id=?", (user["id"],))
    return _start_session(user)