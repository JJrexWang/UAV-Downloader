"""Phase 9: probe verdicts and on-demand HLS transcoding over HTTP."""
import json
from pathlib import Path
import subprocess
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from uav_downloader.web import probe, transcode
from uav_downloader.web.queue import QueueManager
from uav_downloader.web.server import make_server

TEST_PASSWORD = 'test-password-123'
TOKEN = ''


def request(base, path, data=None, timeout=10, **headers):
    raw = None if data is None else json.dumps(data).encode()
    req = Request(base + path, data=raw, headers={
        'Content-Type': 'application/json', **headers})
    try:
        response = urlopen(req, timeout=timeout)
    except HTTPError as exc:
        response = exc
    with response:
        return response.status, response.headers, response.read()


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv('UAV_WEB_STATE_DIR', str(tmp_path / 'state'))
    monkeypatch.setenv('LIBRARY_DIR', str(tmp_path / 'library'))
    monkeypatch.setenv('DOWNLOAD_DIR', str(tmp_path / 'downloads'))
    (tmp_path / 'library').mkdir()
    return tmp_path


@pytest.fixture
def web(env, tmp_path):
    global TOKEN
    q = QueueManager(tmp_path / 'downloads', tmp_path / 'state',
                     autostart=False)
    server = make_server('127.0.0.1', 0, q)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    status, _, body = request(base, '/api/login',
                              {'username': 'admin', 'password': 'admin'})
    assert status == 200
    session = json.loads(body)['session']
    status, _, _ = request(
        base, '/api/change-password',
        {'old_password': 'admin', 'new_password': TEST_PASSWORD},
        Authorization=f'Bearer {session}')
    assert status == 200
    TOKEN = session
    yield base, q
    transcode.purge_all()
    server.shutdown()
    server.server_close()
    q.close()


def _ffmpeg(args):
    subprocess.run(['ffmpeg', '-v', 'error', *args], check=True, timeout=120)


@pytest.fixture
def media(env):
    library = env / 'library'
    _ffmpeg(['-f', 'lavfi', '-i', 'testsrc2=duration=3:size=320x240:rate=10',
             '-f', 'lavfi', '-i', 'sine=frequency=440:duration=3',
             '-c:v', 'libx264', '-preset', 'ultrafast', '-c:a', 'aac',
             '-shortest', '-y', str(library / 'direct.mp4')])
    _ffmpeg(['-f', 'lavfi', '-i', 'testsrc2=duration=3:size=320x240:rate=10',
             '-f', 'lavfi', '-i', 'sine=frequency=440:duration=3',
             '-c:v', 'libx265', '-preset', 'ultrafast', '-c:a', 'ac3',
             '-shortest', '-y', str(library / 'hard.mkv')])
    return library


def _fake(fmt, video_codec, audio_codecs):
    streams = []
    if video_codec:
        streams.append({'codec_type': 'video', 'codec_name': video_codec,
                        'width': 1920, 'height': 1080})
    for codec in audio_codecs:
        streams.append({'codec_type': 'audio', 'codec_name': codec})
    return {'format': {'format_name': fmt, 'duration': '123.5'},
            'streams': streams}


def _probe_with(env, monkeypatch, name, fake):
    (env / 'library' / name).write_bytes(b'x')
    monkeypatch.setattr(probe, '_ffprobe_json', lambda target: fake)
    return probe.probe(name)


def test_probe_direct_mp4_h264_aac(env, monkeypatch):
    result = _probe_with(env, monkeypatch, 'a.mp4',
                         _fake('mov,mp4,m4a,3gp,3g2,mj2', 'h264', ['aac']))
    assert result['direct'] is True
    assert result['mode'] == 'direct'
    assert result['reason'] == ''
    assert result['duration'] == 123.5
    assert result['video'] == {'codec': 'h264', 'width': 1920, 'height': 1080}
    assert result['audio'] == ['aac']


def test_probe_mkv_hevc_ac3_transcodes(env, monkeypatch):
    result = _probe_with(env, monkeypatch, 'b.mkv',
                         _fake('matroska,webm', 'hevc', ['ac3']))
    assert result['direct'] is False
    assert result['mode'] == 'transcode'
    assert result['reason'] == 'container:mkv'


def test_probe_mp4_hevc_transcodes(env, monkeypatch):
    result = _probe_with(env, monkeypatch, 'c.mp4',
                         _fake('mov,mp4,m4a,3gp,3g2,mj2', 'hevc', ['aac']))
    assert result['direct'] is False
    assert result['reason'] == 'video:hevc'


def test_probe_mp4_h264_ac3_transcodes(env, monkeypatch):
    result = _probe_with(env, monkeypatch, 'd.mp4',
                         _fake('mov,mp4,m4a,3gp,3g2,mj2', 'h264', ['ac3']))
    assert result['direct'] is False
    assert result['reason'] == 'audio:ac3'


def test_probe_failure_transcodes(env, monkeypatch):
    result = _probe_with(env, monkeypatch, 'e.mp4', None)
    assert result['direct'] is False
    assert result['mode'] == 'transcode'
    assert result['reason'] == 'probe_failed'


def test_play_info_verdicts(web, media):
    base, _ = web
    status, _, body = request(base, f'/api/play/info?rel=direct.mp4&t={TOKEN}')
    assert status == 200
    info = json.loads(body)
    assert info['direct'] is True and info['mode'] == 'direct'
    assert info['video']['codec'] == 'h264' and info['audio'] == ['aac']
    status, _, body = request(base, f'/api/play/info?rel=hard.mkv&t={TOKEN}')
    assert status == 200
    info = json.loads(body)
    assert info['direct'] is False and info['mode'] == 'transcode'
    assert info['reason'] == 'container:mkv'
    assert request(base, '/api/play/info?rel=hard.mkv')[0] == 401
    assert request(base, f'/api/play/info?rel=missing.mp4&t={TOKEN}')[0] == 404


