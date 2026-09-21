.PHONY: help test lint validate compose-up compose-down deploy up down destroy

help:
	@echo "test         roda os testes da API"
	@echo "lint         roda o ruff na API"
	@echo "validate     roda o cfn-lint nos templates"
	@echo "compose-up   sobe API e Postgres localmente"
	@echo "compose-down derruba o ambiente local"
	@echo "deploy       faz deploy das stacks na AWS"
	@echo "up           escala para 1, descobre o IP e publica o front"
	@echo "down         escala para 0 (para de cobrar Fargate)"
	@echo "destroy      remove todas as stacks do laboratorio"

test:
	cd api && .venv/bin/pytest -q

lint:
	cd api && .venv/bin/ruff check .

validate:
	cd api && .venv/bin/cfn-lint ../infra/*.yaml

compose-up:
	cd api && docker compose up -d --build

compose-down:
	cd api && docker compose down -v

deploy:
	./scripts/deploy.sh

up:
	./scripts/up.sh

down:
	./scripts/down.sh

destroy:
	./scripts/destroy.sh
