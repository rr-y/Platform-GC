.PHONY: dev stop restart logs test migrate shell

# ── Local development ─────────────────────────────────────────────────────────

dev:
	@echo "Stopping any running containers..."
	@docker-compose down --remove-orphans 2>/dev/null || true
	@mkdir -p data
	@echo "Starting backend (api + postgres + redis)..."
	docker-compose up --build

restart: dev

stop:
	docker-compose down --remove-orphans

logs:
	docker-compose logs -f api

# ── Database ──────────────────────────────────────────────────────────────────

migrate:
	docker-compose run --rm api sh -c ".venv/bin/alembic upgrade head"

# ── Tests ─────────────────────────────────────────────────────────────────────

test:
	uv run pytest tests/ -v

# ── Utilities ─────────────────────────────────────────────────────────────────

shell:
	docker-compose exec api sh
