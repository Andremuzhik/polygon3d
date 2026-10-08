#!/bin/sh
# Smoke-тест боевого образа: собирает его, поднимает вместе с PostgreSQL и проверяет страницы.
# Запуск: sh scripts/smoke_test.sh   (или make smoke). Нужен только Docker.
set -eu

IMAGE="${IMAGE:-polygon3d:smoke}"
PORT="${SMOKE_PORT:-18000}"
RUN="smoke-$$"
NET="$RUN-net"
DB="$RUN-db"
WEB="$RUN-web"
FAILED=0

cleanup() {
    if [ "$FAILED" -ne 0 ]; then
        echo "--- логи web ---"
        docker logs "$WEB" 2>&1 | tail -40 || true
    fi
    docker rm -f "$WEB" "$DB" >/dev/null 2>&1 || true
    docker network rm "$NET" >/dev/null 2>&1 || true
}
trap 'FAILED=1; cleanup' INT TERM
trap 'cleanup' EXIT

fail() {
    echo "FAIL: $*" >&2
    FAILED=1
    exit 1
}

check_status() { # путь, ожидаемый код
    code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT$1")
    [ "$code" = "$2" ] || fail "GET $1 вернул $code, ожидали $2"
    echo "ok   $2 $1"
}

echo "==> Сборка образа $IMAGE"
docker build -q -t "$IMAGE" . >/dev/null

echo "==> PostgreSQL"
docker network create "$NET" >/dev/null
docker run -d --name "$DB" --network "$NET" \
    -e POSTGRES_DB=studio -e POSTGRES_USER=studio -e POSTGRES_PASSWORD=studio \
    postgres:17-alpine >/dev/null
for _ in $(seq 1 30); do
    docker exec "$DB" pg_isready -U studio -d studio >/dev/null 2>&1 && break
    sleep 1
done
docker exec "$DB" pg_isready -U studio -d studio >/dev/null 2>&1 || fail "PostgreSQL не поднялся"

echo "==> Приложение (gunicorn, DEBUG=0, миграции при старте)"
docker run -d --name "$WEB" --network "$NET" -p "127.0.0.1:$PORT:8000" \
    -e DJANGO_SECRET_KEY=smoke-test-secret-key-0123456789abcdef \
    -e RUN_MIGRATIONS=1 \
    -e POSTGRES_DB=studio -e POSTGRES_USER=studio -e POSTGRES_PASSWORD=studio -e POSTGRES_HOST="$DB" \
    "$IMAGE" >/dev/null

for _ in $(seq 1 60); do
    curl -sf "http://127.0.0.1:$PORT/healthz/" >/dev/null 2>&1 && break
    sleep 1
done
curl -sf "http://127.0.0.1:$PORT/healthz/" >/dev/null 2>&1 || fail "/healthz/ не отвечает за 60 секунд"
echo "ok   healthz"

docker exec "$WEB" python manage.py seed_demo >/dev/null || fail "seed_demo упал"

echo "==> Страницы"
for path in / /services/ /services/game-assets/ /portfolio/ /portfolio/robot-courier/ \
    /reviews/ /contacts/ /order/ /accounts/login/ /accounts/register/ \
    /accounts/password-reset/ /admin/login/ /robots.txt /sitemap.xml; do
    check_status "$path" 200
done
check_status /cabinet/ 302
check_status /no-such-page/ 404

echo "==> Статика"
css=$(curl -s "http://127.0.0.1:$PORT/" | grep -o '/static/css/style\.[a-f0-9]*\.css' | head -1)
[ -n "$css" ] || fail "в HTML нет хешированной ссылки на CSS (collectstatic/манифест)"
check_status "$css" 200

echo "==> Контейнер"
user=$(docker exec "$WEB" id -un)
[ "$user" = "app" ] || fail "приложение запущено от '$user', ожидали непривилегированного 'app'"
echo "ok   запущено от пользователя $user"

out=$(docker run --rm --network "$NET" -e DJANGO_SECRET_KEY=smoke-test-secret-key-0123456789abcdef \
    "$IMAGE" python manage.py runbot 2>&1 || true)
echo "$out" | grep -q "TELEGRAM_BOT_TOKEN" || fail "бот без токена должен завершаться с понятным сообщением, получили: $out"
echo "ok   бот без токена завершается с сообщением"

echo "SMOKE TEST PASSED"
