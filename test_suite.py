import unittest
from unittest.mock import patch, MagicMock
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
        fake_response = MagicMock()
        fake_response.text = json.dumps({
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
        mock_instance.models.generate_content.return_value = fake_response
        
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
        
        # Verify generate_content received multimodal FileData Part
        call_kwargs = mock_instance.models.generate_content.call_args[1]
        contents = call_kwargs['contents']
        self.assertIsInstance(contents, list)
        self.assertEqual(len(contents), 2)
        video_part = contents[0]
        self.assertTrue(hasattr(video_part, 'file_data'))
        self.assertIn('dQw4w9WgXcQ', video_part.file_data.file_uri)

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
        
        # Verify contents was passed as text prompt string with the transcript
        call_kwargs = mock_instance.models.generate_content.call_args[1]
        contents = call_kwargs['contents']
        self.assertIsInstance(contents, str)
        self.assertIn("Hola bienvenidos a la clase", contents)

if __name__ == '__main__':
    unittest.main()
