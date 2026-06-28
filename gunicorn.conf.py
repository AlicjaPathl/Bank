# =============================================================================
#  Gunicorn — konfiguracja produkcyjna (pathl.pl)
#  Uruchomienie: gunicorn -c gunicorn.conf.py web_server:app
# =============================================================================

import multiprocessing

# Adres i port
bind = "127.0.0.1:8000"

# Liczba workerów (reguła: 2 * CPU + 1)
workers = multiprocessing.cpu_count() * 2 + 1
worker_class = "sync"
worker_connections = 1000

# Timeouty
timeout = 30
keepalive = 5

# Logowanie
accesslog = "/var/log/bank/access.log"
errorlog  = "/var/log/bank/error.log"
loglevel  = "info"

# Pid
pidfile = "/var/run/bank/gunicorn.pid"

# Bezpieczeństwo
limit_request_line    = 4094
limit_request_fields  = 100
limit_request_field_size = 8190

# Auto-restart przy zmianie kodu (tylko dla dev, wyłącz na prod)
reload = False
