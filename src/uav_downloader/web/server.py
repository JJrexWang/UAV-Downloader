"""Small same-origin authenticated HTTP surface, deliberately not a file server."""
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import re
import threading
from urllib.parse import parse_qs, urlsplit

from uav_downloader.core.storage import StorageWriteError
from . import actress, library, organize, postprocess, searchsvc
from .ui import HTML, CSS, JS


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
            "connect-src 'self'; img-src 'self' https: data:; media-src 'self'; "
            "frame-ancestors 'none'; base-uri 'none'; form-action 'none'; object-src 'none'")
VIDEO_TYPES = {'.mp4': 'video/mp4', '.mkv': 'video/x-matroska',
               '.avi': 'video/x-msvideo', '.mov': 'video/quicktime',
               '.wmv': 'video/x-ms-wmv', '.ts': 'video/mp2t',
               '.m2ts': 'video/mp2t', '.webm': 'video/webm'}
IMAGE_TYPES = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
               '.png': 'image/png', '.webp': 'image/webp', '.gif': 'image/gif'}
QUERY_GET_PATHS = {'/api/search', '/api/library', '/api/settings',
                   '/api/stream', '/api/cover'}


def validate_token(value):
    # A length check cannot prove randomness; documentation mandates secrets.token_urlsafe.
    if (not isinstance(value, str) or not 32 <= len(value) <= 256
            or len(set(value)) < 12 or not re.fullmatch(r'[A-Za-z0-9_-]+', value)):
        raise ValueError('UAV_WEB_TOKEN must be a random URL-safe token of at least 32 characters')
    return value


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


def make_server(host, port, token, queue, allowed_hosts=None):
    digest = hashlib.sha256(validate_token(token).encode()).digest()
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

        def _token_ok(self, supplied):
            return hmac.compare_digest(
                hashlib.sha256((supplied or '').encode()).digest(), digest)

        def _auth(self):
            values = self.headers.get_all('Authorization', [])
            value = values[0] if len(values) == 1 else ''
            supplied = value[7:] if value.startswith('Bearer ') else ''
            if not self._token_ok(supplied):
                self._send(401, {'error': 'Authentication required'})
                return False
            return True

        def _auth_media(self, params):
            # Media elements cannot set headers, so accept ?t=<token> as well.
            values = self.headers.get_all('Authorization', [])
            if (len(values) == 1 and values[0].startswith('Bearer ')
                    and self._token_ok(values[0][7:])):
                return True
            if self._token_ok(params.get('t', [''])[0]):
                return True
            self._send(401, {'error': 'Authentication required'})
            return False

        def _handle_library(self):
            works = library.scan_library()
            self._send(200, {
                'works': works,
                'actresses': sorted({w['actress'] for w in works if w['actress']}),
                'folders': sorted({w['folder'] for w in works if w['folder']})})

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

        def do_GET(self):
            path = self.path.split('?', 1)[0].split('#', 1)[0]
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
                elif path == '/api/library':
                    if self._auth():
                        self._handle_library()
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
            if self.path in static:
                if self.path == '/':
                    self._send(200, HTML, 'text/html; charset=utf-8', csp=PAGE_CSP)
                else:
                    self._send(200, *static[self.path])
            elif self.path == '/api/queue' and self._auth():
                self._send(200, queue.snapshot())
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
            if not self._guard() or not self._auth():
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
                if self.path == '/api/queue':
                    if set(data) != {'jobs'}:
                        raise ValueError('Expected only jobs')
                    self._send(201, {'jobs': queue.add(data['jobs'])})
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
                self._send(200, queue.snapshot())
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
