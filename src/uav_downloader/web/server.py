"""Small same-origin authenticated HTTP surface, deliberately not a file server."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import threading
import time
from urllib.parse import parse_qs, quote, urlsplit

from uav_downloader.core.storage import StorageWriteError
from . import actress, auth, backfill, library, metadata, organize
from . import postprocess, probe, searchsvc, thumbs, transcode
from .ui import HTML, CSS, JS

try:
    HLS_JS = Path(__file__).with_name('hls.min.js').read_bytes()
except OSError:
    HLS_JS = None  # UI falls back to a native playback attempt.


def _id_list(data, required=True):
    """Validate an ``{ids: [...]}`` body; returns the id list (str-coerced)."""
    if set(data) - {'ids'} or (required and 'ids' not in data):
        raise ValueError('Expected only ids')
    ids = data.get('ids')
    if ids is None:
        return None
    if not isinstance(ids, list) or len(ids) > 500:
        raise ValueError('ids must be a list')
    out = []
    for item in ids:
        if isinstance(item, bool) or not isinstance(item, (str, int)):
            raise ValueError('ids must be strings or integers')
        out.append(str(item))
    return out

MAX_BODY = 256 * 1024
DEFAULT_SETTINGS = {'auto_rename': True, 'file_mode': 'preview', 'lang': 'zh-Hans'}
PAGE_CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; img-src 'self' https: data:; media-src 'self' blob:; "
            "frame-ancestors 'none'; base-uri 'none'; form-action 'none'; object-src 'none'")
VIDEO_TYPES = {'.mp4': 'video/mp4', '.mkv': 'video/x-matroska',
               '.avi': 'video/x-msvideo', '.mov': 'video/quicktime',
               '.wmv': 'video/x-ms-wmv', '.ts': 'video/mp2t',
               '.m2ts': 'video/mp2t', '.webm': 'video/webm'}
IMAGE_TYPES = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
               '.png': 'image/png', '.webp': 'image/webp', '.gif': 'image/gif'}
QUERY_GET_PATHS = {'/api/search', '/api/library', '/api/library/tree',
                   '/api/library/actresses', '/api/settings',
                   '/api/stream', '/api/cover', '/api/thumb', '/api/play/info'}
HLS_FILE_RE = re.compile(r'^(index\.m3u8|seg\d+\.ts)$')
# While an account still has must_change set, only these paths stay usable:
# the forced password-change flow and its escape hatch.
MUST_CHANGE_ALLOWED = {'/api/me', '/api/change-password', '/api/logout'}


def _enrich_jobs(jobs):
    """Add ``code``/``actress`` display fields to queue job dicts.

    Best-effort and offline only: backfill intents by job id, then existing
    postprocess plans by code, then the metadata cache (never a network
    lookup).  Unknown actresses stay ''.  Mutates and returns *jobs*.
    """
    try:
        intents = backfill.load_intents()
    except Exception:
        intents = {}
    plan_by_code = {}
    try:
        for plan in postprocess.load_plans():
            if plan.get('code') and plan.get('actress_cn'):
                plan_by_code.setdefault(plan['code'], plan['actress_cn'])
    except Exception:
        pass
    for job in jobs or []:
        url = job.get('url', '')
        tail = url.rstrip('/').rsplit('/', 1)[-1]
        job['code'] = library.extract_code(tail) or library.extract_code(url)
        actress = ''
        intent = intents.get(job.get('id') or '')
        if intent:
            actress = intent.get('actress_cn') or ''
        if not actress and job['code']:
            actress = plan_by_code.get(job['code'], '')
        if not actress and job['code']:
            try:
                cached = metadata.cached_lookup(job['code'])
            except Exception:
                cached = None
            if cached:
                actress = cached.get('actress_cn') or ''
        job['actress'] = actress
    return jobs


def _enrich_snapshot(snapshot):
    _enrich_jobs((snapshot or {}).get('jobs'))
    return snapshot


_BACKFILL_ITEM_KEYS = ('url', 'code', 'title', 'actress_jp', 'actress_cn',
                       'target_dir', 'target_name')


def _backfill_items(data):
    """Validate the ``items`` field of a backfill request body."""
    items = data.get('items')
    if not isinstance(items, list) or not 1 <= len(items) <= 1000:
        raise ValueError('items must be a list of 1..1000 entries')
    out = []
    for item in items:
        if (not isinstance(item, dict)
                or not set(item) <= set(_BACKFILL_ITEM_KEYS)
                or any(not isinstance(item.get(key, ''), str)
                       for key in _BACKFILL_ITEM_KEYS)
                or not item.get('url')):
            raise ValueError('Invalid backfill item')
        out.append({key: item.get(key, '') for key in _BACKFILL_ITEM_KEYS})
    return out


class BoundedServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 16

    def __init__(self, *args, **kwargs):
        self.slots = threading.BoundedSemaphore(24)
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


def make_server(host, port, queue, allowed_hosts=None):
    auth.ensure_bootstrap()  # First run: create the default admin account.
    try:
        transcode.purge_all()  # Transcode sessions never survive a restart.
    except Exception:
        pass
    settings_path = os.path.join(
        os.environ.get('UAV_WEB_STATE_DIR', '/state'), 'settings.json')

    def load_settings():
        saved = {}
        try:
            with open(settings_path, encoding='utf-8') as stream:
                data = json.load(stream)
            if isinstance(data, dict):
                saved = data
        except (OSError, ValueError):
            saved = {}
        merged = dict(DEFAULT_SETTINGS)
        if type(saved.get('auto_rename')) is bool:
            merged['auto_rename'] = saved['auto_rename']
        if saved.get('file_mode') in ('preview', 'auto'):
            merged['file_mode'] = saved['file_mode']
        if isinstance(saved.get('lang'), str) and saved['lang']:
            merged['lang'] = saved['lang']
        return merged

    def save_settings(data):
        if set(data) - set(DEFAULT_SETTINGS):
            raise ValueError('Unknown settings')
        merged = load_settings()
        if 'auto_rename' in data:
            if type(data['auto_rename']) is not bool:
                raise ValueError('auto_rename must be a boolean')
            merged['auto_rename'] = data['auto_rename']
        if 'file_mode' in data:
            if data['file_mode'] not in ('preview', 'auto'):
                raise ValueError('file_mode must be preview or auto')
            merged['file_mode'] = data['file_mode']
        if 'lang' in data:
            if (not isinstance(data['lang'], str)
                    or not re.fullmatch(r'[A-Za-z-]{2,16}', data['lang'])):
                raise ValueError('lang must be a language tag')
            merged['lang'] = data['lang']
        os.makedirs(os.path.dirname(settings_path), exist_ok=True)
        temp = settings_path + '.tmp'
        with open(temp, 'w', encoding='utf-8') as stream:
            json.dump(merged, stream, ensure_ascii=False)
        os.replace(temp, settings_path)
        return merged

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.0'
        current_user = None      # Safe user dict, set by _auth/_auth_media.
        current_session = None   # Session token backing this request.

        def setup(self):
            super().setup()
            self.connection.settimeout(8)

        def log_message(self, *_args):
            pass  # Never log Authorization, attacker-controlled paths or token query strings.

        def _send(self, status, payload, kind='application/json; charset=utf-8', csp=None):
            if isinstance(payload, (dict, list)):
                payload = json.dumps(payload, ensure_ascii=True).encode()
            elif isinstance(payload, str):
                payload = payload.encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('X-Frame-Options', 'DENY')
            self.send_header('Content-Security-Policy', csp or
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "connect-src 'self'; img-src 'none'; frame-ancestors 'none'; "
                "base-uri 'none'; form-action 'none'; object-src 'none'")
            self.end_headers()
            self.wfile.write(payload)

        def _guard(self, allow_query=False):
            hosts = self.headers.get_all('Host', [])
            if len(hosts) != 1 or hosts[0].lower() not in self.server.allowed_hosts:
                self._send(403, {'error': 'Host is not allowed'})
                return False
            if not allow_query and ('?' in self.path or '#' in self.path):
                self._send(400, {'error': 'Query parameters are not accepted'})
                return False
            origin = self.headers.get('Origin')
            if origin:
                try:
                    parsed = urlsplit(origin)
                    valid = (parsed.scheme in {'http', 'https'} and parsed.netloc.lower() == hosts[0].lower()
                             and not parsed.path and not parsed.query and not parsed.fragment)
                except ValueError:
                    valid = False
                if not valid:
                    self._send(403, {'error': 'Cross-origin request denied'})
                    return False
            return True

        def _finish_auth(self, user, session_token):
            """Record who is calling; enforce the forced password change."""
            self.current_user = user
            self.current_session = session_token
            path = self.path.split('?', 1)[0].split('#', 1)[0]
            if user['must_change'] and path not in MUST_CHANGE_ALLOWED:
                self._send(403, {'error': 'must_change_password'})
                return False
            return True

        def _auth(self):
            values = self.headers.get_all('Authorization', [])
            value = values[0] if len(values) == 1 else ''
            supplied = value[7:] if value.startswith('Bearer ') else ''
            user = auth.lookup_session(supplied) if supplied else None
            if user is None:
                self._send(401, {'error': 'Authentication required'})
                return False
            return self._finish_auth(user, supplied)

        def _auth_media(self, params):
            # Media elements cannot set headers, so accept ?t=<session> too.
            values = self.headers.get_all('Authorization', [])
            supplied = ''
            if len(values) == 1 and values[0].startswith('Bearer '):
                supplied = values[0][7:]
            if not supplied:
                supplied = params.get('t', [''])[0]
            user = auth.lookup_session(supplied) if supplied else None
            if user is None:
                self._send(401, {'error': 'Authentication required'})
                return False
            return self._finish_auth(user, supplied)

        def _require_admin(self):
            if not self.current_user or self.current_user.get('role') != 'admin':
                self._send(403, {'error': '需要管理员权限'})
                return False
            return True

        def _do_login(self, data):
            if (set(data) != {'username', 'password'}
                    or not isinstance(data['username'], str)
                    or not isinstance(data['password'], str)):
                self._send(400, {'error': 'Expected username and password'})
                return
            username = data['username'].strip()
            remaining = auth.lock_remaining(username)
            if remaining > 0:
                minutes = max(1, -(-remaining // 60))
                self._send(429, {'error': f'尝试次数过多，请 {minutes} 分钟后重试'})
                return
            user = auth.authenticate(username, data['password'])
            if user is None:
                auth.record_failure(username)
                self._send(401, {'error': '用户名或密码不正确'})
                return
            auth.record_success(username)
            self._send(200, {'session': auth.create_session(username),
                             'username': user['username'],
                             'role': user['role'],
                             'must_change': user['must_change']})

        def _do_change_password(self, data):
            if (set(data) != {'old_password', 'new_password'}
                    or not isinstance(data['old_password'], str)
                    or not isinstance(data['new_password'], str)):
                self._send(400, {'error': 'Expected old_password and new_password'})
                return
            username = self.current_user['username']
            if not auth.check_password(username, data['old_password']):
                self._send(401, {'error': '当前密码不正确'})
                return
            if not auth.password_ok(data['new_password']):
                self._send(400, {'error': '新密码至少 8 位'})
                return
            auth.set_password(username, data['new_password'], must_change=False)
            self.current_user['must_change'] = False
            needs_onboarding = (self.current_user['role'] == 'admin'
                                and auth.user_count() == 1)
            self._send(200, {'ok': True, 'needs_onboarding': needs_onboarding})

        def _do_create_user(self, data):
            if (not set(data) <= {'username', 'password', 'role'}
                    or not isinstance(data.get('username'), str)
                    or not isinstance(data.get('password'), str)):
                self._send(400, {'error': 'Expected username and password'})
                return
            username = data['username'].strip()
            role = data.get('role', 'user')
            if not auth.valid_username(username):
                self._send(400, {'error': '用户名需为 1-32 个字符（字母、数字、_ . -）'})
                return
            if role not in ('admin', 'user'):
                self._send(400, {'error': '角色不正确'})
                return
            if not auth.password_ok(data['password']):
                self._send(400, {'error': '密码至少 8 位'})
                return
            if auth.get_user(username) is not None:
                self._send(409, {'error': '用户名已存在'})
                return
            user = auth.create_user(username, data['password'], role)
            self._send(200, {'ok': True, 'user': user})

        def _do_user_admin(self, data):
            """POST /api/users/reset | /api/users/delete | /api/users/role."""
            if self.path == '/api/users/reset':
                if (set(data) != {'username', 'new_password'}
                        or not isinstance(data['username'], str)
                        or not isinstance(data['new_password'], str)):
                    self._send(400, {'error': 'Expected username and new_password'})
                    return
                if auth.get_user(data['username']) is None:
                    self._send(404, {'error': '用户不存在'})
                    return
                if not auth.password_ok(data['new_password']):
                    self._send(400, {'error': '新密码至少 8 位'})
                    return
                auth.set_password(data['username'], data['new_password'],
                                  must_change=True)
                auth.revoke_user_sessions(data['username'])
                self._send(200, {'ok': True})
                return
            if self.path == '/api/users/delete':
                if set(data) != {'username'} or not isinstance(data['username'], str):
                    self._send(400, {'error': 'Expected username'})
                    return
                target = auth.get_user(data['username'])
                if target is None:
                    self._send(404, {'error': '用户不存在'})
                    return
                if data['username'] == self.current_user['username']:
                    self._send(400, {'error': '不能删除当前登录的账号'})
                    return
                if target['role'] == 'admin' and auth.admin_count() <= 1:
                    self._send(400, {'error': '不能删除最后一个管理员'})
                    return
                auth.delete_user(data['username'])
                self._send(200, {'ok': True})
                return
            # /api/users/role
            if (set(data) != {'username', 'role'}
                    or not isinstance(data['username'], str)
                    or data['role'] not in ('admin', 'user')):
                self._send(400, {'error': 'Expected username and role'})
                return
            target = auth.get_user(data['username'])
            if target is None:
                self._send(404, {'error': '用户不存在'})
                return
            if (target['role'] == 'admin' and data['role'] == 'user'
                    and auth.admin_count() <= 1):
                self._send(400, {'error': '不能取消最后一个管理员的管理员权限'})
                return
            auth.set_role(data['username'], data['role'])
            self._send(200, {'ok': True})

        def _handle_library(self):
            works = library.scan_library()
            self._send(200, {
                'works': works,
                'actresses': sorted({w['actress'] for w in works if w['actress']}),
                'folders': sorted({w['folder'] for w in works if w['folder']})})

        def _handle_library_tree(self, params):
            path = params.get('path', [''])[0].strip().strip('/')
            if path == '.':
                path = ''
            view = library.tree_view(path)
            if view is None:
                self._send(404, {'error': '目录不存在'})
                return
            self._send(200, view)

        def _handle_thumb(self, params):
            rel = params.get('rel', [''])[0]
            try:
                cached = thumbs.get_thumb(rel)
            except thumbs.ThumbBusy:
                self._send(503, {'error': '预览图生成繁忙，请稍后重试'})
                return
            if cached is None:
                self._send(404, {'error': 'Not found'})
                return
            try:
                payload = cached.read_bytes()
            except OSError:
                self._send(404, {'error': 'Not found'})
                return
            self.send_response(200)
            self.send_header('Content-Type', 'image/jpeg')
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Cache-Control', 'private, max-age=86400')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.end_headers()
            self.wfile.write(payload)

        def _handle_search(self, params):
            query = params.get('q', [''])[0].strip()
            site = params.get('site', ['jable'])[0].strip().lower() or 'jable'
            if not query:
                self._send(400, {'error': 'Missing search query'})
                return
            if site not in searchsvc.SITES:
                self._send(400, {'error': 'Unsupported site'})
                return
            urls = [job.get('url', '') for job in queue.snapshot()['jobs']]
            try:
                codes = library.code_index()
            except Exception:
                codes = set()
            self._send(200, searchsvc.search(site, query, urls, codes))

        def _send_media(self, target, content_type, allow_range):
            size = os.path.getsize(target)
            start, end, status = 0, size - 1, 200
            header = self.headers.get('Range') if allow_range else None
            if header:
                match = re.fullmatch(r'bytes=(\d*)-(\d*)', header.strip())
                if match and match.groups() != ('', ''):
                    first, last = match.groups()
                    if first == '':
                        start = max(0, size - int(last))
                    else:
                        start = int(first)
                        end = min(int(last), size - 1) if last else size - 1
                    if size == 0 or start >= size or start > end:
                        self.send_response(416)
                        self.send_header('Content-Range', f'bytes */{size}')
                        self.send_header('Content-Length', '0')
                        self.end_headers()
                        return
                    status = 206
            length = max(0, end - start + 1) if size else 0
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(length))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            if allow_range:
                self.send_header('Accept-Ranges', 'bytes')
            if status == 206:
                self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
            self.end_headers()
            if not length:
                return
            try:
                with open(target, 'rb') as stream:
                    stream.seek(start)
                    remaining = length
                    while remaining > 0:
                        chunk = stream.read(min(256 * 1024, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        self.wfile.flush()
                        remaining -= len(chunk)
            except OSError:
                pass  # Client went away mid-stream; nothing useful to report.

        def _handle_media(self, path, params):
            rel = params.get('rel', [''])[0]
            target = library.resolve_stream(rel)
            if not target:
                self._send(404, {'error': 'Not found'})
                return
            extension = os.path.splitext(target)[1].lower()
            if path == '/api/cover':
                content_type = IMAGE_TYPES.get(extension)
                if not content_type:
                    self._send(404, {'error': 'Not found'})
                    return
                self._send_media(target, content_type, allow_range=False)
            else:
                self._send_media(target,
                                 VIDEO_TYPES.get(extension, 'application/octet-stream'),
                                 allow_range=True)

        def _handle_play_info(self, params):
            rel = params.get('rel', [''])[0]
            if not library.resolve_stream(rel):
                self._send(404, {'error': 'Not found'})
                return
            result = probe.probe(rel)
            result['mode'] = 'direct' if result.get('direct') else 'transcode'
            self._send(200, result)

        def _handle_hls(self, path, params):
            parts = path[len('/api/hls/'):].split('/')
            if len(parts) != 2:
                self._send(404, {'error': 'Not found'})
                return
            session_id, filename = parts
            session = transcode.get(session_id)
            if (session is None or not HLS_FILE_RE.match(filename)):
                self._send(404, {'error': 'Not found'})
                return
            transcode.touch(session_id)
            target = session['dir'] / filename
            if filename == 'index.m3u8':
                # ffmpeg writes the playlist shortly after spawn; wait a
                # little instead of making the player retry on a 404.
                deadline = time.monotonic() + 5
                while not target.is_file() and time.monotonic() < deadline:
                    time.sleep(0.1)
            if not target.is_file():
                self._send(404, {'error': 'Not found'})
                return
            try:
                payload = target.read_bytes()
            except OSError:
                self._send(404, {'error': 'Not found'})
                return
            if filename == 'index.m3u8':
                # hls.js and Safari resolve segment URLs relative to the
                # playlist URL and drop its query string, so bake the
                # media token into the segment lines themselves.
                token = params.get('t', [''])[0]
                if token:
                    suffix = '?t=' + quote(token, safe='')
                    lines = payload.decode('utf-8', 'replace').splitlines()
                    payload = ('\n'.join(
                        line + suffix if line and not line.startswith('#')
                        and line.endswith('.ts') else line
                        for line in lines) + '\n').encode('utf-8')
                content_type = 'application/vnd.apple.mpegurl'
            else:
                content_type = 'video/mp2t'
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.end_headers()
            self.wfile.write(payload)

        def _do_play_start(self, data):
            if (not set(data) <= {'rel', 't'}
                    or not isinstance(data.get('rel'), str)
                    or not data.get('rel')):
                self._send(400, {'error': 'Expected rel and optional t'})
                return
            offset = data.get('t', 0)
            if (isinstance(offset, bool)
                    or not isinstance(offset, (int, float)) or offset < 0):
                self._send(400, {'error': 't must be a non-negative number'})
                return
            rel = data['rel']
            if not library.resolve_stream(rel):
                self._send(404, {'error': 'Not found'})
                return
            try:
                session = transcode.start(rel, float(offset))
            except ValueError as exc:
                if str(exc) == 'busy':
                    self._send(503, {'error': '转码繁忙，请稍后再试'})
                    return
                if str(exc) == 'not_found':
                    self._send(404, {'error': 'Not found'})
                    return
                raise
            info = probe.probe(rel)
            self._send(200, {
                'session': session['id'],
                'playlist': f"/api/hls/{session['id']}/index.m3u8",
                'offset': session['offset'],
                'encoder': session['encoder'],
                'duration': info.get('duration', 0.0)})

        def _do_play_stop(self, data):
            if set(data) != {'session'} or not isinstance(data['session'], str):
                self._send(400, {'error': 'Expected only session'})
                return
            transcode.stop(data['session'])
            self._send(200, {'ok': True})

        def do_GET(self):
            path = self.path.split('?', 1)[0].split('#', 1)[0]
            if path.startswith('/api/hls/'):
                if not self._guard(allow_query=True):
                    return
                try:
                    params = parse_qs(urlsplit(self.path).query)
                except ValueError:
                    self._send(400, {'error': 'Invalid query string'})
                    return
                if self._auth_media(params):
                    self._handle_hls(path, params)
                return
            if path in QUERY_GET_PATHS:
                if not self._guard(allow_query=True):
                    return
                try:
                    params = parse_qs(urlsplit(self.path).query)
                except ValueError:
                    self._send(400, {'error': 'Invalid query string'})
                    return
                if path in ('/api/stream', '/api/cover'):
                    if self._auth_media(params):
                        self._handle_media(path, params)
                elif path == '/api/thumb':
                    if self._auth_media(params):
                        self._handle_thumb(params)
                elif path == '/api/play/info':
                    if self._auth_media(params):
                        self._handle_play_info(params)
                elif path == '/api/library':
                    if self._auth():
                        self._handle_library()
                elif path == '/api/library/tree':
                    if self._auth():
                        self._handle_library_tree(params)
                elif path == '/api/library/actresses':
                    if self._auth():
                        self._send(200, {'actresses': library.actress_dirs()})
                elif path == '/api/search':
                    if self._auth():
                        self._handle_search(params)
                elif self._auth():
                    self._send(200, load_settings())
                return
            if not self._guard():
                return
            static = {'/': (HTML, 'text/html; charset=utf-8'),
                      '/app.css': (CSS, 'text/css; charset=utf-8'),
                      '/app.js': (JS, 'text/javascript; charset=utf-8')}
            if HLS_JS is not None:
                static['/hls.min.js'] = (HLS_JS,
                                         'application/javascript; charset=utf-8')
            if self.path in static:
                if self.path == '/':
                    self._send(200, HTML, 'text/html; charset=utf-8', csp=PAGE_CSP)
                else:
                    self._send(200, *static[self.path])
            elif self.path == '/api/queue' and self._auth():
                self._send(200, _enrich_snapshot(queue.snapshot()))
            elif self.path == '/api/backfill':
                if self._auth():
                    self._send(200, {'intents': backfill.load_intents()})
            elif self.path == '/api/me':
                if self._auth():
                    self._send(200, self.current_user)
            elif self.path == '/api/users':
                if self._auth() and self._require_admin():
                    self._send(200, {'users': auth.list_users()})
            elif self.path == '/api/actress/list':
                if self._auth():
                    self._send(200, {'actresses': actress.library_actresses()})
            elif self.path in ('/api/postprocess', '/api/organize'):
                if self._auth():
                    if self.path == '/api/postprocess':
                        self._send(200, {'plans': postprocess.load_plans()})
                    else:
                        self._send(200, organize.state_view())
            elif self.path != '/api/queue':
                self._send(404, {'error': 'Not found'})

        def do_POST(self):
            if not self._guard():
                return
            try:
                lengths = self.headers.get_all('Content-Length', [])
                if self.headers.get('Transfer-Encoding') or len(lengths) != 1:
                    raise ValueError('Content-Length is required; chunked bodies are not accepted')
                size = int(lengths[0])
                if not 0 < size <= MAX_BODY:
                    self._send(413, {'error': 'Request is too large or empty'})
                    return
                if self.headers.get_content_type() != 'application/json':
                    raise ValueError('Use application/json')
                raw = self.rfile.read(size)
                if len(raw) != size:
                    raise ValueError('Incomplete request body')
                data = json.loads(raw.decode('utf-8'))
                if not isinstance(data, dict):
                    raise ValueError('Expected an object')
                if self.path == '/api/login':
                    self._do_login(data)
                    return
                if not self._auth():
                    return
                if self.path == '/api/logout':
                    auth.revoke_session(self.current_session)
                    self._send(200, {'ok': True})
                    return
                if self.path == '/api/change-password':
                    self._do_change_password(data)
                    return
                if self.path == '/api/play/start':
                    self._do_play_start(data)
                    return
                if self.path == '/api/play/stop':
                    self._do_play_stop(data)
                    return
                if self.path == '/api/users':
                    if self._require_admin():
                        self._do_create_user(data)
                    return
                if self.path in ('/api/users/reset', '/api/users/delete',
                                  '/api/users/role'):
                    if self._require_admin():
                        self._do_user_admin(data)
                    return
                if self.path == '/api/queue':
                    if set(data) != {'jobs'}:
                        raise ValueError('Expected only jobs')
                    self._send(201, {'jobs': _enrich_jobs(queue.add(data['jobs']))})
                    return
                if self.path == '/api/backfill/plan':
                    if not set(data) <= {'items', 'actress_hint'}:
                        raise ValueError('Expected items and optional actress_hint')
                    hint = data.get('actress_hint')
                    if hint is not None and not isinstance(hint, str):
                        raise ValueError('actress_hint must be a string')
                    self._send(200, backfill.plan(
                        _backfill_items(data), hint, queue.snapshot()))
                    return
                if self.path == '/api/backfill/start':
                    if not set(data) <= {'items', 'actress_hint'}:
                        raise ValueError('Expected items and optional actress_hint')
                    hint = data.get('actress_hint')
                    if hint is not None and not isinstance(hint, str):
                        raise ValueError('actress_hint must be a string')
                    self._send(200, backfill.start(
                        _backfill_items(data), queue, hint))
                    return
                if self.path == '/api/settings':
                    self._send(200, save_settings(data))
                    return
                if self.path == '/api/actress/gap':
                    if set(data) != {'name'} or not isinstance(data['name'], str):
                        raise ValueError('Expected only name')
                    self._send(200, actress.gap(data['name'], queue.snapshot()))
                    return
                if self.path == '/api/postprocess/execute':
                    self._send(200, {'results': postprocess.execute(_id_list(data)),
                                     'plans': postprocess.load_plans()})
                    return
                if self.path == '/api/postprocess/dismiss':
                    self._send(200, {'plans': postprocess.dismiss(_id_list(data))})
                    return
                if self.path == '/api/organize/scan':
                    if set(data) != {'scope'} or data['scope'] not in organize.SCOPES:
                        raise ValueError('Expected a valid scope')
                    self._send(200, organize.scan(data['scope']))
                    return
                if self.path == '/api/organize/execute':
                    self._send(200, {'results': organize.execute(_id_list(data)),
                                     **organize.state_view()})
                    return
                if self.path == '/api/organize/rollback':
                    self._send(200, {'result': organize.rollback(_id_list(data, required=False)),
                                     **organize.state_view()})
                    return
                if self.path in {'/api/resume', '/api/clear'}:
                    if data:
                        raise ValueError('Expected an empty object')
                    (queue.resume if self.path == '/api/resume' else queue.clear)()
                elif self.path in {'/api/cancel', '/api/retry'}:
                    if set(data) != {'id'} or not isinstance(data['id'], str):
                        raise ValueError('Expected only id')
                    (queue.cancel if self.path == '/api/cancel' else queue.retry)(data['id'])
                else:
                    self._send(404, {'error': 'Not found'})
                    return
                self._send(200, _enrich_snapshot(queue.snapshot()))
            except KeyError:
                self._send(404, {'error': 'Job not found'})
            except StorageWriteError:
                self._send(503, {'error': 'Storage failed; queue halted. Check disk health before resuming.'})
            except (ValueError, UnicodeError, TypeError, RecursionError):
                self._send(400, {'error': 'Invalid request or unsupported URL/settings'})
            except OSError:
                self._send(503, {'error': 'I/O unavailable'})

    server = BoundedServer((host, port), Handler)
    actual_port = server.server_port
    defaults = {f'localhost:{actual_port}', f'127.0.0.1:{actual_port}'}
    if host not in {'0.0.0.0', '::', ''}:
        defaults.add(f'{host.lower()}:{actual_port}')
    server.allowed_hosts = {value.lower() for value in (allowed_hosts or defaults)}
    return server
