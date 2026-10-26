import json
import re
import tempfile
import os
import logging
import shutil
from urllib.request import urlopen
from pathlib import Path
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, urlencode


def video_id(value):
    parsed = urlparse(value)
    if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port:
        raise ValueError('Paste a valid https YouTube video link.')
    host = (parsed.hostname or '').lower()
    if host in ('youtu.be', 'www.youtu.be'):
        candidate = parsed.path.strip('/')
    elif host in ('youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com'):
        parts = parsed.path.strip('/').split('/')
        candidate = parse_qs(parsed.query).get('v', [''])[0] if parsed.path == '/watch' else (parts[1] if len(parts) == 2 and parts[0] in ('shorts', 'live', 'embed') else '')
    else:
        candidate = ''
    if not re.fullmatch(r'[A-Za-z0-9_-]{11}', candidate):
        raise ValueError('Paste a YouTube video link, rather than a channel or playlist.')
    return candidate


def javascript_runtime():
    import deno
    bundled = Path(__file__).resolve().parent.parent / 'runtime/deno'
    if bundled.is_file():
        return str(bundled)
    try:
        return deno.find_deno_bin()
    except FileNotFoundError:
        return shutil.which('deno') or shutil.which('node')


def options():
    import imageio_ffmpeg
    runtime = javascript_runtime()
    runtime_name = 'node' if runtime and Path(runtime).name == 'node' else 'deno'
    return {'quiet': True, 'no_warnings': True, 'noplaylist': True,
            'socket_timeout': 15, 'retries': 1, 'extractor_retries': 1,
            'js_runtimes': {runtime_name: {'path': runtime}} if runtime else {},
            'cachedir': False, 'ffmpeg_location': imageio_ffmpeg.get_ffmpeg_exe()}


def metadata(vid):
    query = urlencode({'url': 'https://www.youtube.com/watch?v=' + vid, 'format': 'json'})
    with urlopen('https://www.youtube.com/oembed?' + query, timeout=12) as response:
        data = json.load(response)
    return {'id': vid, 'title': data.get('title', 'YouTube video'),
            'channel': data.get('author_name', ''),
            'thumbnail': 'https://i.ytimg.com/vi/' + vid + '/hqdefault.jpg'}


def download_options(height, directory):
    import yt_dlp
    free = shutil.disk_usage('/tmp').free
    reserve = 64 * 1024 * 1024
    if free <= reserve:
        raise ValueError('The download service is busy. Please try again shortly.')
    def check_disk(progress):
        if shutil.disk_usage('/tmp').free < reserve:
            raise ValueError('There is not enough processing space for this quality. Choose a lower resolution.')
    opts = options()
    opts.update({'format': f'bv[height={height}][ext=mp4]+ba[ext=m4a]/b[height={height}][ext=mp4]/bv[height={height}]+ba/b[height={height}]',
                 'outtmpl': directory + '/video.%(ext)s', 'merge_output_format': 'mp4/mkv',
                 'max_filesize': (free - reserve) // 3, 'progress_hooks': [check_disk],
                 'match_filter': yt_dlp.utils.match_filter_func('!is_live')})
    return opts


def inspect_video(vid):
    import yt_dlp
    with yt_dlp.YoutubeDL(options()) as ydl:
        info = ydl.extract_info('https://www.youtube.com/watch?v=' + vid, download=False)
    if info.get('is_live'):
        raise ValueError('Wait until this live stream has ended before downloading.')
    formats = info.get('formats', [])
    audio = [f for f in formats if f.get('acodec') not in (None, 'none') and f.get('vcodec') == 'none']
    audio_size = max((f.get('filesize') or f.get('filesize_approx') or 0 for f in audio), default=0)
    choices = []
    for height in sorted({int(f['height']) for f in formats if f.get('height') and f.get('vcodec') not in (None, 'none') and f['height'] <= 2160}, reverse=True):
        matching = [f for f in formats if f.get('height') == height and f.get('vcodec') not in (None, 'none')]
        best = max(matching, key=lambda f: f.get('tbr') or 0)
        size = best.get('filesize') or best.get('filesize_approx')
        separate = best.get('acodec') in (None, 'none')
        if size and separate:
            size = size + audio_size if audio_size else None
        choices.append({'height': height, 'bytes': size, 'estimated': separate or not bool(best.get('filesize'))})
    return {'id': vid, 'title': info.get('title', 'YouTube video'), 'channel': info.get('uploader', ''),
            'duration': info.get('duration'), 'thumbnail': 'https://i.ytimg.com/vi/' + vid + '/hqdefault.jpg', 'qualities': choices}


