.PHONY: up down logs build test smoke e2e scan lock lint format migrations superuser seed shell

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

e2e:
	sh e2e/run.sh

scan:  # те же проверки, что в .github/workflows/security.yml
	docker run --rm -v "$(PWD)":/src -w /src python:3.13-slim sh -c "pip install -q pip-audit && pip-audit -r requirements.txt --require-hashes --progress-spinner off"
	docker run --rm -v "$(PWD)":/repo zricethezav/gitleaks:latest detect --source /repo --config /repo/.gitleaks.toml --redact --no-banner
	docker build -q -t polygon3d:scan . && docker save polygon3d:scan -o /tmp/polygon3d-scan.tar
	docker run --rm -v /tmp/polygon3d-scan.tar:/img.tar:ro -v trivy-cache:/root/.cache aquasec/trivy:latest image --input /img.tar --severity HIGH,CRITICAL --ignore-unfixed --scanners vuln --exit-code 1

lock:
	docker run --rm -v "$(PWD)":/src -w /src python:3.13-slim sh -c "pip install -q pip-tools && \
		pip-compile -q --generate-hashes --strip-extras --allow-unsafe -o requirements.txt requirements.in && \
		pip-compile -q --generate-hashes --strip-extras --allow-unsafe -o requirements-dev.txt requirements-dev.in"

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
