import importlib.util
import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('downloader', Path(__file__).resolve().parents[1] / 'api/index.py')
app = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(app)


class ApiTests(unittest.TestCase):
    def test_valid_and_untrusted_urls(self):
        for url in ('https://youtu.be/abcdefghijk', 'https://youtube.com/watch?v=abcdefghijk&list=ignored',
                    'https://www.youtube.com/shorts/abcdefghijk', 'https://youtube.com/live/abcdefghijk'):
            self.assertEqual(app.video_id(url), 'abcdefghijk')
        for url in ('https://youtube.com.evil.test/watch?v=abcdefghijk', 'https://youtube.com@evil.test/watch?v=abcdefghijk',
                    'file:///etc/passwd', 'https://youtube.com:444/watch?v=abcdefghijk', 'https://youtube.com/playlist?list=x'):
            with self.assertRaises(ValueError):
                app.video_id(url)

    def test_long_video_has_no_application_duration_cap(self):
        with patch.object(app, 'options', return_value={}):
            opts = app.download_options(1080, '/tmp/example')
        self.assertIsNone(opts['match_filter']({'duration': 14400, 'is_live': False}, incomplete=False))
        self.assertIsNotNone(opts['match_filter']({'duration': 60, 'is_live': True}, incomplete=False))
        self.assertIn('ext=mp4', opts['format'])

    def test_formats_come_from_source_and_estimate_merged_audio(self):
        info = {'title': '<unsafe title>', 'duration': 7200, 'formats': [
            {'height': 720, 'vcodec': 'h264', 'acodec': 'aac', 'filesize': 1000, 'tbr': 10},
            {'height': 1080, 'vcodec': 'h264', 'acodec': 'none', 'filesize': 2000, 'tbr': 20},
            {'vcodec': 'none', 'acodec': 'aac', 'filesize': 300}]}
        with patch('yt_dlp.YoutubeDL') as mock, patch.object(app, 'options', return_value={}):
            mock.return_value.__enter__.return_value.extract_info.return_value = info
            result = app.inspect_video('abcdefghijk')
        self.assertEqual([q['height'] for q in result['qualities']], [1080, 720])
        self.assertEqual(result['qualities'][0]['bytes'], 2300)
        self.assertTrue(result['qualities'][0]['estimated'])
        self.assertFalse(result['qualities'][1]['estimated'])

    def test_json_error_and_video_response_cleanup(self):
        class Capture(app.handler):
            def __init__(self, path):
                self.path = path
                self.wfile = io.BytesIO()
                self.headers_out = {}
            def send_response(self, status): self.status = status
            def send_header(self, key, value): self.headers_out[key] = value
            def end_headers(self): pass
        invalid = Capture('/api/index?action=inspect&url=https://evil.test/')
        invalid.do_GET()
        self.assertEqual(invalid.status, 400)
        self.assertIn('error', json.loads(invalid.wfile.getvalue()))
        request = Capture('/api/index?action=download&url=https://youtu.be/abcdefghijk&height=720')
        made = []
        def download(_):
            Path(made[0], 'video.mp4').write_bytes(b'example-video-data')
        def opts(height, directory):
            made.append(directory)
            return {}
        with patch('yt_dlp.YoutubeDL') as mock, patch.object(app, 'download_options', side_effect=opts):
            mock.return_value.__enter__.return_value.download.side_effect = download
            request.do_GET()
        self.assertEqual(request.status, 200)
        self.assertEqual(request.headers_out['Content-Type'], 'video/mp4')
        self.assertIn('.mp4', request.headers_out['Content-Disposition'])
        self.assertEqual(request.wfile.getvalue(), b'example-video-data')
        self.assertFalse(Path(made[0]).exists())


if __name__ == '__main__': unittest.main()
