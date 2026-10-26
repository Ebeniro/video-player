import importlib.util
import io
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

SPEC = importlib.util.spec_from_file_location('downloader', Path(__file__).resolve().parents[1] / 'api/index.py')
app = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(app)

class Capture(app.handler):
    def __init__(self, path):
        self.path = path
        self.wfile = io.BytesIO()
        self.headers_out = {}
    def send_response(self, status): self.status = status
    def send_header(self, key, value): self.headers_out[key] = value
    def end_headers(self): pass

class ApiTests(unittest.TestCase):
    def test_valid_and_untrusted_urls(self):
        for url in ('https://youtu.be/abcdefghijk', 'https://youtube.com/watch?v=abcdefghijk&list=ignored',
                    'https://www.youtube.com/shorts/abcdefghijk', 'https://youtube.com/live/abcdefghijk'):
            self.assertEqual(app.video_id(url), 'abcdefghijk')
        for url in ('https://youtube.com.evil.test/watch?v=abcdefghijk', 'https://youtube.com@evil.test/watch?v=abcdefghijk',
                    'file:///etc/passwd', 'https://youtube.com:444/watch?v=abcdefghijk', 'https://youtube.com/playlist?list=x'):
            with self.assertRaises(ValueError): app.video_id(url)

    def test_missing_key_fails_before_any_network_request(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(app, 'urlopen') as fetch:
            req = Capture('/api/index?action=inspect&url=https://youtu.be/abcdefghijk')
            req.do_GET()
        self.assertEqual(req.status, 503)
        self.assertIn('setup is incomplete', json.loads(req.wfile.getvalue())['error'])
        fetch.assert_not_called()

    def test_provider_authorization_stays_server_side(self):
        response = io.BytesIO(json.dumps({'title': 'Test'}).encode())
        with patch.dict(os.environ, {'TUNELIO_API_KEY': 'example-test-value'}), patch.object(app, 'urlopen', return_value=response) as fetch:
            self.assertEqual(app.managed_request('info', {'url': 'https://youtu.be/abcdefghijk'})['title'], 'Test')
        sent = fetch.call_args.args[0]
        self.assertEqual(sent.get_header('Authorization'), 'Bearer example-test-value')
        self.assertNotIn('example-test-value', sent.full_url)
        self.assertTrue(sent.full_url.startswith('https://tunelio.dev/info?'))

    def test_long_video_and_real_source_qualities(self):
        data = {'title': 'Long source', 'duration_seconds': 14400, 'formats': [
            {'quality': '1080p', 'height': 1080, 'file_size': 2000},
            {'quality': '720p', 'file_size': 1000}, {'quality': 'audio'},
            {'quality': '1080p', 'height': 1080, 'file_size': 2500}]}
        with patch.object(app, 'managed_request', return_value=data): result = app.managed_inspect('abcdefghijk')
        self.assertEqual(result['duration'], 14400)
        self.assertEqual([q['height'] for q in result['qualities']], [1080, 720])
        self.assertEqual(result['qualities'][0]['bytes'], 2500)
        self.assertFalse(result['qualities'][0]['estimated'])

    def test_download_link_is_validated_and_browser_redirects(self):
        good = {'url': 'https://tunelio.dev/tunnel?exp=100&sig=example', 'filename': 'video.mp4'}
        with patch.object(app, 'managed_request', return_value=good):
            self.assertEqual(app.managed_download('abcdefghijk', 720)['filename'], 'video.mp4')
            req = Capture('/api/index?action=download&url=https://youtu.be/abcdefghijk&height=720')
            req.do_GET()
        self.assertEqual(req.status, 302)
        self.assertEqual(req.headers_out['Location'], good['url'])
        self.assertEqual(req.wfile.getvalue(), b'')
        for url in ('http://tunelio.dev/tunnel', 'https://tunelio.dev.evil.test/tunnel', 'https://evil.test/tunnel',
                    'https://tunelio.dev@evil.test/tunnel', 'https://tunelio.dev:444/tunnel', 'javascript:alert(1)'):
            with patch.object(app, 'managed_request', return_value={'url': url}):
                with self.assertRaises(app.ServiceError): app.managed_download('abcdefghijk', 720)

    def test_quota_error_does_not_start_another_download(self):
        with patch.dict(os.environ, {'TUNELIO_API_KEY': 'example-test-value'}), patch.object(app, 'urlopen', side_effect=HTTPError('https://tunelio.dev/create', 402, 'quota', {}, None)) as fetch:
            req = Capture('/api/index?action=download-link&url=https://youtu.be/abcdefghijk&height=720')
            req.do_GET()
        self.assertEqual(req.status, 402)
        self.assertIn('allowance', json.loads(req.wfile.getvalue())['error'])
        self.assertEqual(fetch.call_count, 1)

    def test_transcript_preserves_timestamps_and_provenance(self):
        payload = {'language': 'en', 'language_name': 'English', 'is_generated': True,
                   'segments': [{'text': 'Example caption.', 'start': 0.5, 'duration': 1.2}],
                   'available_languages': [{'language_code': 'en', 'name': 'English', 'is_generated': True}]}
        with patch.object(app, 'managed_request', return_value=payload): result = app.managed_transcript('abcdefghijk', 'en')
        self.assertTrue(result['automatic'])
        self.assertEqual(result['segments'], payload['segments'])
        self.assertEqual(result['languages'][0]['code'], 'en')
        with patch.object(app, 'managed_request', return_value={'segments': []}):
            with self.assertRaises(app.ServiceError): app.managed_transcript('abcdefghijk', 'en')

if __name__ == '__main__': unittest.main()
