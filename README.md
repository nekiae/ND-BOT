# HD | Lookism - Telegram Looksmax Coach Bot

Telegram бот для анализа внешности и looksmax коучинга с использованием ИИ.

## Функции

- 📸 Анализ фото анфас и профиль
- 📊 Детальные метрики лица (кантальный тилт, гониальный угол, симметрия)
- 🎯 PSL рейтинг (Sub-5 → PSL-God)
- 💪 Персональный план улучшений
- 💬 Q&A с ИИ-коучем
- 💳 Подписочная модель (999 ₽/месяц)

## Технологии

- **Backend**: Python 3.11, aiogram 3, FastAPI
- **Database**: PostgreSQL + SQLModel ORM
- **Queue**: Redis + aioredis
- **AI APIs**: Face++, AILab, DeepSeek Chat
- **Payments**: YooKassa
- **Computer Vision**: OpenCV
- **Deploy**: Docker, Railway

## Быстрый старт

### 1. Клонирование и установка

```bash
git clone <repository>
cd ND\ BOT
```

### 2. Настройка окружения

```bash
cp .env.example .env
# Заполните все API ключи в .env файле
```

### 3. Установка зависимостей

```bash
# Установка Poetry
curl -sSL https://install.python-poetry.org | python3 -

# Установка зависимостей
poetry install
```

### 4. Локальный запуск с Docker

```bash
# Запуск всех сервисов
docker-compose up -d

# Просмотр логов
docker-compose logs -f bot
```

### 5. Разработка без Docker

```bash
# Запуск PostgreSQL и Redis
docker-compose up -d postgres redis

# Активация виртуального окружения
poetry shell

# Запуск бота (polling режим)
python bot.py

# В отдельном терминале - запуск воркера
python worker.py
```

## Настройка API ключей

### Telegram Bot
1. Создайте бота через [@BotFather](https://t.me/botfather)
2. Получите токен и добавьте в `.env` как `BOT_TOKEN`

### Face++ API
1. Регистрация на [Face++](https://www.faceplusplus.com/)
2. Получите API Key и Secret
3. Добавьте в `.env` как `FACEPP_API_KEY` и `FACEPP_API_SECRET`

### AILab API
1. Регистрация на [AILab](https://ailabapi.com/)
2. Получите API Key и Secret
3. Добавьте в `.env` как `AILAB_API_KEY` и `AILAB_API_SECRET`

### DeepSeek API
1. Регистрация на [DeepSeek](https://platform.deepseek.com/)
2. Получите API Key
3. Добавьте в `.env` как `DEEPSEEK_API_KEY`

### YooKassa
1. Регистрация в [YooKassa](https://yookassa.ru/)
2. Получите Shop ID и Secret Key
3. Добавьте в `.env` как `YOOKASSA_SHOP_ID` и `YOOKASSA_SECRET_KEY`

## Деплой на Railway

### 1. Подготовка
```bash
# Установка Railway CLI
npm install -g @railway/cli

# Логин
railway login
```

### 2. Создание проекта
```bash
# Создание нового проекта
railway new

# Добавление PostgreSQL
railway add postgresql

# Добавление Redis
railway add redis
```

### 3. Настройка переменных окружения
```bash
# Установка переменных через CLI
railway variables set BOT_TOKEN=your_token
railway variables set FACEPP_API_KEY=your_key
# ... остальные переменные
```

### 4. Деплой
```bash
# Деплой приложения
railway up

# Деплой воркера (отдельный сервис)
railway service create worker
railway up --service worker
```

## Структура проекта

```
ND BOT/
├── bot.py                 # Основной файл бота
├── worker.py             # Фоновый обработчик
├── models.py             # Модели базы данных
├── database.py           # Конфигурация БД
├── validators.py         # Валидация фото
├── payments.py           # Интеграция с YooKassa
├── queue.py              # Redis очередь
├── analyzers/
│   ├── client.py         # API клиенты
│   └── metrics.py        # Извлечение метрик
├── tests/
│   ├── test_yaw.py       # Тесты валидации
│   └── test_metrics.py   # Тесты метрик
├── Dockerfile
├── docker-compose.yml
└── README.md
```

## Команды бота

- `/start` - Начать работу / оплата подписки
- `/stats` - Показать статистику (анализы, сообщения)
- `/renew` - Продлить подписку
- `/help` - Справка

## Workflow пользователя

1. `/start` → оплата 999 ₽ → активация подписки
2. Отправка фото анфас → валидация позы
3. Отправка фото профиль → валидация позы
4. Автоматический анализ (1-2 минуты)
5. Получение детального отчёта
6. Q&A с ИИ-коучем

## Мониторинг

```bash
# Логи бота
docker-compose logs -f bot

# Логи воркера
docker-compose logs -f worker

# Статус очереди Redis
redis-cli llen hd_lookism:tasks

# Статус базы данных
docker-compose exec postgres psql -U postgres -d hd_lookism -c "SELECT COUNT(*) FROM users;"
```

## Разработка

### Запуск тестов
```bash
poetry run pytest tests/
```

### Форматирование кода
```bash
poetry run black .
poetry run isort .
```

### Проверка типов
```bash
poetry run mypy .
```

## Поддержка

Для вопросов и поддержки обращайтесь к разработчику.

## Лицензия

Проект создан для коммерческого использования.
# ND-BOT
