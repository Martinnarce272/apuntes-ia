import unittest
from unittest.mock import patch, MagicMock
import json
import io
import os
from app import extract_youtube_id, app, robust_parse_json, call_gemini_api_with_fallback

class TestApuntesIAGeminiDirect(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        # Asegurar clave ficticia para tests donde no testeamos el 401
        self.original_env_key = os.environ.get('GEMINI_API_KEY')
        os.environ['GEMINI_API_KEY'] = 'test-fake-key-for-unit-tests'

    def tearDown(self):
        if self.original_env_key:
            os.environ['GEMINI_API_KEY'] = self.original_env_key
        elif 'GEMINI_API_KEY' in os.environ:
            del os.environ['GEMINI_API_KEY']

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
        self.assertEqual(data.get('engine'), 'gemini-direct')
        self.assertTrue(data.get('has_api_key'))

    @patch('requests.post')
    def test_save_key_valid(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        res = self.client.post('/api/save-key', json={'apiKey': 'valid-gemini-key'})
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertTrue(data['success'])
        self.assertEqual(os.environ.get('GEMINI_API_KEY'), 'valid-gemini-key')

    @patch('requests.post')
    def test_save_key_invalid(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.text = "API_KEY_INVALID"
        mock_post.return_value = mock_resp

        res = self.client.post('/api/save-key', json={'apiKey': 'bad-key'})
        self.assertEqual(res.status_code, 400)
        data = json.loads(res.data)
        self.assertFalse(data['success'])

    def test_youtube_preview(self):
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
        self.assertIn('key_takeaways', data['data'])
        self.assertIn('general_diagram', data['data'])

    def test_robust_parse_json(self):
        # 1. Standard markdown fences
        fenced_json = '```json\n{"title": "Test Note", "status": "ok"}\n```'
        parsed = robust_parse_json(fenced_json)
        self.assertEqual(parsed["title"], "Test Note")

        # 2. Unescaped LaTeX backslashes
        latex_json = r'{"formula": "\frac{-b \pm \sqrt{b^2 - 4ac}}{2a}", "symbol": "\Delta"}'
        parsed_latex = robust_parse_json(latex_json)
        self.assertIn("frac", parsed_latex["formula"])
        self.assertIn("Delta", parsed_latex["symbol"])

        # 3. Leading and trailing conversational text
        wrapped_json = 'Aquí tienes el apunte:\n\n{"title": "Wrapped"}\n\nEspero te sirva!'
        parsed_wrapped = robust_parse_json(wrapped_json)
        self.assertEqual(parsed_wrapped["title"], "Wrapped")

    @patch('requests.post')
    def test_call_gemini_api_with_fallback(self, mock_post):
        # Primer modelo (3.8) falla con 500, segundo modelo (3.7) responde con 200
        mock_resp_fail = MagicMock()
        mock_resp_fail.status_code = 500
        mock_resp_fail.text = "Internal error"

        mock_resp_ok = MagicMock()
        mock_resp_ok.status_code = 200
        mock_resp_ok.json.return_value = {
            "candidates": [{
                "content": {
                    "parts": [{"text": '{"title": "Fallback Note"}'}]
                }
            }]
        }
        mock_post.side_effect = [mock_resp_fail, mock_resp_ok]

        text, model = call_gemini_api_with_fallback("system", "prompt", "test-key")
        self.assertEqual(model, "gemini-3.7-flash")
        self.assertIn("Fallback Note", text)

    @patch('app.call_gemini_api_with_fallback')
    @patch('app.get_youtube_transcript')
    def test_generate_notes_endpoint_with_subtitles(self, mock_transcript, mock_gemini):
        mock_transcript.return_value = {
            "success": True,
            "timed_text": "[00:01] Bienvenidos al curso de Álgebra Lineal",
            "full_text": "Bienvenidos al curso de Álgebra Lineal",
            "duration_seconds": 120
        }

        mock_gemini.return_value = (
            json.dumps({
                "title": "Álgebra Lineal",
                "topic_overview": "Conceptos clave de matrices y espacios vectoriales.",
                "estimated_study_time": "15 min",
                "key_takeaways": [{"title": "Determinante", "description": "Si es 0, no es invertible", "type": "critical"}],
                "developments": [{"unit_number": 1, "title": "Matrices", "content_markdown": "Definición y operaciones."}]
            }),
            "gemini-3.8-flash"
        )

        res = self.client.post('/api/generate-notes', data={
            'youtubeUrl': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
            'depth': 'completo',
            'instructions': 'Enfocarse en matrices'
        })

        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertTrue(data['success'])
        self.assertEqual(data['model_used'], 'gemini-3.8-flash')
        self.assertIn('data', data)
        self.assertEqual(data['data']['title'], "Álgebra Lineal")

        # Check sources metadata
        sources = data['data']['sources']
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]['type'], 'youtube')
        self.assertTrue(sources[0]['has_captions'])
        self.assertEqual(sources[0]['id'], 'dQw4w9WgXcQ')

    @patch('app.call_gemini_api_with_fallback')
    @patch('app.transcribe_youtube_audio_with_whisper')
    @patch('app.get_youtube_transcript')
    def test_generate_notes_endpoint_with_whisper_fallback(self, mock_transcript, mock_whisper, mock_gemini):
        mock_transcript.return_value = {
            "success": False,
            "error": "No subtitles available"
        }

        mock_whisper.return_value = {
            "success": True,
            "timed_text": "[00:05] Audio transcrito con Whisper sobre Termodinámica",
            "full_text": "Audio transcrito con Whisper sobre Termodinámica",
            "duration_seconds": 95
        }

        mock_gemini.return_value = (
            json.dumps({
                "title": "Termodinámica",
                "topic_overview": "Leyes de la termodinámica",
                "developments": []
            }),
            "gemini-3.8-flash"
        )

        res = self.client.post('/api/generate-notes', data={
            'youtubeUrl': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
            'depth': 'exhaustivo'
        })

        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertTrue(data['success'])
        sources = data['data']['sources']
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]['type'], 'youtube')
        self.assertFalse(sources[0]['has_captions'])
        self.assertEqual(sources[0]['mode'], 'whisper_audio')

    @patch('app.call_gemini_api_with_fallback')
    @patch('app.extract_pdf_text')
    def test_generate_notes_endpoint_with_pdf(self, mock_extract_pdf, mock_gemini):
        mock_extract_pdf.return_value = {
            "success": True,
            "content": "Capítulo 1: Cinemática.",
            "pages": 4
        }

        mock_gemini.return_value = (
            json.dumps({
                "title": "Cinemática",
                "developments": []
            }),
            "gemini-3.8-flash"
        )

        data = {
            'depth': 'conciso',
            'pdfFiles': (io.BytesIO(b'%PDF-1.4 dummy content'), 'fisica_mecanica.pdf')
        }

        res = self.client.post('/api/generate-notes', data=data, content_type='multipart/form-data')
        self.assertEqual(res.status_code, 200)
        res_data = json.loads(res.data)
        self.assertTrue(res_data['success'])
        self.assertEqual(res_data['data']['title'], 'Cinemática')

    def test_generate_notes_no_key_returns_401(self):
        if 'GEMINI_API_KEY' in os.environ:
            del os.environ['GEMINI_API_KEY']

        res = self.client.post('/api/generate-notes', data={
            'youtubeUrl': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
        })
        self.assertEqual(res.status_code, 401)
        data = json.loads(res.data)
        self.assertFalse(data['success'])
        self.assertEqual(data.get('error_code'), 'no_api_key')

    def test_generate_notes_empty_sources_returns_400(self):
        res = self.client.post('/api/generate-notes', data={
            'depth': 'completo'
        })
        self.assertEqual(res.status_code, 400)
        data = json.loads(res.data)
        self.assertFalse(data['success'])
        self.assertIn("Debes proporcionar al menos un enlace de YouTube", data['error'])

if __name__ == '__main__':
    unittest.main()
