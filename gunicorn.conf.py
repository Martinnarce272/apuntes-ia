# Gunicorn configuration file
# Automatically read by Gunicorn in Render and production environments

import os

# Set timeout to 5 minutes (300 seconds) so LLM generation and video processing never get killed at 30s
timeout = 300
workers = 2
threads = 4
worker_class = 'sync'
keepalive = 5

port = os.environ.get('PORT', '5001')
bind = f'0.0.0.0:{port}'
