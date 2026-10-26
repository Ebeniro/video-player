import json
import re
import os
import logging
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError
from pathlib import Path
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, urlencode


class ServiceError(Exception):
    def __init__(self, message, status=503):
        super().__init__(message)
        self.status = status


def managed_request(endpoint, params):
    key = os.environ.get('TUNELIO_API_KEY', '').strip()
    if not key:
        raise ServiceError('Download service setup is incomplete. The owner needs to connect the download provider.')
    request = Request('https://tunelio.dev/' + endpoint + '?' + urlencode(params),
                      headers={'Authorization': 'Bearer ' + key, 'Accept': 'application/json'})
    try:
        with urlopen(request, timeout=45) as response:
            result = json.load(response)
    except HTTPError as exc:
        messages = {401: 'The download service connection needs updating.',
                    402: 'The download service allowance has been used up.',
                    404: 'This video or the requested captions are unavailable.',
                    429: 'The download service is busy. Please try again shortly.'}
        raise ServiceError(messages.get(exc.code, 'The download provider did not complete the request.'),
                           exc.code if exc.code in messages else 502) from None
    except (URLError, TimeoutError, json.JSONDecodeError):
        raise ServiceError('The download provider did not respond. Please try again later.', 502) from None
    if not isinstance(result, dict) or result.get('error') or result.get('status') not in (None, 'ok', 'success'):
        raise ServiceError('The download provider did not complete the request.', 502)
    return result


def managed_inspect(vid):
    data = managed_request('info', {'url': 'https://www.youtube.com/watch?v=' + vid})
    choices = {}
    for item in data.get('formats', []):
        match = re.fullmatch(r'(\d{3,4})p', str(item.get('quality', '')))
        height = item.get('height') or (int(match.group(1)) if match else None)
        if not isinstance(height, int) or not 144 <= height <= 2160:
            continue
        size = item.get('file_size')
        choices[height] = {'height': height, 'bytes': size if isinstance(size, (int, float)) and size > 0 else None,
                           'estimated': False}
    return {'id': vid, 'title': data.get('title', 'YouTube video'), 'channel': data.get('author', ''),
            'duration': data.get('duration_seconds'), 'qualities': [choices[h] for h in sorted(choices, reverse=True)]}


def managed_download(vid, height):
    data = managed_request('create', {'url': 'https://www.youtube.com/watch?v=' + vid, 'quality': str(height) + 'p'})
    url = data.get('url', '')
    parsed = urlparse(url)
    if (parsed.scheme != 'https' or parsed.hostname != 'tunelio.dev' or parsed.username or parsed.password
            or parsed.port or not parsed.path.startswith('/tunnel')):
        raise ServiceError('The download provider returned an invalid download link.', 502)
    return {'url': url, 'filename': data.get('filename', 'youtube-' + vid + '.mp4'),
            'bytes': data.get('file_size'), 'expires': data.get('expires')}


def managed_transcript(vid, language):
    data = managed_request('transcript', {'url': vid, 'lang': language, 'format': 'json'})
    segments = data.get('segments')
    if not isinstance(segments, list) or not segments:
        raise ServiceError('No captions are available for this video or language.', 404)
    cleaned = []
    for item in segments:
        if not isinstance(item, dict) or not isinstance(item.get('text'), str):
            raise ServiceError('The caption service returned an invalid transcript.', 502)
        start, duration = item.get('start'), item.get('duration')
        if not isinstance(start, (int, float)) or not isinstance(duration, (int, float)) or start < 0 or duration < 0:
            raise ServiceError('The caption service returned invalid timestamps.', 502)
        cleaned.append({'text': item['text'], 'start': start, 'duration': duration})
    code = data.get('language', language)
    tracks = []
    for track in data.get('available_languages', []):
        if not isinstance(track, dict):
            continue
        track_code = track.get('language_code') or track.get('code') or track.get('language')
        if track_code:
            tracks.append({'code': track_code, 'name': track.get('name') or track.get('language_name') or track_code,
                           'automatic': track.get('is_generated', track.get('auto_generated'))})
    if not any(t['code'] == code for t in tracks):
        tracks.insert(0, {'code': code, 'name': data.get('language_name', code), 'automatic': data.get('is_generated')})
    return {'language': data.get('language_name', code), 'language_code': code,
            'automatic': data.get('is_generated'), 'languages': tracks, 'segments': cleaned}


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


def metadata(vid):
    query = urlencode({'url': 'https://www.youtube.com/watch?v=' + vid, 'format': 'json'})
    with urlopen('https://www.youtube.com/oembed?' + query, timeout=12) as response:
        data = json.load(response)
    return {'id': vid, 'title': data.get('title', 'YouTube video'),
            'channel': data.get('author_name', ''),
            'thumbnail': 'https://i.ytimg.com/vi/' + vid + '/hqdefault.jpg'}


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
            return self.json_response({'ok': True, 'service': 'YouTube Downloader',
                                       'download_provider': 'tunelio',
                                       'provider_configured': bool(os.environ.get('TUNELIO_API_KEY', '').strip())})
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
                return self.json_response(managed_inspect(vid))
            if action == 'transcript':
                return self.json_response(managed_transcript(vid, query.get('language', ['en'])[0]))
            if action not in ('download', 'download-link'):
                raise ValueError('Unknown request.')
            height = int(query.get('height', ['720'])[0])
            if height < 144 or height > 2160:
                raise ValueError('Choose an available resolution between 144p and 4K.')
            link = managed_download(vid, height)
            if action == 'download-link':
                return self.json_response(link)
            self.send_response(302)
            self.send_header('Location', link['url'])
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            return
        except (BrokenPipeError, ConnectionResetError):
            return
        except ServiceError as exc:
            logging.error('Download provider error: action=%s status=%s', action, exc.status)
            self.json_response({'error': str(exc), 'code': 'provider_unavailable'}, exc.status)
        except Exception as exc:
            logging.error('YouTube request failed: action=%s type=%s reason=%s', action, type(exc).__name__, public_error(exc))
            self.json_response({'error': public_error(exc)}, 400 if isinstance(exc, ValueError) else 502)
