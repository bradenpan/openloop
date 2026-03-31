.PHONY: dev dev-backend dev-frontend test lint lint-fix migrate seed generate-types backup backup-gdrive

dev:
	@echo "Starting backend and frontend..."
	$(MAKE) dev-backend & $(MAKE) dev-frontend & wait

dev-backend:
	cd backend && uvicorn openloop.main:app --reload --host 0.0.0.0 --port 8000

dev-frontend:
	cd frontend && npx vite --host --port 5173

test:
	pytest backend/tests/

lint:
	ruff check backend/ contract/ scripts/
	ruff format --check backend/ contract/ scripts/

lint-fix:
	ruff format backend/ contract/ scripts/
	ruff check --fix backend/ contract/ scripts/

migrate:
	cd backend && alembic upgrade head

seed:
	python scripts/seed.py

generate-types:
	python scripts/export_openapi.py
	npx openapi-typescript contract/openapi.json -o frontend/src/api/types.ts

backup:
	@echo "TODO: Backup database"

backup-gdrive:
	@echo "TODO: Backup to Google Drive"
