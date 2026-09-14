import os

port = os.environ.get('PORT', '5001')
bind = f"0.0.0.0:{port}"

# 1 worker to minimize memory footprint on 512MB RAM instances
workers = 1

# Multi-threaded I/O without extra memory overhead
worker_class = "gthread"
threads = 4

# Extended timeout (300s) to prevent Gunicorn arbiter SIGKILL during Gemini video processing
timeout = 300
graceful_timeout = 30
keepalive = 5

# Periodically recycle worker to prevent memory fragmentation
max_requests = 100
max_requests_jitter = 10