def transcript(vid, language):
    from youtube_transcript_api import YouTubeTranscriptApi
    available = list(YouTubeTranscriptApi().list(vid))
    if not available:
        raise ValueError('This video has no available captions. Speech transcription is not included.')
    matches = [t for t in available if t.language_code == language]
    selected = sorted(matches or available, key=lambda t: t.is_generated)[0]
    snippets = selected.fetch()
    return {'language': selected.language, 'language_code': selected.language_code,
            'automatic': selected.is_generated,
            'languages': [{'code': t.language_code, 'name': t.language, 'automatic': t.is_generated} for t in available],
            'segments': [{'text': s.text, 'start': s.start, 'duration': s.duration} for s in snippets]}


def public_error(exc):
    message = str(exc).lower()
    if any(term in message for term in ('sign in', 'bot', 'ipblocked', 'requestblocked', 'ip has been blocked', 'blocking requests', '403', 'forbidden')):
        return 'YouTube is refusing this download request. Please try again later.'
    if any(term in message for term in ('disabled', 'no transcript', 'subtitles', 'captions')):
        return 'No captions are available for this video or language.'
    if isinstance(exc, ValueError):
        return str(exc)
    return 'YouTube did not complete this request. The video might be restricted or temporarily unavailable. Try again later.'


class handler(BaseHTTPRequestHandler):
    def json_response(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if urlparse(self.path).path == '/':
            body = (Path(__file__).resolve().parent.parent / 'index.html').read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        query = parse_qs(urlparse(self.path).query)
        action = query.get('action', ['health'])[0]
        if action == 'health':
            import yt_dlp.version
            import youtube_transcript_api
            import importlib.metadata
            return self.json_response({'ok': True, 'service': 'YouTube Downloader',
                                       'versions': {'yt_dlp': yt_dlp.version.__version__,
                                                    'transcripts': importlib.metadata.version('youtube-transcript-api')},
                                       'javascript_runtime': bool(javascript_runtime())})
        try:
            vid = video_id(query.get('url', [''])[0])
            if action == 'thumbnail':
                with urlopen('https://i.ytimg.com/vi/' + vid + '/hqdefault.jpg', timeout=12) as response:
                    body = response.read(2 * 1024 * 1024)
                if not body.startswith(b'\xff\xd8'):
                    raise ValueError('Video thumbnail is unavailable.')
                self.send_response(200)
                self.send_header('Content-Type', 'image/jpeg')
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'public, max-age=3600')
                self.end_headers()
                self.wfile.write(body)
                return
            if action == 'metadata':
                return self.json_response(metadata(vid))
            if action == 'inspect':
                return self.json_response(inspect_video(vid))
            if action == 'transcript':
                return self.json_response(transcript(vid, query.get('language', ['en'])[0]))
            if action != 'download':
                raise ValueError('Unknown request.')
            height = int(query.get('height', ['720'])[0])
            if height < 144 or height > 2160:
                raise ValueError('Choose an available resolution between 144p and 4K.')
            import yt_dlp
            with tempfile.TemporaryDirectory(prefix='trelion-', dir='/tmp') as directory:
                opts = download_options(height, directory)
                with yt_dlp.YoutubeDL(opts) as ydl:
                    ydl.download(['https://www.youtube.com/watch?v=' + vid])
                files = [os.path.join(directory, name) for name in os.listdir(directory)
                         if name.endswith(('.mp4', '.mkv', '.webm', '.mov'))]
                if len(files) != 1 or os.path.getsize(files[0]) == 0:
                    raise ValueError('The selected file was not prepared. Try a lower resolution.')
                path = files[0]
                extension = os.path.splitext(path)[1]
                self.send_response(200)
                self.send_header('Content-Type', {'.mp4': 'video/mp4', '.webm': 'video/webm'}.get(extension, 'video/x-matroska'))
                self.send_header('Content-Disposition', f'attachment; filename="youtube-{vid}-{height}p{extension}"')
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                with open(path, 'rb') as source:
                    while True:
                        block = source.read(256 * 1024)
                        if not block:
                            break
                        self.wfile.write(block)
                return
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as exc:
            logging.error('YouTube request failed: action=%s type=%s reason=%s', action, type(exc).__name__, public_error(exc))
            self.json_response({'error': public_error(exc)}, 400 if isinstance(exc, ValueError) else 502)
