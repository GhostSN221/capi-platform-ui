.PHONY: demo-up demo-down test

demo-up:
	docker compose -f docker-compose.demo.yml up -d --build

demo-down:
	docker compose -f docker-compose.demo.yml down -v

test:
	cd backend && pytest -q
