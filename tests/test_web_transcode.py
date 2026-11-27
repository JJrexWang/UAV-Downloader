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
    if not Path('/dev/dri/renderD128').exists():
        assert started['vaapi_state'] == 'no_device'
        assert started['vaapi_error'] is None

    playlist = _get_playlist(base, session_id)
    # The playlist is server-generated: a complete VOD list from the
    # first request, not an event list that grows with the transcode.
    assert '#EXT-X-PLAYLIST-TYPE:VOD' in playlist
    assert '#EXT-X-ENDLIST' in playlist
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

    # A fresh session can also be started at an offset.
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


@pytest.fixture
def media_long(env):
    library = env / 'library'
    _ffmpeg(['-f', 'lavfi', '-i', 'testsrc2=duration=26:size=320x240:rate=10',
             '-f', 'lavfi', '-i', 'sine=frequency=440:duration=26',
             '-c:v', 'libx265', '-preset', 'ultrafast', '-c:a', 'ac3',
             '-shortest', '-y', str(library / 'long.mkv')])
    return library


def test_vod_playlist_matches_duration(web, media_long):
    base, _ = web
    auth = {'Authorization': 'Bearer ' + TOKEN}
    status, _, body = request(base, '/api/play/start',
                              {'rel': 'long.mkv', 't': 0}, **auth)
    assert status == 200
    started = json.loads(body)
    session_id = started['session']
    try:
        status, _, body = request(
            base, f'/api/hls/{session_id}/index.m3u8?t={TOKEN}')
        assert status == 200
        playlist = body.decode('utf-8')
        assert '#EXT-X-PLAYLIST-TYPE:VOD' in playlist
        assert playlist.rstrip().endswith('#EXT-X-ENDLIST')
        extinf = [float(line.split(':', 1)[1].rstrip(','))
                  for line in playlist.splitlines()
                  if line.startswith('#EXTINF:')]
        # ceil(26/4) = 7 segments whose lengths sum to the duration.
        assert len(extinf) == transcode.segment_count(started['duration'])
        assert len(extinf) == 7
        assert abs(sum(extinf) - started['duration']) < 0.01
        seg_lines = [line for line in playlist.splitlines()
                     if line and not line.startswith('#')]
        assert seg_lines == [f'seg{i:05d}.ts?t={TOKEN}' for i in range(7)]
    finally:
        request(base, '/api/play/stop', {'session': session_id}, **auth)


@pytest.fixture
def media_colors(env):
    library = env / 'library'
    _ffmpeg(['-f', 'lavfi', '-i',
             'color=c=red:duration=30:size=320x240:rate=10',
             '-f', 'lavfi', '-i',
             'color=c=green:duration=30:size=320x240:rate=10',
             '-f', 'lavfi', '-i',
             'color=c=blue:duration=30:size=320x240:rate=10',
             '-f', 'lavfi', '-i', 'sine=frequency=440:duration=90',
             '-filter_complex', '[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]',
             '-map', '[v]', '-map', '3:a',
             '-c:v', 'libx264', '-preset', 'ultrafast', '-c:a', 'ac3',
             '-shortest', '-y', str(library / 'colors.mkv')])
    return library


def _frame_rgb(tmp_path, name, payload):
    src = tmp_path / name
    src.write_bytes(payload)
    out = tmp_path / (name + '.rgb')
    subprocess.run(['ffmpeg', '-v', 'error', '-i', str(src),
                    '-frames:v', '1', '-vf', 'scale=1:1',
                    '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-y', str(out)],
                   check=True, timeout=60)
    data = out.read_bytes()
    return data[0], data[1], data[2]


def test_segment_position_true(web, media_colors, tmp_path):
    """Segments carry the content of their absolute position.

    colors.mkv is red (0-30s) / green (30-60s) / blue (60-90s).  Asking
    for segment 11 (44-48s) first must restart ffmpeg at that index and
    serve green content; segment 0 must be red.  This only passes if
    -copyts and the forced-keyframe grid keep runs on the absolute
    timeline.
    """
    base, _ = web
    auth = {'Authorization': 'Bearer ' + TOKEN}
    status, _, body = request(base, '/api/play/start',
                              {'rel': 'colors.mkv', 't': 0}, **auth)
    assert status == 200
    session_id = json.loads(body)['session']
    try:
        status, _, payload = request(
            base, f'/api/hls/{session_id}/seg00011.ts?t={TOKEN}',
            timeout=60)
        assert status == 200
        r, g, b = _frame_rgb(tmp_path, 'seg11.ts', payload)
        assert g > r and g > b, (r, g, b)
        status, _, payload = request(
            base, f'/api/hls/{session_id}/seg00000.ts?t={TOKEN}',
            timeout=60)
        assert status == 200
        r, g, b = _frame_rgb(tmp_path, 'seg0.ts', payload)
        assert r > g and r > b, (r, g, b)
    finally:
        request(base, '/api/play/stop', {'session': session_id}, **auth)


def test_stop_preserves_ffmpeg_logs(web, media, env):
    base, _ = web
    auth = {'Authorization': 'Bearer ' + TOKEN}
    status, _, body = request(base, '/api/play/start',
                              {'rel': 'hard.mkv', 't': 0}, **auth)
    assert status == 200
    session_id = json.loads(body)['session']
    status, _, _ = request(
        base, f'/api/hls/{session_id}/seg00000.ts?t={TOKEN}', timeout=60)
    assert status == 200
    status, _, _ = request(base, '/api/play/stop',
                           {'session': session_id}, **auth)
    assert status == 200
    assert not (env / 'state' / 'transcode' / session_id).exists()
    preserved = list((env / 'state' / 'transcode-logs').glob(
        f'{session_id}-*ffmpeg.log'))
    assert preserved, 'ffmpeg log was not preserved on stop'


