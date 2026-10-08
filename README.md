# Polygon3D — сайт студии 3D-моделирования + Telegram-бот

Демонстрационный проект для портфолио: Django-сайт, Telegram-бот на aiogram, Docker и CI/CD с автодеплоем.

## Что умеет

**Сайт**
- Главная, каталог услуг с ценами, портфолио с фильтром по категориям
- Интерактивный 3D-просмотр работ (`.glb` / `.gltf`) через `<model-viewer>`
- Форма заказа с загрузкой референсов, защита honeypot-полем и проверкой типа/размера файла
- Регистрация и личный кабинет: заказы, статусы, переписка с менеджером, привязка Telegram
- Админка: заказы со статусами и ответами клиенту, услуги, портфолио, отзывы

**Telegram-бот**
- Услуги, портфолио, контакты
- Оформление заказа (услуга → описание → телефон → референсы)
- «Мои заказы» и чат с менеджером
- Менеджерам: уведомление о новых заказах и сообщениях, кнопки «Ответить» и смены статуса, команда `/orders`
- Клиенту: уведомление о смене статуса и ответах менеджера

**Связка сайта и бота.** Сайт кладёт сообщения в таблицу `Notification` (паттерн outbox), бот забирает их каждые 2 секунды и отправляет. Если бот выключен, ничего не теряется. Сайт и бот не вызывают друг друга по HTTP, общая только БД.

## Быстрый старт (локально, нужен только Docker)

```bash
cp .env.example .env          # при желании впишите токен бота (см. ниже)
make up                       # сайт: http://localhost:8000
make superuser                # создать администратора → /admin/
make seed                     # демо-услуги, работы и отзывы
make logs                     # логи; make down — остановить
```

Команды `make test`, `make lint`, `make format` выполняются в контейнерах.

### Подключение бота
1. Создайте бота у [@BotFather](https://t.me/BotFather), получите токен.
2. В `.env` заполните `TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_USERNAME` (без `@`) и `TELEGRAM_ADMIN_IDS` (ваш числовой ID, узнать у [@userinfobot](https://t.me/userinfobot); несколько ID через запятую).
3. `docker compose up -d --build` — сервис `bot` стартует сам.

Без токена сайт работает полностью, просто уведомления не создаются.

## Структура

```
config/      настройки Django (всё через переменные окружения)
studio/      модели, представления, админка, уведомления, тесты
bot/         aiogram: handlers, keyboards, db-слой, outbox
templates/   шаблоны      static/   CSS и JS
deploy/      docker-compose.prod.yml и Caddyfile для сервера
.github/     CI/CD пайплайн
```

## CI/CD

Пайплайн `.github/workflows/ci-cd.yml`:

| Этап | Когда | Что делает |
|------|-------|-----------|
| `test` | каждый push и PR | ruff, проверка миграций, `check --deploy`, тесты на PostgreSQL |
| `build` | push в `main` | сборка образа, публикация в GHCR (`:sha` и `:latest`) |
| `deploy` | после `build` | копирует compose-файлы на сервер по SSH, делает `pull` и `up -d` |

### Подготовка сервера (один раз)

Нужны VPS с Docker + Compose plugin и домен, направленный A-записью на сервер. Порты 80 и 443 должны быть открыты.

```bash
mkdir -p /opt/polygon3d && cd /opt/polygon3d
nano .env        # см. шаблон ниже
```

`.env` на сервере (в репозиторий не попадает):

```env
DJANGO_SECRET_KEY=<длинная случайная строка>
DJANGO_DEBUG=0
DJANGO_HTTPS=1
DJANGO_ALLOWED_HOSTS=example.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://example.com
SITE_URL=https://example.com
DOMAIN=example.com
POSTGRES_DB=studio
POSTGRES_USER=studio
POSTGRES_PASSWORD=<надёжный пароль>
POSTGRES_HOST=db
TELEGRAM_BOT_TOKEN=...
TELEGRAM_BOT_USERNAME=...
TELEGRAM_ADMIN_IDS=...
```

Сгенерировать ключ: `python3 -c "import secrets; print(secrets.token_urlsafe(50))"`.

### Секреты GitHub (Settings → Secrets and variables → Actions)

| Секрет | Значение |
|--------|----------|
| `DEPLOY_HOST` | IP или домен сервера |
| `DEPLOY_USER` | пользователь SSH (в группе `docker`) |
| `DEPLOY_SSH_KEY` | приватный ключ (публичный — в `~/.ssh/authorized_keys` на сервере) |
| `DEPLOY_PATH` | `/opt/polygon3d` |
| `DEPLOY_PORT` | необязательно, по умолчанию 22 |

Также создайте Environment `production` (Settings → Environments), при желании с ручным подтверждением деплоя. Первый запуск создаст админа командой:
`docker compose -f docker-compose.prod.yml exec web python manage.py createsuperuser`.

### Что внутри production
- `caddy` — HTTPS (сертификат Let's Encrypt выпускается автоматически), раздаёт только `/media/public/*`
- `web` — gunicorn, миграции при старте, статика через WhiteNoise
- `bot` — тот же образ, команда `python manage.py runbot`
- `db` — PostgreSQL с томом `pgdata`

Файлы клиентов (`media/orders/`) наружу напрямую не отдаются: скачать их может только владелец заказа или сотрудник через Django.

## Что можно улучшить дальше
- Ограничение частоты заявок (django-ratelimit), капча
- Бэкапы PostgreSQL по расписанию (`pg_dump` в cron или отдельный контейнер)
- Webhook вместо long polling для бота, Sentry для ошибок
- Онлайн-оплата (ЮKassa / Stripe) и счета по заказам
