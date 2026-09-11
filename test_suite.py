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
    def test_extract_and_validate_key_header_and_sanitization(self):
        # Test clean extraction with whitespace and quotes from header
        with app.test_request_context('/', headers={'X-Gemini-Api-Key': ' " AIzaSyMockKeyForValidationPurposes12345 " '}):
            from app import extract_and_validate_key
            key, err = extract_and_validate_key()
            self.assertIsNone(err)
            self.assertEqual(key, "AIzaSyMockKeyForValidationPurposes12345")

    def test_extract_and_validate_key_accepts_aq_key_format(self):
        with app.test_request_context('/', headers={'X-Gemini-Api-Key': ' " AQ.Ab8RN6L4mMockValidationKeyLongEnough12345 " '}):
            from app import extract_and_validate_key
            key, err = extract_and_validate_key()
            self.assertIsNone(err)
            self.assertEqual(key, "AQ.Ab8RN6L4mMockValidationKeyLongEnough12345")

    def test_extract_and_validate_key_too_short(self):
        with app.test_request_context('/', headers={'X-Gemini-Api-Key': 'short_key'}):
            from app import extract_and_validate_key
            key, err = extract_and_validate_key()
            self.assertIsNone(key)
            self.assertIn("incompleta", err)

    def test_generate_notes_missing_key_returns_400_with_auth_flag(self):
        import os
        old_env = os.environ.get('GEMINI_API_KEY')
        if 'GEMINI_API_KEY' in os.environ:
            del os.environ['GEMINI_API_KEY']
        try:
            res = self.client.post('/api/generate-notes', data={'youtubeUrl': 'https://youtu.be/dQw4w9WgXcQ'})
            self.assertEqual(res.status_code, 400)
            data = json.loads(res.data)
            self.assertFalse(data['success'])
            self.assertTrue(data['is_auth_error'])
            self.assertIn('aistudio.google.com', data['error'])
        finally:
            if old_env:
                os.environ['GEMINI_API_KEY'] = old_env

if __name__ == '__main__':
    unittest.main()