def _get_playlist(base, session_id, timeout=20):
    deadline = time.monotonic() + timeout
    body = b''
    while time.monotonic() < deadline:
        status, _, body = request(
            base, f'/api/hls/{session_id}/index.m3u8?t={TOKEN}')
        if status == 200 and b'seg' in body:
            return body.decode('utf-8')
        time.sleep(0.25)
    raise AssertionError(f'playlist never ready: {body!r}')


def test_transcode_hls_flow(web, media, env):
    base, _ = web
    auth = {'Authorization': 'Bearer ' + TOKEN}
    status, _, body = request(base, '/api/play/start',
                              {'rel': 'hard.mkv', 't': 0}, **auth)
    assert status == 200
    started = json.loads(body)
    session_id = started['session']
    assert len(session_id) == 16
    expected = ('vaapi' if Path('/dev/dri/renderD128').exists()
                else 'libx264')
    assert started['encoder'] == expected
    assert started['offset'] == 0
    assert started['duration'] > 0
    assert started['playlist'] == f'/api/hls/{session_id}/index.m3u8'

    playlist = _get_playlist(base, session_id)
    seg_lines = [line for line in playlist.splitlines()
                 if line and not line.startswith('#')]
    assert seg_lines, playlist
    assert all(f'?t={TOKEN}' in line for line in seg_lines)
    seg_name = seg_lines[0].split('?')[0]

    status, headers, payload = request(
        base, f'/api/hls/{session_id}/{seg_name}?t={TOKEN}')
    assert status == 200
    assert headers['Content-Type'] == 'video/mp2t'
    assert len(payload) > 1024
    seg_file = env / 'segment.ts'
    seg_file.write_bytes(payload)
    probed = json.loads(subprocess.run(
        ['ffprobe', '-v', 'error', '-show_streams', '-of', 'json',
         str(seg_file)], stdout=subprocess.PIPE, check=True).stdout)
    codecs = {s['codec_type']: s['codec_name'] for s in probed['streams']}
    assert codecs['video'] == 'h264'
    assert codecs['audio'] == 'aac'

    # The short source finishes quickly; ffmpeg must close the event
    # playlist with ENDLIST so players see the true end.
    deadline = time.monotonic() + 20
    while '#EXT-X-ENDLIST' not in playlist and time.monotonic() < deadline:
        time.sleep(0.5)
        playlist = _get_playlist(base, session_id, timeout=5)
    assert '#EXT-X-ENDLIST' in playlist

    # Seek-restart: a fresh session at an offset.
    status, _, body = request(base, '/api/play/start',
                              {'rel': 'hard.mkv', 't': 1}, **auth)
    assert status == 200
    seek = json.loads(body)
    assert seek['offset'] == 1
    assert seek['session'] != session_id

    session_dir = env / 'state' / 'transcode' / session_id
    assert session_dir.is_dir()
    status, _, _ = request(base, '/api/play/stop',
                           {'session': session_id}, **auth)
    assert status == 200
    assert not session_dir.exists()
    request(base, '/api/play/stop', {'session': seek['session']}, **auth)


def test_hls_rejects_bogus_and_traversal(web, media):
    base, _ = web
    auth = {'Authorization': 'Bearer ' + TOKEN}
    assert request(base, f'/api/hls/deadbeefdeadbeef/index.m3u8?t={TOKEN}')[0] == 404
    assert request(base, '/api/hls/deadbeefdeadbeef/index.m3u8')[0] == 401
    status, _, body = request(base, '/api/play/start',
                              {'rel': 'hard.mkv', 't': 0}, **auth)
    assert status == 200
    session_id = json.loads(body)['session']
    try:
        assert request(base, f'/api/hls/{session_id}/evil.ts?t={TOKEN}')[0] == 404
        assert request(base, f'/api/hls/{session_id}/seg00000.txt?t={TOKEN}')[0] == 404
        assert request(base, f'/api/hls/{session_id}/../../secret?t={TOKEN}')[0] == 404
        assert request(base, f'/api/hls/{session_id}/..%2fseg00000.ts?t={TOKEN}')[0] == 404
        assert request(base, f'/api/hls/nothexatall1234/index.m3u8?t={TOKEN}')[0] == 404
    finally:
        request(base, '/api/play/stop', {'session': session_id}, **auth)


def test_transcode_session_cap(web, media):
    base, _ = web
    auth = {'Authorization': 'Bearer ' + TOKEN}
    started = []
    try:
        for _ in range(transcode.MAX_SESSIONS):
            status, _, body = request(base, '/api/play/start',
                                      {'rel': 'hard.mkv', 't': 0}, **auth)
            assert status == 200
            started.append(json.loads(body)['session'])
        status, _, body = request(base, '/api/play/start',
                                  {'rel': 'hard.mkv', 't': 0}, **auth)
        assert status == 503
        assert '转码繁忙' in json.loads(body)['error']
    finally:
        for session_id in started:
            request(base, '/api/play/stop', {'session': session_id}, **auth)


def test_hls_js_vendored_and_csp_blob(web):
    base, _ = web
    status, headers, body = request(base, '/')
    assert status == 200
    assert "media-src 'self' blob:" in headers['Content-Security-Policy']
    status, headers, body = request(base, '/hls.min.js')
    assert status == 200
    assert 'javascript' in headers['Content-Type']
    assert len(body) > 100_000
