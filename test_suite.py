import unittest
from unittest.mock import patch, MagicMock
import json
import io
from app import extract_youtube_id, app, robust_parse_json, SYSTEM_INSTRUCTION

class TestApuntesIAPuter(unittest.TestCase):
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
        self.assertEqual(data.get('engine'), 'puter.js')
        self.assertTrue(data.get('puter_ready'))

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

    @patch('app.get_youtube_transcript')
    def test_generate_notes_endpoint_with_subtitles(self, mock_transcript):
        mock_transcript.return_value = {
            "success": True,
            "timed_text": "[00:01] Bienvenidos al curso de Álgebra Lineal",
            "full_text": "Bienvenidos al curso de Álgebra Lineal",
            "duration_seconds": 120
        }

        res = self.client.post('/api/generate-notes', data={
            'youtubeUrl': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
            'depth': 'balanced',
            'instructions': 'Enfocarse en matrices'
        })

        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertTrue(data['success'])
        self.assertIn('system_instruction', data)
        self.assertIn('user_prompt', data)
        self.assertIn('sources', data)

        # Check prompt contents
        self.assertIn("Bienvenidos al curso de Álgebra Lineal", data['user_prompt'])
        self.assertIn("Enfocarse en matrices", data['user_prompt'])

        # Check sources metadata
        sources = data['sources']
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]['type'], 'youtube')
        self.assertTrue(sources[0]['has_captions'])
        self.assertEqual(sources[0]['id'], 'dQw4w9WgXcQ')

    @patch('app.transcribe_youtube_audio_with_whisper')
    @patch('app.get_youtube_transcript')
    def test_generate_notes_endpoint_with_whisper_fallback(self, mock_transcript, mock_whisper):
        # Video has no YouTube captions
        mock_transcript.return_value = {
            "success": False,
            "error": "No subtitles available"
        }

        # Whisper fallback succeeds
        mock_whisper.return_value = {
            "success": True,
            "timed_text": "[00:05] Audio transcrito localmente con Whisper sobre Termodinámica",
            "full_text": "Audio transcrito localmente con Whisper sobre Termodinámica",
            "duration_seconds": 95
        }

        res = self.client.post('/api/generate-notes', data={
            'youtubeUrl': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
            'depth': 'detailed'
        })

        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertTrue(data['success'])
        self.assertIn("Audio transcrito localmente con Whisper sobre Termodinámica", data['user_prompt'])

        sources = data['sources']
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]['type'], 'youtube')
        self.assertFalse(sources[0]['has_captions'])
        self.assertEqual(sources[0]['mode'], 'whisper_audio')
        self.assertEqual(sources[0]['id'], 'dQw4w9WgXcQ')

    @patch('app.extract_pdf_text')
    def test_generate_notes_endpoint_with_pdf(self, mock_extract_pdf):
        mock_extract_pdf.return_value = {
            "success": True,
            "content": "Capítulo 1: Cinemática. Ecuaciones del Movimiento Uniformemente Acelerado.",
            "pages": 4
        }

        data = {
            'depth': 'quick',
            'pdfFiles': (io.BytesIO(b'%PDF-1.4 dummy content'), 'fisica_mecanica.pdf')
        }

        res = self.client.post('/api/generate-notes', data=data, content_type='multipart/form-data')
        self.assertEqual(res.status_code, 200)
        res_data = json.loads(res.data)
        self.assertTrue(res_data['success'])
        self.assertIn("Cinemática", res_data['user_prompt'])

        sources = res_data['sources']
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]['type'], 'pdf')
        self.assertEqual(sources[0]['filename'], 'fisica_mecanica.pdf')
        self.assertEqual(sources[0]['pages'], 4)

    def test_generate_notes_empty_sources_returns_400(self):
        res = self.client.post('/api/generate-notes', data={
            'depth': 'balanced'
        })
        self.assertEqual(res.status_code, 400)
        data = json.loads(res.data)
        self.assertFalse(data['success'])
        self.assertIn("Debes proporcionar al menos un enlace de YouTube", data['error'])

if __name__ == '__main__':
    unittest.main()
