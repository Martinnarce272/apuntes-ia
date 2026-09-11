import unittest
from app import extract_youtube_id, app
import json

class TestApuntesIA(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_extract_youtube_id_various_formats(self):
        cases = [
            ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://www.youtube.com/embed/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
            ("dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ]
        for url, expected in cases:
            self.assertEqual(extract_youtube_id(url), expected, f"Failed for {url}")

    def test_api_status(self):
        response = self.client.get('/api/status')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertIn('status', data)
        self.assertEqual(data['status'], 'ready')

    def test_youtube_preview(self):
        # Test with a known public video
        response = self.client.post('/api/youtube-preview', 
                                  json={'url': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'})
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertTrue(data['success'])
        self.assertIn('title', data)
        self.assertIn('thumbnail', data)
    def test_demo_endpoint(self):
        response = self.client.get('/api/demo')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertTrue(data['success'])
        self.assertIn('title', data['data'])
        self.assertIn('developments', data['data'])
        self.assertIn('flashcards', data['data'])
        self.assertIn('quiz', data['data'])

    def test_multiple_youtube_previews(self):
        test_urls = [
            'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
            'https://youtu.be/dQw4w9WgXcQ'
        ]
        for u in test_urls:
            res = self.client.post('/api/youtube-preview', json={'url': u})
            self.assertEqual(res.status_code, 200)
            data = json.loads(res.data)
            self.assertTrue(data['success'])
    def test_youtube_transcript_missing_url(self):
        res = self.client.get('/api/youtube-transcript')
        self.assertEqual(res.status_code, 400)
        data = json.loads(res.data)
        self.assertFalse(data['success'])
        self.assertIn('error', data)

    def test_youtube_transcript_invalid_url(self):
        res = self.client.post('/api/youtube-transcript', json={'url': 'invalid-url-here'})
        self.assertEqual(res.status_code, 400)
        data = json.loads(res.data)
        self.assertFalse(data['success'])
        self.assertIn('error', data)

    def test_youtube_transcript_endpoint_structure(self):
        res = self.client.get('/api/youtube-transcript?url=https://www.youtube.com/watch?v=dQw4w9WgXcQ')
        self.assertIn(res.status_code, [200, 400])
        data = json.loads(res.data)
        if res.status_code == 200:
            self.assertTrue(data['success'])
            self.assertIn('full_text', data)
            self.assertIn('title', data)
        else:
            self.assertFalse(data['success'])
            self.assertIn('error', data)

if __name__ == '__main__':
    unittest.main()
