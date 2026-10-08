#!/bin/sh
# E2E: боевой образ + PostgreSQL + Caddy (с HTTPS от внутреннего CA), в браузере Chromium проходим
# сценарии клиента и менеджера. Нужен только Docker. Запуск: sh e2e/run.sh   (или make e2e)
set -eu
cd "$(dirname "$0")/.."

PROJECT=polygon3d-e2e
PLAYWRIGHT_IMAGE=mcr.microsoft.com/playwright/python:v1.63.0-noble
ADMIN_USER=e2e_admin
ADMIN_PASSWORD=e2e-admin-password-91
FAILED=0

compose() {
    docker compose -p "$PROJECT" -f deploy/docker-compose.prod.yml -f e2e/docker-compose.e2e.yml \
        --env-file e2e/e2e.env "$@"
}

cleanup() {
    if [ "$FAILED" -ne 0 ]; then
        echo "--- логи web и caddy ---"
        compose logs --tail 50 web caddy 2>&1 || true
    fi
    compose down -v >/dev/null 2>&1 || true
}
trap 'FAILED=1; cleanup' INT TERM
trap 'cleanup' EXIT

echo "==> Сборка боевого образа"
docker build -q -t polygon3d:e2e . >/dev/null

echo "==> Стек: PostgreSQL + web + Caddy"
compose up -d db web caddy

echo "==> Демо-данные и администратор"
compose exec -T web python manage.py seed_demo >/dev/null
compose exec -T -e DJANGO_SUPERUSER_PASSWORD="$ADMIN_PASSWORD" web \
    python manage.py createsuperuser --noinput --username "$ADMIN_USER" --email admin@e2e.test >/dev/null

echo "==> Тесты в Chromium ($PLAYWRIGHT_IMAGE)"
docker run --rm --init --ipc=host --network "${PROJECT}_default" \
    -v "$PWD/e2e:/e2e:ro" \
    -e PYTHONDONTWRITEBYTECODE=1 \
    -e E2E_BASE_URL=https://e2e.internal -e E2E_ADMIN_USER="$ADMIN_USER" -e E2E_ADMIN_PASSWORD="$ADMIN_PASSWORD" \
    "$PLAYWRIGHT_IMAGE" \
    sh -c "pip install -q --root-user-action=ignore -r /e2e/requirements.txt && pytest -v --durations=5 -p no:cacheprovider /e2e" \
    || { FAILED=1; exit 1; }
echo "E2E PASSED"
