dev:
	cmd.exe /c start "Project Chess backend" cmd.exe /c ".\.venv\Scripts\python.exe -m uvicorn backend.app:app --host 127.0.0.1 --port 8000"
	cd frontend && npm.cmd run dev -- --open

backend:
	.\.venv\Scripts\python.exe -m uvicorn backend.app:app --host 127.0.0.1 --port 8000

frontend:
	cd frontend && npm.cmd run dev

test:
	.\.venv\Scripts\python.exe -m unittest backend.test_core
	cd frontend && npm.cmd run check
	cd frontend && npm.cmd run build

.PHONY: dev backend frontend test
