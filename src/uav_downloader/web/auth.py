"""Account store, password hashing, sessions and login throttling.

Stdlib only. Two JSON files live in the web state dir (``UAV_WEB_STATE_DIR``,
default ``/state``): ``users.json`` and ``sessions.json``. Both are written
atomically (temp file + ``os.replace``). Passwords are stored as salted
PBKDF2-HMAC-SHA256 hashes; plaintext never touches disk.

On first use (store missing, empty or corrupt) exactly one account is
bootstrapped: ``admin`` / ``admin``, role ``admin``, ``must_change`` set so
the first login is forced through a password change.
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time

SESSION_TTL = 30 * 24 * 3600  # 30 days
LOCK_THRESHOLD = 5            # consecutive failures before lockout
LOCK_SECONDS = 5 * 60         # lockout duration
_PBKDF2_ROUNDS = 200_000
_USERNAME_RE = re.compile(r'[A-Za-z0-9_.-]{1,32}')

_lock = threading.RLock()
_failures = {}  # username -> (fail_count, locked_until_epoch)


# ---------------------------------------------------------------------------
# Storage helpers
# ---------------------------------------------------------------------------

def _state_dir():
    return os.environ.get('UAV_WEB_STATE_DIR', '/state')


def _path(name):
    return os.path.join(_state_dir(), name)


def _load_json(name, default):
    try:
        with open(_path(name), encoding='utf-8') as stream:
            data = json.load(stream)
        return data if isinstance(data, type(default)) else default
    except (OSError, ValueError):
        return default


def _save_json(name, data):
    os.makedirs(_state_dir(), exist_ok=True)
    temp = _path(name) + '.tmp'
    with open(temp, 'w', encoding='utf-8') as stream:
        json.dump(data, stream, ensure_ascii=False)
    os.replace(temp, _path(name))


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

def _hash(password, salt_hex):
    return hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'),
                               bytes.fromhex(salt_hex), _PBKDF2_ROUNDS).hex()


def _new_credentials(password):
    salt = secrets.token_hex(16)
    return salt, _hash(password, salt)


def _valid_record(user):
    return (isinstance(user, dict)
            and isinstance(user.get('username'), str)
            and isinstance(user.get('salt'), str)
            and isinstance(user.get('hash'), str)
            and user.get('role') in ('admin', 'user'))


def _safe(user):
    """Public view of a user record — never salt/hash."""
    return {'username': user['username'],
            'role': user['role'],
            'must_change': bool(user.get('must_change')),
            'created': int(user.get('created') or 0)}


def _load_users():
    """User records, bootstrapping the default admin when the store is
    missing, empty or has no usable record. Caller holds ``_lock``."""
    data = _load_json('users.json', {'users': []})
    users = [u for u in data.get('users', []) if _valid_record(u)] \
        if isinstance(data.get('users'), list) else []
    if not users:
        salt, hashed = _new_credentials('admin')
        users = [{'username': 'admin', 'salt': salt, 'hash': hashed,
                  'role': 'admin', 'must_change': True,
                  'created': int(time.time())}]
        _save_json('users.json', {'users': users})
    return users


def _save_users(users):
    _save_json('users.json', {'users': users})


def _find(users, username):
    for user in users:
        if user['username'] == username:
            return user
    return None


def ensure_bootstrap():
    """Create the default admin account if the store has never been used."""
    with _lock:
        _load_users()


def get_user(username):
    with _lock:
        user = _find(_load_users(), username)
        return _safe(user) if user else None


def list_users():
    with _lock:
        return [_safe(user) for user in _load_users()]


def user_count():
    with _lock:
        return len(_load_users())


def admin_count():
    with _lock:
        return sum(1 for user in _load_users() if user['role'] == 'admin')


def valid_username(username):
    return isinstance(username, str) and bool(_USERNAME_RE.fullmatch(username))


def password_ok(password):
    """Policy for user-set passwords: at least 8 characters."""
    return isinstance(password, str) and len(password) >= 8


def check_password(username, password):
    if not isinstance(password, str):
        return False
    with _lock:
        user = _find(_load_users(), username)
        if user is None:
            return False
        return hmac.compare_digest(_hash(password, user['salt']), user['hash'])


def authenticate(username, password):
    """Safe user dict when the credentials check out, else None."""
    if not isinstance(password, str):
        return None
    with _lock:
        user = _find(_load_users(), username)
        if user is None:
            return None
        if not hmac.compare_digest(_hash(password, user['salt']), user['hash']):
            return None
        return _safe(user)


def create_user(username, password, role='user'):
    if not valid_username(username):
        raise ValueError('用户名需为 1-32 个字符（字母、数字、_ . -）')
    if not password_ok(password):
        raise ValueError('密码至少 8 位')
    if role not in ('admin', 'user'):
        raise ValueError('角色不正确')
    with _lock:
        users = _load_users()
        if _find(users, username) is not None:
            raise ValueError('用户名已存在')
        salt, hashed = _new_credentials(password)
        record = {'username': username, 'salt': salt, 'hash': hashed,
                  'role': role, 'must_change': False,
                  'created': int(time.time())}
        users.append(record)
        _save_users(users)
        return _safe(record)


def set_password(username, new_password, must_change=False):
    salt, hashed = _new_credentials(new_password)
    with _lock:
        users = _load_users()
        user = _find(users, username)
        if user is None:
            raise ValueError('用户不存在')
        user['salt'], user['hash'] = salt, hashed
        user['must_change'] = bool(must_change)
        _save_users(users)


def set_role(username, role):
    if role not in ('admin', 'user'):
        raise ValueError('角色不正确')
    with _lock:
        users = _load_users()
        user = _find(users, username)
        if user is None:
            raise ValueError('用户不存在')
        user['role'] = role
        _save_users(users)


def delete_user(username):
    with _lock:
        users = _load_users()
        kept = [user for user in users if user['username'] != username]
        if len(kept) == len(users):
            raise ValueError('用户不存在')
        _save_users(kept)
    revoke_user_sessions(username)


# ---------------------------------------------------------------------------
# Sessions (persisted, 30-day TTL)
# ---------------------------------------------------------------------------

def _load_sessions():
    return _load_json('sessions.json', {})


def create_session(username):
    token = secrets.token_urlsafe(32)
    with _lock:
        sessions = _load_sessions()
        sessions[token] = {'username': username,
                           'expires': int(time.time()) + SESSION_TTL}
        _save_json('sessions.json', sessions)
    return token


def lookup_session(token):
    """Safe user dict for a live session token, else None.

    Expired sessions and sessions whose user no longer exists are purged.
    """
    if not token or not isinstance(token, str):
        return None
    with _lock:
        sessions = _load_sessions()
        record = sessions.get(token)
        if not isinstance(record, dict):
            return None
        user = _find(_load_users(), record.get('username', ''))
        if user is None or int(record.get('expires', 0)) <= int(time.time()):
            sessions.pop(token, None)
            _save_json('sessions.json', sessions)
            return None
        return _safe(user)


def revoke_session(token):
    if not token:
        return
    with _lock:
        sessions = _load_sessions()
        if token in sessions:
            del sessions[token]
            _save_json('sessions.json', sessions)


def revoke_user_sessions(username):
    with _lock:
        sessions = _load_sessions()
        kept = {token: record for token, record in sessions.items()
                if not isinstance(record, dict)
                or record.get('username') != username}
        if len(kept) != len(sessions):
            _save_json('sessions.json', kept)


# ---------------------------------------------------------------------------
# Login throttling (in-memory)
# ---------------------------------------------------------------------------

def lock_remaining(username):
    """Seconds left on the account's login lock; 0 when not locked."""
    with _lock:
        _count, until = _failures.get(username, (0, 0))
        remaining = int(until - time.time())
        return remaining if remaining > 0 else 0


def record_failure(username):
    with _lock:
        count, until = _failures.get(username, (0, 0))
        if until > time.time():
            return  # Already locked; failures during lockout don't extend it.
        count += 1
        if count >= LOCK_THRESHOLD:
            _failures[username] = (0, time.time() + LOCK_SECONDS)
        else:
            _failures[username] = (count, 0)


def record_success(username):
    with _lock:
        _failures.pop(username, None)
