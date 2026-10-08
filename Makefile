.PHONY: up down logs build test smoke lint format migrations superuser seed shell

up:
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f web bot

build:
	docker compose build

test:
	docker compose run --rm -e DJANGO_DEBUG=0 web python manage.py test -v 2

smoke:
	sh scripts/smoke_test.sh

lint:
	docker run --rm -v "$(PWD)":/src -w /src ghcr.io/astral-sh/ruff check .
	docker run --rm -v "$(PWD)":/src -w /src ghcr.io/astral-sh/ruff format --check .

format:
	docker run --rm -v "$(PWD)":/src -w /src ghcr.io/astral-sh/ruff format .
	docker run --rm -v "$(PWD)":/src -w /src ghcr.io/astral-sh/ruff check --fix .

migrations:
	docker compose run --rm web python manage.py makemigrations

superuser:
	docker compose run --rm web python manage.py createsuperuser

seed:
	docker compose run --rm web python manage.py seed_demo

shell:
	docker compose run --rm web python manage.py shell
