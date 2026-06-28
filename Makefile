# =============================================================================
#  PathlBank — Makefile
#  Lokalne PC:   make dev / make stop / make test
#  Serwer prod:  make release  →  deploy na pathl.pl
# =============================================================================

# --------------- Konfiguracja lokalna ----------------------------------------
PYTHON      := .venv/bin/python
PIP         := .venv/bin/pip
VENV        := .venv
FLASK_PORT  := 5000
SOCKET_PORT := 9999
TEST_SCRIPT := /home/neon/.gemini/antigravity-ide/brain/7e27d2d9-7ddd-42f0-8ceb-263ecc9750fe/scratch/test_auth.py

# --------------- Konfiguracja serwera produkcyjnego --------------------------
SERVER_USER      := neon
SERVER_HOST      := pathl.pl
SERVER_DIR       := /var/www/bank
SERVER_SERVICE   := pathl-bank
GUNICORN_WORKERS := 4
GUNICORN_PORT    := 8000

# --------------- Kolory do terminala -----------------------------------------
RESET  := \033[0m
BOLD   := \033[1m
GREEN  := \033[32m
YELLOW := \033[33m
CYAN   := \033[36m
RED    := \033[31m

# --------------- Phony targets -----------------------------------------------
.PHONY: help install dev run socket stop kill \
        test test-verbose db logs \
        release deploy ssh logs-remote \
        clean

# =============================================================================
#  HELP
# =============================================================================
help:
	@printf "\n$(BOLD)$(CYAN)╔══════════════════════════════════════════════╗$(RESET)\n"
	@printf "$(BOLD)$(CYAN)║          PathlBank — Makefile Help           ║$(RESET)\n"
	@printf "$(BOLD)$(CYAN)╚══════════════════════════════════════════════╝$(RESET)\n\n"
	@printf "$(BOLD)🛠  LOKALNE ŚRODOWISKO$(RESET)\n"
	@printf "  $(GREEN)make install$(RESET)      — Zainstaluj zależności Python (venv)\n"
	@printf "  $(GREEN)make dev$(RESET)          — Uruchom Flask dev server (port $(FLASK_PORT))\n"
	@printf "  $(GREEN)make socket$(RESET)       — Uruchom serwer TCP (port $(SOCKET_PORT))\n"
	@printf "  $(GREEN)make stop$(RESET)         — Zatrzymaj lokalne serwery\n"
	@printf "  $(GREEN)make kill$(RESET)         — Wymuś zwolnienie portu $(FLASK_PORT)\n"
	@printf "  $(GREEN)make db$(RESET)           — Uruchom migrację bazy danych\n"
	@printf "  $(GREEN)make logs$(RESET)         — Pokaż logi lokalne (bank_server.log)\n\n"
	@printf "$(BOLD)🧪 TESTY$(RESET)\n"
	@printf "  $(GREEN)make test$(RESET)         — Uruchom wszystkie testy automatyczne\n"
	@printf "  $(GREEN)make test-verbose$(RESET) — Testy z pełnym outputem\n\n"
	@printf "$(BOLD)🚀 PRODUKCJA (pathl.pl)$(RESET)\n"
	@printf "  $(GREEN)make release$(RESET)      — Test + deploy + restart na pathl.pl\n"
	@printf "  $(GREEN)make deploy$(RESET)       — Tylko sync plików (bez restartu)\n"
	@printf "  $(GREEN)make ssh$(RESET)          — Połącz przez SSH z serwerem\n"
	@printf "  $(GREEN)make logs-remote$(RESET)  — Pokaż logi produkcyjne (przez SSH)\n\n"
	@printf "$(BOLD)🧹 CLEANUP$(RESET)\n"
	@printf "  $(GREEN)make clean$(RESET)        — Usuń cache, pyc, logi\n\n"

# =============================================================================
#  LOKALNE ŚRODOWISKO
# =============================================================================

## Instalacja zależności
install:
	@printf "$(CYAN)▶ Tworzenie środowiska wirtualnego...$(RESET)\n"
	@test -d $(VENV) || python3 -m venv $(VENV)
	@printf "$(CYAN)▶ Instalowanie zależności z req.txt...$(RESET)\n"
	@$(PIP) install --upgrade pip -q
	@$(PIP) install -r req.txt
	@printf "$(GREEN)✔ Zależności zainstalowane.$(RESET)\n"

## Serwer Flask (tryb developerski)
dev: kill
	@printf "$(CYAN)▶ Uruchamianie Flask dev server na porcie $(FLASK_PORT)...$(RESET)\n"
	$(PYTHON) web_server.py

## Alias dla dev
run: dev

## Serwer TCP (socket)
socket:
	@printf "$(CYAN)▶ Uruchamianie serwera TCP na porcie $(SOCKET_PORT)...$(RESET)\n"
	$(PYTHON) server.py

## Zatrzymaj lokalne serwery
stop:
	@printf "$(YELLOW)▶ Zatrzymywanie lokalnych serwerów...$(RESET)\n"
	@pkill -f "python.*web_server.py" 2>/dev/null \
		&& printf "$(GREEN)✔ web_server zatrzymany.$(RESET)\n" \
		|| printf "  web_server nie działał.\n"
	@pkill -f "python.*server.py" 2>/dev/null \
		&& printf "$(GREEN)✔ server.py zatrzymany.$(RESET)\n" \
		|| printf "  server.py nie działał.\n"

## Wymuś zwolnienie portu 5000
kill:
	@PID=$$(lsof -ti :$(FLASK_PORT) 2>/dev/null); \
	if [ -n "$$PID" ]; then \
		printf "$(YELLOW)▶ Zwalniam port $(FLASK_PORT) (PID: $$PID)...$(RESET)\n"; \
		kill -9 $$PID 2>/dev/null; \
		printf "$(GREEN)✔ Port $(FLASK_PORT) zwolniony.$(RESET)\n"; \
	else \
		printf "  Port $(FLASK_PORT) jest wolny.\n"; \
	fi

## Migracja bazy danych
db:
	@printf "$(CYAN)▶ Uruchamianie migracji bazy danych...$(RESET)\n"
	@$(PYTHON) -c "from server import Server, User; s = Server(User); print('OK')"
	@printf "$(GREEN)✔ Migracja zakończona.$(RESET)\n"

## Logi lokalne
logs:
	@printf "$(CYAN)▶ Logi lokalne (bank_server.log):$(RESET)\n"
	@tail -80 bank_server.log 2>/dev/null || printf "$(YELLOW)  Brak pliku bank_server.log$(RESET)\n"

# =============================================================================
#  TESTY
# =============================================================================

test:
	@printf "\n$(BOLD)$(CYAN)▶ Uruchamianie testów automatycznych...$(RESET)\n\n"
	@$(PYTHON) -m pytest $(TEST_SCRIPT) -v --tb=short 2>/dev/null \
	  || $(PYTHON) $(TEST_SCRIPT) -v

test-verbose:
	@printf "$(BOLD)$(CYAN)▶ Testy z pełnym outputem...$(RESET)\n"
	@$(PYTHON) $(TEST_SCRIPT) -v

# =============================================================================
#  PRODUKCJA — deploy na pathl.pl
# =============================================================================

## Pełny release: testy + sync + restart usługi na serwerze
release: test deploy
	@printf "$(CYAN)▶ Restartuję usługę $(SERVER_SERVICE) na $(SERVER_HOST)...$(RESET)\n"
	@ssh $(SERVER_USER)@$(SERVER_HOST) "\
		cd $(SERVER_DIR) && \
		.venv/bin/pip install -r req.txt -q && \
		sudo systemctl restart $(SERVER_SERVICE) && \
		sudo systemctl status $(SERVER_SERVICE) --no-pager -l"
	@printf "$(GREEN)✔ Release zakończony! Aplikacja działa na https://pathl.pl$(RESET)\n"

## Tylko sync plików (rsync, bez restartu)
deploy:
	@printf "$(CYAN)▶ Synchronizacja plików → $(SERVER_USER)@$(SERVER_HOST):$(SERVER_DIR)...$(RESET)\n"
	@rsync -avz --progress \
		--exclude='.venv' \
		--exclude='__pycache__' \
		--exclude='*.pyc' \
		--exclude='.env' \
		--exclude='bank_server.log' \
		--exclude='.git' \
		--exclude='*.sock' \
		. $(SERVER_USER)@$(SERVER_HOST):$(SERVER_DIR)/
	@printf "$(GREEN)✔ Pliki zsynchronizowane.$(RESET)\n"

## SSH do serwera
ssh:
	@printf "$(CYAN)▶ Łączenie z $(SERVER_USER)@$(SERVER_HOST)...$(RESET)\n"
	@ssh $(SERVER_USER)@$(SERVER_HOST)

## Logi produkcyjne
logs-remote:
	@printf "$(CYAN)▶ Logi produkcyjne z $(SERVER_HOST):$(RESET)\n"
	@ssh $(SERVER_USER)@$(SERVER_HOST) \
		"journalctl -u $(SERVER_SERVICE) -n 100 --no-pager 2>/dev/null \
		 || tail -100 $(SERVER_DIR)/bank_server.log"

# =============================================================================
#  CLEANUP
# =============================================================================

clean:
	@printf "$(YELLOW)▶ Czyszczenie projektu...$(RESET)\n"
	@find . -type f -name "*.pyc" -delete
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	@rm -f bank_server.log
	@printf "$(GREEN)✔ Projekt wyczyszczony.$(RESET)\n"
