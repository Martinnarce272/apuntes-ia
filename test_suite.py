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
    def test_youtube_preview_has_caption_tracks(self):
        res = self.client.post('/api/youtube-preview', json={'url': 'https://www.youtube.com/watch?v=0XoS8EUrG3k'})
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertTrue(data['success'])
        self.assertIn('caption_tracks', data)
        self.assertIn('has_captions', data)
        self.assertTrue(data['has_captions'])
        self.assertGreater(len(data['caption_tracks']), 0)
        self.assertIn('base_url', data['caption_tracks'][0])

    def test_youtube_tracks_missing_url(self):
        res = self.client.get('/api/youtube-tracks')
        self.assertEqual(res.status_code, 400)
        data = json.loads(res.data)
        self.assertFalse(data['success'])
        self.assertIn('error', data)

    def test_youtube_tracks_invalid_url(self):
        res = self.client.post('/api/youtube-tracks', json={'url': 'invalid-url-here'})
        self.assertEqual(res.status_code, 400)
        data = json.loads(res.data)
        self.assertFalse(data['success'])
        self.assertIn('error', data)

    def test_youtube_tracks_valid_video(self):
        res = self.client.get('/api/youtube-tracks?url=https://www.youtube.com/watch?v=0XoS8EUrG3k')
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertTrue(data['success'])
        self.assertTrue(data['has_captions'])
        self.assertGreater(len(data['caption_tracks']), 0)
        self.assertIn('base_url', data['caption_tracks'][0])

    def test_youtube_video_without_captions_detection(self):
        # MejbOFk7H6U is a video without any captions
        res = self.client.get('/api/youtube-tracks?url=https://www.youtube.com/watch?v=MejbOFk7H6U')
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertTrue(data['success'])
        self.assertFalse(data['has_captions'])
        self.assertEqual(len(data['caption_tracks']), 0)

    def test_youtube_audio_streaming(self):
        # Test direct audio stream endpoint
        res = self.client.get('/api/youtube-audio?videoId=0XoS8EUrG3k')
        self.assertEqual(res.status_code, 200)
        self.assertIn('audio/', res.headers.get('Content-Type', ''))
        chunk = next(res.response)
        self.assertGreater(len(chunk), 0)

    def test_youtube_transcript_endpoint(self):
        # Test direct transcript extraction endpoint
        res = self.client.get('/api/youtube-transcript?videoId=0XoS8EUrG3k')
        data = json.loads(res.data)
        if res.status_code == 200:
            self.assertTrue(data['success'])
            self.assertIn('full_text', data)
            self.assertGreater(len(data['full_text']), 100)
            self.assertIn('timed_text', data)
        else:
            # When YouTube IP-blocks/rate-limits (429 / IpBlocked), endpoint should return clean JSON 404
            self.assertEqual(res.status_code, 404)
            self.assertFalse(data['success'])
            self.assertIn('error', data)

    def test_health_gemini(self):
        res = self.client.get('/api/health-gemini')
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertIn('configured', data)

    def test_generate_notes_requires_key(self):
        # Without key header/param, should return 401 with needs_key: True
        res = self.client.post('/api/generate-notes', json={'youtube_url': 'https://www.youtube.com/watch?v=0XoS8EUrG3k'})
        self.assertEqual(res.status_code, 401)
        data = json.loads(res.data)
        self.assertTrue(data.get('needs_key'))

    def test_robust_parse_json(self):
        from app import robust_parse_json
        raw = '```json\n{"title": "Test", "formula": "\\frac{1}{2} \\sigma(x)"}\n```'
        parsed = robust_parse_json(raw)
        self.assertEqual(parsed['title'], 'Test')
        self.assertIn('sigma', parsed['formula'])

    def test_gemini_models_config(self):
        from app import GeminiConfig, GEMINI_MODELS
        # Verify primary model is gemini-3.7-flash
        self.assertEqual(GeminiConfig.PRIMARY_MODEL, "gemini-3.7-flash")
        # Verify fallback is gemini-3.6-flash
        self.assertEqual(GeminiConfig.FALLBACK_MODEL, "gemini-3.6-flash")
        # Verify models list order
        self.assertEqual(GeminiConfig.MODELS, ["gemini-3.7-flash", "gemini-3.6-flash"])
        self.assertEqual(GEMINI_MODELS, ["gemini-3.7-flash", "gemini-3.6-flash"])
        # Verify deprecated 2.5 models are completely removed
        self.assertNotIn("gemini-2.5-flash", GeminiConfig.MODELS)
        self.assertNotIn("gemini-2.5-pro", GeminiConfig.MODELS)
        self.assertNotIn("gemini-2.5-flash", GEMINI_MODELS)
        self.assertNotIn("gemini-2.5-pro", GEMINI_MODELS)
        # Verify status endpoint reflects new model configuration
        res = self.client.get('/api/status')
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertEqual(data.get('default_model'), "gemini-3.7-flash")
        self.assertEqual(data.get('fallback_model'), "gemini-3.6-flash")
        self.assertIn('commit', data)

    def test_token_limit_exceeded_guard(self):
        """Verify that when token count exceeds 1M, a user-friendly 400 error is returned."""
        from unittest.mock import patch, MagicMock
        with patch('google.genai.Client') as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            # Mock count_tokens returning 1,350,000 tokens (> 1,000,000 limit)
            mock_count_resp = MagicMock()
            mock_count_resp.total_tokens = 1350000
            mock_client.models.count_tokens.return_value = mock_count_resp

            headers = {'X-Gemini-Api-Key': 'fake_test_key'}
            res = self.client.post('/api/generate-notes',
                                  headers=headers,
                                  json={'notes_text': 'Texto de prueba largo.'})
            self.assertEqual(res.status_code, 400)
            data = json.loads(res.data)
            self.assertFalse(data['success'])
            self.assertIn('demasiado extenso', data['error'])
            self.assertIn('1,350,000', data['error'])
            self.assertEqual(data['total_tokens'], 1350000)

    def test_gemini_503_retry_and_success(self):
        """Verify that a 503 UNAVAILABLE error triggers automatic retry and succeeds if recovery happens."""
        from unittest.mock import patch, MagicMock
        with patch('google.genai.Client') as mock_client_cls, patch('time.sleep') as mock_sleep:
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client

            # Mock count_tokens OK
            mock_count_resp = MagicMock()
            mock_count_resp.total_tokens = 5000
            mock_client.models.count_tokens.return_value = mock_count_resp

            # Mock generate_content: 1st call fails with 503, 2nd call succeeds
            mock_success_resp = MagicMock()
            mock_success_resp.text = json.dumps({
                "title": "Apunte de Prueba",
                "overview": "Resumen",
                "key_takeaways": [],
                "developments": []
            })
            mock_client.models.generate_content.side_effect = [
                Exception("503 UNAVAILABLE: The model is overloaded. Please try again later."),
                mock_success_resp
            ]

            headers = {'X-Gemini-Api-Key': 'fake_test_key'}
            res = self.client.post('/api/generate-notes',
                                  headers=headers,
                                  json={'notes_text': 'Texto de prueba'})
            self.assertEqual(res.status_code, 200)
            data = json.loads(res.data)
            self.assertTrue(data['success'])
            self.assertEqual(data['data']['title'], "Apunte de Prueba")
            # Verify sleep was called for backoff
            mock_sleep.assert_called_once_with(2)

    def test_youtube_url_deduplication(self):
        """Verify that duplicate YouTube URLs are processed only once."""
        from unittest.mock import patch, MagicMock
        with patch('google.genai.Client') as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client

            mock_count_resp = MagicMock()
            mock_count_resp.total_tokens = 8000
            mock_client.models.count_tokens.return_value = mock_count_resp

            mock_success_resp = MagicMock()
            mock_success_resp.text = json.dumps({
                "title": "Apunte con Video",
                "sources": []
            })
            mock_client.models.generate_content.return_value = mock_success_resp

            headers = {'X-Gemini-Api-Key': 'fake_test_key'}
            # Send same video in 2 different URL formats
            res = self.client.post('/api/generate-notes',
                                  headers=headers,
                                  json={
                                      'youtube_urls': [
                                          'https://www.youtube.com/watch?v=0XoS8EUrG3k',
                                          'https://youtu.be/0XoS8EUrG3k'
                                      ],
                                      'client_transcripts': {
                                          '0XoS8EUrG3k': 'Transcripcion de prueba para el video.'
                                      }
                                  })
            self.assertEqual(res.status_code, 200)
            data = json.loads(res.data)
            self.assertTrue(data['success'])
            # Ensure sources list has only 1 entry for 0XoS8EUrG3k
            sources = [s for s in data['data']['sources'] if s.get('video_id') == '0XoS8EUrG3k']
            self.assertEqual(len(sources), 1)

if __name__ == '__main__':
    unittest.main()