def test_hls_js_vendored_and_csp_blob(web):
    base, _ = web
    status, headers, body = request(base, '/')
    assert status == 200
    assert "media-src 'self' blob:" in headers['Content-Security-Policy']
    status, headers, body = request(base, '/hls.min.js')
    assert status == 200
    assert 'javascript' in headers['Content-Type']
    assert len(body) > 100_000


# --- Phase 9.2: tiered encoder strategy ---------------------------------
# Tier 1 = full VAAPI (hw decode + hw encode), tier 2 = hybrid (sw
# decode + VAAPI encode), tier 3 = libx264.  The sandbox has no render
# node, so sessions still land on tier 3 end to end; the tier plan and
# command builders are unit-tested directly.

def test_tier_plan_vaapi_decodable_codecs():
    for codec in ('h264', 'hevc', 'vp9', 'vp8', 'av1', 'mpeg2video',
                  'vc1', 'mjpeg'):
        assert transcode.tier_plan(codec) == [1, 2, 3]
    # Codec names are normalized (case/space) before the lookup.
    assert transcode.tier_plan('HEVC') == [1, 2, 3]
    assert transcode.tier_plan(' h264 ') == [1, 2, 3]


def test_tier_plan_software_decode_codecs():
    # MPEG-4 ASP and friends cannot be VAAPI-decoded at all, so the
    # full-VAAPI tier is skipped and the plan starts at the hybrid.
    for codec in ('mpeg4', 'msmpeg4v3', 'wmv3', 'rv40', 'theora',
                  'unknown', ''):
        assert transcode.tier_plan(codec) == [2, 3]
    assert transcode.tier_plan(None) == [2, 3]


def test_available_plan_no_device_is_software_only():
    if Path(transcode._VAAPI_DEVICE).exists():
        pytest.skip('render node present in this environment')
    assert transcode._available_plan('hevc') == [3]
    assert transcode._available_plan('mpeg4') == [3]


def _bare_session(tmp_path):
    return {'target': tmp_path / 'in.mkv', 'dir': tmp_path}


def _vf_arg(cmd):
    return cmd[cmd.index('-vf') + 1]


def test_build_command_tier1_full_vaapi(tmp_path):
    cmd = transcode._build_command(_bare_session(tmp_path), 3, 1)
    assert cmd[cmd.index('-hwaccel') + 1] == 'vaapi'
    assert cmd[cmd.index('-hwaccel_device') + 1] == '/dev/dri/renderD128'
    assert '-hwaccel_output_format' in cmd
    assert '-vaapi_device' not in cmd
    assert 'scale_vaapi' in _vf_arg(cmd)
    assert cmd[cmd.index('-c:v') + 1] == 'h264_vaapi'
    assert '-force_key_frames' in cmd


def test_build_command_tier2_hybrid(tmp_path):
    cmd = transcode._build_command(_bare_session(tmp_path), 3, 2)
    # Software decode: no -hwaccel anywhere; the device is only opened
    # so frames can be uploaded for VAAPI encoding.
    assert '-hwaccel' not in cmd
    assert '-hwaccel_device' not in cmd
    assert cmd[cmd.index('-vaapi_device') + 1] == '/dev/dri/renderD128'
    vf = _vf_arg(cmd)
    assert vf.startswith("scale=w=-2:h='min(1080,ih)'")
    assert 'format=nv12,hwupload' in vf
    assert 'scale_vaapi' not in vf
    assert cmd[cmd.index('-c:v') + 1] == 'h264_vaapi'
    assert cmd[cmd.index('-b:v') + 1] == '8M'
    assert '-force_key_frames' in cmd


def test_build_command_tier3_software(tmp_path):
    cmd = transcode._build_command(_bare_session(tmp_path), 0, 3)
    assert '-hwaccel' not in cmd
    assert '-vaapi_device' not in cmd
    assert 'hwupload' not in _vf_arg(cmd)
    assert cmd[cmd.index('-c:v') + 1] == 'libx264'
    assert '-force_key_frames' in cmd


def test_spawn_env_gpu_tiers_pin_ihd():
    for tier in (1, 2):
        env = transcode._spawn_env(tier)
        assert env is not None
        assert env['LIBVA_DRIVER_NAME'] == 'iHD'
    # Software runs inherit the parent environment untouched.
    assert transcode._spawn_env(3) is None


def test_note_tier_failure_marks_broken_and_records_tail(
        tmp_path, monkeypatch):
    monkeypatch.setattr(transcode, '_tier1_broken', False)
    monkeypatch.setattr(transcode, '_tier2_broken', False)
    monkeypatch.setattr(transcode, '_last_vaapi_error', None)
    session_dir = tmp_path / 'sess'
    session_dir.mkdir()
    (session_dir / 'ffmpeg-hybrid.log').write_text(
        'some banner\nboom: cannot open device\n', encoding='utf-8')
    session = {'dir': session_dir, 'gpu_failed': False,
               'vaapi_error': None}
    transcode._note_tier_failure(session, 2)
    assert transcode._tier2_broken is True
    assert transcode._tier1_broken is False
    assert session['gpu_failed'] is True
    assert 'boom' in session['vaapi_error']
    assert transcode._last_vaapi_error == session['vaapi_error']
    # Tier 3 failures are not GPU failures and mark nothing.
    transcode._note_tier_failure(session, 3)
    assert transcode._tier1_broken is False
