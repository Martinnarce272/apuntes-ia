import unittest
from unittest.mock import patch, MagicMock
from app import extract_youtube_id, app, GeminiConfig
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
            self.assertEqual(data['video_id'], 'dQw4w9WgXcQ')

    @patch('app.get_youtube_transcript')
    @patch('google.genai.Client')
    def test_video_without_subtitles_handled_multimodal(self, mock_client_class, mock_transcript):
        # Simulate video without subtitles / transcripts
        mock_transcript.return_value = {
            "success": False,
            "error": "No subtitles available"
        }
        
        mock_instance = mock_client_class.return_value
        
        # Step 1: Video extraction call returns text notes
        resp_extract = MagicMock()
        resp_extract.text = "Desarrollo detallado extraido del video multimodal."
        
        # Step 2: Final synthesis call returns structured JSON
        resp_synthesis = MagicMock()
        resp_synthesis.text = json.dumps({
            "title": "Video Sin Subtitulos",
            "topic_overview": "Analizado directamente por visión multimodal",
            "estimated_study_time": "15 min",
            "key_takeaways": [],
            "developments": [],
            "general_diagram": {"title": "Diagrama", "mermaid_code": ""},
            "flashcards": [],
            "quiz": [],
            "exam_tips": [],
            "glossary": []
        })
        mock_instance.models.generate_content.side_effect = [resp_extract, resp_synthesis]
        
        res = self.client.post('/api/generate-notes', data={
            'youtubeUrl': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
        }, headers={'X-Gemini-Api-Key': 'fake-test-key-12345'})
        
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertTrue(data['success'])
        self.assertEqual(data['data']['title'], "Video Sin Subtitulos")
        
        sources = data['data']['sources']
        self.assertEqual(len(sources), 1)
        self.assertFalse(sources[0]['has_captions'])
        self.assertEqual(sources[0]['mode'], 'multimodal_vision')
        
        # Verify 2 calls: 1 individual video extraction + 1 final synthesis
        self.assertEqual(mock_instance.models.generate_content.call_count, 2)
        
        # Call 1: check that video FileData Part was passed
        first_call = mock_instance.models.generate_content.call_args_list[0][1]
        first_contents = first_call['contents']
        self.assertIsInstance(first_contents, list)
        self.assertEqual(len(first_contents), 2)
        video_part = first_contents[0]
        self.assertTrue(hasattr(video_part, 'file_data'))
        self.assertIn('dQw4w9WgXcQ', video_part.file_data.file_uri)
        
        # Call 2: final synthesis receives text prompt only
        second_call = mock_instance.models.generate_content.call_args_list[1][1]
        second_contents = second_call['contents']
        self.assertIsInstance(second_contents, str)
        self.assertIn("Desarrollo detallado extraido del video multimodal", second_contents)

    @patch('app.get_youtube_transcript')
    @patch('google.genai.Client')
    def test_video_with_subtitles_handled_as_text(self, mock_client_class, mock_transcript):
        mock_transcript.return_value = {
            "success": True,
            "timed_text": "[00:01] Hola bienvenidos a la clase",
            "full_text": "Hola bienvenidos a la clase",
            "duration_seconds": 60
        }
        mock_instance = mock_client_class.return_value
        fake_response = MagicMock()
        fake_response.text = json.dumps({
            "title": "Video Con Subtitulos",
            "topic_overview": "Resumen con subtitulos",
            "estimated_study_time": "10 min",
            "key_takeaways": [],
            "developments": [],
            "general_diagram": {"title": "Diagrama", "mermaid_code": ""},
            "flashcards": [],
            "quiz": [],
            "exam_tips": [],
            "glossary": []
        })
        mock_instance.models.generate_content.return_value = fake_response
        
        res = self.client.post('/api/generate-notes', data={
            'youtubeUrl': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
        }, headers={'X-Gemini-Api-Key': 'fake-test-key-12345'})
        
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertTrue(data['success'])
        self.assertEqual(data['data']['title'], "Video Con Subtitulos")
        
        sources = data['data']['sources']
        self.assertEqual(len(sources), 1)
        self.assertTrue(sources[0]['has_captions'])
        
        # Verify only 1 call is made (synthesis) because transcript is already text
        self.assertEqual(mock_instance.models.generate_content.call_count, 1)
        call_kwargs = mock_instance.models.generate_content.call_args[1]
        contents = call_kwargs['contents']
        self.assertIsInstance(contents, str)
        self.assertIn("Hola bienvenidos a la clase", contents)

    @patch('app.get_youtube_transcript')
    @patch('google.genai.Client')
    def test_quota_error_429_returns_clear_message(self, mock_client_class, mock_transcript):
        mock_transcript.return_value = {
            "success": True,
            "timed_text": "[00:01] Clase de prueba",
            "full_text": "Clase de prueba",
            "duration_seconds": 30
        }
        mock_instance = mock_client_class.return_value
        mock_instance.models.generate_content.side_effect = Exception(
            "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You exceeded your current quota...'}}"
        )
        
        res = self.client.post('/api/generate-notes', data={
            'youtubeUrl': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
        }, headers={'X-Gemini-Api-Key': 'fake-test-key-12345'})
        
        self.assertEqual(res.status_code, 429)
        data = json.loads(res.data)
        self.assertFalse(data['success'])
        self.assertIn("límite de uso gratuito de Gemini", data['error'])

    @patch('app.get_youtube_transcript')
    @patch('google.genai.Client')
    def test_multiple_videos_without_subtitles_processed_sequentially(self, mock_client_class, mock_transcript):
        # Both videos have no subtitles
        mock_transcript.return_value = {"success": False, "error": "No subtitles"}
        
        mock_instance = mock_client_class.return_value
        
        v1_extract = MagicMock(text="Apuntes Video 1")
        v2_extract = MagicMock(text="Apuntes Video 2")
        final_synth = MagicMock(text=json.dumps({
            "title": "Apunte Maestro Combinado",
            "topic_overview": "Sintesis de dos videos",
            "estimated_study_time": "30 min",
            "key_takeaways": [],
            "developments": [],
            "general_diagram": {"title": "", "mermaid_code": ""},
            "flashcards": [],
            "quiz": [],
            "exam_tips": [],
            "glossary": []
        }))
        
        mock_instance.models.generate_content.side_effect = [v1_extract, v2_extract, final_synth]
        
        res = self.client.post('/api/generate-notes', data={
            'youtubeUrls': [
                'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
                'https://www.youtube.com/watch?v=9bZkp7q19f0'
            ]
        }, headers={'X-Gemini-Api-Key': 'fake-test-key-12345'})
        
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertTrue(data['success'])
        
        # 3 calls: Video 1 alone, Video 2 alone, Synthesis call
        self.assertEqual(mock_instance.models.generate_content.call_count, 3)
        
        # Verify first call had only 1 video part
        c1 = mock_instance.models.generate_content.call_args_list[0][1]['contents']
        self.assertEqual(len(c1), 2)
        self.assertIn('dQw4w9WgXcQ', c1[0].file_data.file_uri)
        
        # Verify second call had only 1 video part
        c2 = mock_instance.models.generate_content.call_args_list[1][1]['contents']
        self.assertEqual(len(c2), 2)
        self.assertIn('9bZkp7q19f0', c2[0].file_data.file_uri)
        
        # Verify third call is pure text synthesis
        c3 = mock_instance.models.generate_content.call_args_list[2][1]['contents']
        self.assertIsInstance(c3, str)
        self.assertIn("Apuntes Video 1", c3)
        self.assertIn("Apuntes Video 2", c3)

    def test_gemini_config_order(self):
        """Confirm the exact model order requested by the user."""
        self.assertEqual(GeminiConfig.PRIMARY_MODEL, "gemini-3.8-flash")
        self.assertEqual(GeminiConfig.FALLBACK_MODEL, "gemini-3.5-flash-lite")
        self.assertEqual(GeminiConfig.LAST_RESORT_MODELS, ["gemini-3.7-flash", "gemini-3.6-flash"])
        self.assertEqual(GeminiConfig.ACTIVE_MODELS, ["gemini-3.8-flash", "gemini-3.5-flash-lite"])

    @patch('app.get_youtube_transcript')
    @patch('google.genai.Client')
    def test_model_fallback_on_429_skips_immediately_to_3_5_flash_lite(self, mock_client_class, mock_transcript):
        """When gemini-3.8-flash returns 429, it must immediately fall back to gemini-3.5-flash-lite without retrying."""
        mock_transcript.return_value = {
            "success": True,
            "timed_text": "[00:01] Intro",
            "full_text": "Intro",
            "duration_seconds": 10
        }
        mock_instance = mock_client_class.return_value

        def fake_generate(model, contents, config):
            if model == "gemini-3.8-flash":
                raise Exception("429 RESOURCE_EXHAUSTED. You exceeded your current quota...")
            if model == "gemini-3.5-flash-lite":
                return MagicMock(text=json.dumps({
                    "title": "Apunte de 3.5-flash-lite",
                    "topic_overview": "Resumen",
                    "estimated_study_time": "10 min",
                    "key_takeaways": [],
                    "developments": [],
                    "general_diagram": {"title": "", "mermaid_code": ""},
                    "flashcards": [],
                    "quiz": [],
                    "exam_tips": [],
                    "glossary": []
                }))
            raise Exception(f"Unexpected model {model}")

        mock_instance.models.generate_content.side_effect = fake_generate

        res = self.client.post('/api/generate-notes', data={
            'youtubeUrl': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
        }, headers={'X-Gemini-Api-Key': 'fake-test-key-12345'})

        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertTrue(data['success'])
        self.assertEqual(data['model_used'], "gemini-3.5-flash-lite")

        # Verify calls: 3.8-flash was called exactly once (no retry), then 3.5-flash-lite was called once
        calls = mock_instance.models.generate_content.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][1]['model'], "gemini-3.8-flash")
        self.assertEqual(calls[1][1]['model'], "gemini-3.5-flash-lite")

    @patch('app.get_youtube_transcript')
    @patch('google.genai.Client')
    def test_quota_exhausted_does_not_call_last_resort_models(self, mock_client_class, mock_transcript):
        """When 3.8 and 3.5-lite both fail with 429, 3.7 and 3.6 are NOT called."""
        mock_transcript.return_value = {
            "success": True,
            "timed_text": "[00:01] Intro",
            "full_text": "Intro",
            "duration_seconds": 10
        }
        mock_instance = mock_client_class.return_value
        called_models = []

        def fake_generate(model, contents, config):
            called_models.append(model)
            raise Exception("429 RESOURCE_EXHAUSTED. You exceeded your current quota...")

        mock_instance.models.generate_content.side_effect = fake_generate

        res = self.client.post('/api/generate-notes', data={
            'youtubeUrl': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
        }, headers={'X-Gemini-Api-Key': 'fake-test-key-12345'})

        self.assertEqual(res.status_code, 429)
        # Should only have called 3.8 and 3.5-lite, NOT 3.7 or 3.6
        self.assertEqual(called_models, ["gemini-3.8-flash", "gemini-3.5-flash-lite"])

    @patch('app.get_youtube_transcript')
    @patch('google.genai.Client')
    def test_non_quota_error_calls_last_resort_models(self, mock_client_class, mock_transcript):
        """When 3.8 and 3.5-lite fail with non-quota errors, 3.7 is called as last resort."""
        mock_transcript.return_value = {
            "success": True,
            "timed_text": "[00:01] Intro",
            "full_text": "Intro",
            "duration_seconds": 10
        }
        mock_instance = mock_client_class.return_value

        def fake_generate(model, contents, config):
            if model in ["gemini-3.8-flash", "gemini-3.5-flash-lite"]:
                raise Exception("500 INTERNAL_SERVER_ERROR")
            if model == "gemini-3.7-flash":
                return MagicMock(text=json.dumps({
                    "title": "Apunte desde Ultimo Recurso",
                    "topic_overview": "Resumen",
                    "estimated_study_time": "10 min",
                    "key_takeaways": [],
                    "developments": [],
                    "general_diagram": {"title": "", "mermaid_code": ""},
                    "flashcards": [],
                    "quiz": [],
                    "exam_tips": [],
                    "glossary": []
                }))
            raise Exception(f"Unexpected model {model}")

        mock_instance.models.generate_content.side_effect = fake_generate

        res = self.client.post('/api/generate-notes', data={
            'youtubeUrl': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
        }, headers={'X-Gemini-Api-Key': 'fake-test-key-12345'})

        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertTrue(data['success'])
        self.assertEqual(data['model_used'], "gemini-3.7-flash")


    @patch('app.get_youtube_transcript')
    @patch('google.genai.Client')
    def test_model_not_found_404_returns_clear_message(self, mock_client_class, mock_transcript):
        """When all models return 404 (model not found / deprecated), a clear 404 response is returned."""
        mock_transcript.return_value = {
            "success": True,
            "timed_text": "[00:01] Intro",
            "full_text": "Intro",
            "duration_seconds": 10
        }
        mock_instance = mock_client_class.return_value
        mock_instance.models.generate_content.side_effect = Exception("404 NOT_FOUND. models/gemini-old is not found for API version v1")

        res = self.client.post('/api/generate-notes', data={
            'youtubeUrl': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
        }, headers={'X-Gemini-Api-Key': 'fake-test-key-12345'})

        self.assertEqual(res.status_code, 404)
        data = json.loads(res.data)
        self.assertFalse(data['success'])
        self.assertIn("no está disponible o ha sido discontinuado", data['error'])

    @patch('app.get_youtube_transcript')
    @patch('google.genai.Client')
    def test_token_limit_400_returns_clear_message(self, mock_client_class, mock_transcript):
        """When Gemini returns a 400 token/context limit error, a clear 400 response is returned."""
        mock_transcript.return_value = {
            "success": True,
            "timed_text": "[00:01] Intro",
            "full_text": "Intro",
            "duration_seconds": 10
        }
        mock_instance = mock_client_class.return_value
        mock_instance.models.generate_content.side_effect = Exception("400 INVALID_ARGUMENT. Request payload exceeds the maximum context length of tokens")

        res = self.client.post('/api/generate-notes', data={
            'youtubeUrl': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
        }, headers={'X-Gemini-Api-Key': 'fake-test-key-12345'})

        self.assertEqual(res.status_code, 400)
        data = json.loads(res.data)
        self.assertFalse(data['success'])
        self.assertIn("límite máximo de tokens", data['error'])

    @patch('app.get_youtube_transcript')
    @patch('google.genai.Client')
    def test_model_fallback_on_404_skips_to_next_model(self, mock_client_class, mock_transcript):
        """When primary model returns 404 (deprecated), it automatically skips to the next available model."""
        mock_transcript.return_value = {
            "success": True,
            "timed_text": "[00:01] Intro",
            "full_text": "Intro",
            "duration_seconds": 10
        }
        mock_instance = mock_client_class.return_value

        def fake_generate(model, contents, config):
            if model == "gemini-3.8-flash":
                raise Exception("404 NOT_FOUND. models/gemini-3.8-flash is deprecated")
            if model == "gemini-3.5-flash-lite":
                return MagicMock(text=json.dumps({
                    "title": "Apunte de 3.5-flash-lite",
                    "topic_overview": "Resumen",
                    "estimated_study_time": "10 min",
                    "key_takeaways": [],
                    "developments": [],
                    "general_diagram": {"title": "", "mermaid_code": ""},
                    "flashcards": [],
                    "quiz": [],
                    "exam_tips": [],
                    "glossary": []
                }))
            raise Exception(f"Unexpected model {model}")

        mock_instance.models.generate_content.side_effect = fake_generate

        res = self.client.post('/api/generate-notes', data={
            'youtubeUrl': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
        }, headers={'X-Gemini-Api-Key': 'fake-test-key-12345'})

        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertTrue(data['success'])
        self.assertEqual(data['model_used'], "gemini-3.5-flash-lite")


if __name__ == '__main__':

    unittest.main()

