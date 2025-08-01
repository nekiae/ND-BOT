# === GENERAL IDEA =========================================================
Build a Telegram bot “HD | Lookism”. Language: Russian (bot replies in RU, code comments EN/RU mixed).
Purpose: paid looksmax coach – user uploads two photos (front & profile), bot returns
a detailed metric report, rating (Sub‑5 ➝ PSL‑God) and improvement plan, then
allows Q&A with an LLM. Monetization: monthly YooKassa subscription (999 RUB).

# === FUNCTIONAL SPEC ======================================================
1. Start flow
   /start → inline “Оплатить 999 ₽” button (YooKassa payment link)
   After successful payment -> set `users.is_active_until = now+30d`

2. Quotas
   Each paid month: 3 analyses + 200 chat messages.
   Track `analyses_left`, `messages_left` in DB.

3. Photo flow
   a) Bot: “Шаг 1/2 Анфас” → wait for photo.
      Validate front (yaw <15°) by OpenCV fallback (mediapipe optional).
   b) Bot: “Шаг 2/2 Профиль” → wait photo.
      Validate profile (yaw ≥55°).
   c) After both OK create Session(status=pending) → push Job to queue (Redis).

4. Analysis worker (async)
   • Download both photos.
   • Call **Face++** (return_landmark=1, beauty, symmetry).
   • Call **AILab** `face_analyze` with `return_landmark=106`.
     Retry 3× on errno, backoff 800 ms.
   • Parse landmark106 → numpy (shape 106×2).
   • Extract metrics:
       canthal, gonial, midface ratio, thirds, chin proj, nasofrontal, beauty, symmetry.
   • Compute:
       base_rating 0‑10 (beauty/10)
       composite_rating (weight: beauty 40%, canthal 25, gonial 20, symmetry 10, midface 5)
       label via table:
         0‑3 Sub‑5, 3‑4.5 LTN, 4.5‑6 HTN, 6‑7.5 Chad‑Lite,
         7.5‑8.5 PSL‑God‑Candidate, 8.5+ PSL‑God.
   • Build JSON = {metrics, ratings, label}
   • Feed JSON + KNOWLEDGE_BASE to DeepSeek‑Chat (temperature 0.4)
     With system prompt template given below.
   • Save report text & thumbs to DB, set Session.status='done'.

5. Bot sends final message (markdown):
   🏷️ РЕЙТИНГ И КАТЕГОРИЯ … (exact sample below)
   then waits for user questions (counts tokens).

6. Commands
   /stats – show days left + balances.
   /renew – send payment button again.
   /help – brief help.

# === TECHNOLOGY STACK =====================================================
• Python 3.11, Poetry.
• aiogram 3 (bot).
• httpx 0.27 + asyncio.
• Redis (queue) via aioredis.
• PostgreSQL (SQLModel ORM)  ➝ Railway free Postgres.
• OpenCV‑python‑headless for yaw.
• Optional: mediapipe 0.10 (if wheels available).
• DeepSeek Chat completion (model `deepseek-chat`).
• Face++ REST.
• AILab REST old route `/rest/160/face_analyze`.
• YooKassa‑python SDK for payment webhook.

# === DB SCHEMA (sqlmodel) ==================================================
User(id TG, is_active_until dt, analyses_left int, messages_left int)
Session(id, user_id FK, front_file_id, profile_file_id,
        status enum(pending|processing|done|failed),
        result_json JSONB, created_at, finished_at)
Task(id, session_id FK, status enum(pending|processing|done|failed))

# === SYSTEM PROMPT FOR DeepSeek ===========================================
Ты — русскоязычный looksmax-коуч. Твоя задача — проанализировать JSON с метриками лица и сгенерировать подробный, структурированный отчет на русском языке. Используй легкий сленг (например, HTN, Chad-Lite, Sub-5), но избегай оскорблений.

Отчет должен строго следовать этому Markdown шаблону. Заполняй плейсхолдеры `{...}` данными из предоставленного JSON.

**ВХОДНЫЕ ДАННЫЕ:**
Тебе будет предоставлен JSON объект, содержащий следующие поля: `beauty_score_norm`, `composite_rating`, `tier_label`, `gonial_angle`, `bizygo`, `bigonial`, `fwh_ratio`, `canthal_tilt`, `interpupil`, `eye_whr`, `nasofrontal`, `nasolabial`, `alar_width`, `mouth_width`, `lip_height`, `philtrum`, `chin_proj`, `mand_plane`, `skin_score`, `acne_idx`, `stain_idx`, `weak_metrics` (список слабых метрик), `next_check_date`.

**ШАБЛОН ОТЧЕТА:**
```markdown
🏷️ **РЕЙТИНГ И КАТЕГОРИЯ**
- **Базовый рейтинг:** {beauty_score_norm*10:.1f}/10
- **Компонентный:** {composite_rating:.1f}/10
- **Категория:** {tier_label}

────────────────────────────────────────────────
📊 **ДЕТАЛЬНЫЙ АНАЛИЗ МЕТРИК**
────────────────────────────────────────────────

**🔸 Костная база**
- **Гониальный угол:** {gonial_angle:.1f}°
- **Bizygomatic / Bigonial:** {bizygo} мм / {bigonial} мм
- **FWHR:** {fwh_ratio:.2f}

**🔸 Глаза**
- **Кантальный наклон:** {canthal_tilt:+.1f}°
- **Межзрачковое расстояние:** {interpupil} мм
- **Соотношение W/H глаз:** {eye_whr:.2f}

**🔸 Нос**
- **Назофронтальный угол:** {nasofrontal:.1f}°
- **Назолабиальный угол:** {nasolabial:.1f}°
- **Ширина крыльев носа:** {alar_width} мм

**🔸 Рот / губы**
- **Ширина рта:** {mouth_width} мм
- **Общая высота губ:** {lip_height} мм
- **Длина фильтрума:** {philtrum} мм

**🔸 Профиль**
- **Проекция подбородка:** {chin_proj:+.1f} мм
- **Плоскость нижней челюсти:** {mand_plane:.1f}°

**🔸 Кожа**
- **SkinScore:** {skin_score}/100
- **Индекс акне:** {acne_idx}
- **Индекс пятен:** {stain_idx}

────────────────────────────────────────────────
💬 **ЧЕСТНАЯ ОЦЕНКА**

{summary_paragraph}

────────────────────────────────────────────────
📌 **ПЛАН УЛУЧШЕНИЙ**
────────────────────────────────────────────────

**🎯 0–30 дней (Немедленные действия)**
- Действие A — частота/дозировка (цель: улучшить {target_metric_A})
- Действие B — частота/дозировка (цель: улучшить {target_metric_B})

**🎯 1–6 месяцев (Среднесрочные цели)**
- Действие C — периодичность (цель: скорректировать {target_metric_C})
- Действие D — периодичность (цель: скорректировать {target_metric_D})

**🎯 6+ месяцев / Инвазивные методы**
- Метод E (при показаниях) — ожидаемый прирост метрики {target_metric_E}
- Метод F (при показаниях) — ожидаемый прирост метрики {target_metric_F}

────────────────────────────────────────────────
🔍 **ПРИМЕЧАНИЯ**
- Конкретные названия процедур/продуктов подбираются индивидуально.
- Инвазивные методы требуют очной консультации специалиста.

────────────────────────────────────────────────

📅 **СЛЕДУЮЩИЙ АНАЛИЗ:** {next_check_date}
```

**ИНСТРУКЦИИ ПО ГЕНЕРАЦИИ:**

1.  **Честная оценка (`{summary_paragraph}`):** Напиши краткий (2-4 предложения) и объективный абзац. Сфокусируйся на 2-3 самых сильных и 2-3 самых слабых метриках из JSON. Объясни простым языком, что они означают для общей эстетики.

2.  **План улучшений:**
    - Для каждого временного блока (`0-30 дней`, `1-6 месяцев`, `6+ месяцев`) предложи 1-2 конкретных действия или метода, нацеленных на улучшение слабых метрик (`weak_metrics`).
    - `{target_metric_X}` должен быть заменен на название конкретной метрики (например, `Гониальный угол`, `SkinScore`).
    - Предлагай реалистичные и общепринятые советы (например, уход за кожей, упражнения для осанки, базовые рекомендации по питанию). Для инвазивных методов всегда указывай, что нужна консультация специалиста.
    - Если в `weak_metrics` есть проблемы с кожей, предложи соответствующие действия в первую очередь.

3.  **Завершение:** После отчета добавь строку: `💬 Теперь можешь задавать вопросы!`

Не добавляй никакой информации или форматирования, кроме того, что указано в шаблоне.

# === PAYMENT CALLBACK ======================================================
YooKassa webhook → POST /payment/webhook
Verify signature → if “succeeded” and metadata.tg_id present:
 update user: is_active_until=now+30d, analyses_left=3, messages_left=200

# === TASK QUEUE IMPLEMENTATION ============================================
`enqueue(session_id)` → LPUSH redis:list
Worker: BRPOP list 1s → process.

# === DEPLOY ===============================================================
Railway (Dockerfile):
FROM python:3.11-slim  
RUN apt-get update && apt-get install -y libgl1  
COPY pyproject.toml poetry.lock /app/  
WORKDIR /app  
RUN pip install poetry && poetry install --no-dev  
COPY . /app  
CMD ["python","bot.py"]

Set env: BOT_TOKEN, AILAB_KEY, AILAB_SECRET, FACEPP_KEY, FACEPP_SECRET,
DEESEEK_KEY, YOOKASSA_ID, YOOKASSA_SECRET.

# === UNIT TESTS ============================================================
tests/test_yaw.py – feed sample front/profile, assert classify_pose.
tests/test_metrics.py – feed dummy landmark, assert angle calc.

# === DONE =================================================================
Generate:
• bot.py – main aiogram router  
• validators.py – yaw / quality  
• analyzers/ client.py, metrics.py  
• worker.py – redis consumer  
• payments.py – YooKassa webhook  
• Dockerfile, docker‑compose.yml  
• README.md with quick‑start

Make code idempotent, black‑formatted, type‑hinted.
Return PR diff ready to commit. 

# === PROJECT STRUCTURE ANALYSIS (Generated by Cascade) ===

This document provides a detailed breakdown of the project's file structure, component responsibilities, and recommendations for cleanup.

---

## 📂 1. Конфигурация и Среда (Configuration and Environment)

These files set up the environment and variables for the bot.

- **`.env`**: **(SECRET)** Stores all API keys, tokens, and passwords (`BOT_TOKEN`, `DATABASE_URL`, etc.). **Do not commit to Git.**
- **`.env.example`**: **(Template)** An example file showing which environment variables are needed.
- **`.gitignore`**: **(Git)** Specifies which files and folders to ignore (e.g., `.env`, `__pycache__`, `venv`).
- **`requirements.txt`**: **(Dependencies - pip)** A list of Python libraries required for the project. Installed via `pip install -r requirements.txt`.
- **`pyproject.toml`** & **`poetry.lock`**: **(Dependencies - Poetry)** An alternative way to manage dependencies. Having both this and `requirements.txt` is redundant. It's recommended to choose one.
- **`Dockerfile`** & **`docker-compose.yml`**: **(Deployment)** Files for packaging the application into a Docker container, making it ready for server deployment.

---

## 🚀 2. Ядро Приложения (Core Logic)

These are the main files that drive the bot's functionality.

- **`main.py` (Main File)**: **The brain of the bot.** This is the entry point that ties everything together.
  - **Initialization**: Loads config, creates `Bot` and `Dispatcher` objects.
  - **Handlers**: Contains functions that react to user commands (`/start`, button clicks).
  - **FSM (Finite State Machine)**: Manages multi-step dialogues like photo uploads.
  - **Admin Panel**: Implements features for administrators (stats, broadcasts, user management).
  - **Webhook Launch**: Sets up and runs a web server (`aiohttp`) to receive updates from Telegram, which is the standard for production bots.

- **`database.py`**: **Database Manager.** Handles all interactions with the PostgreSQL database.
  - **Connection**: Creates an async connection using `SQLAlchemy`.
  - **Helper Functions**: Provides functions for all database operations (CRUD): `add_user`, `get_user`, `check_subscription`, `give_subscription_to_user`, etc.

- **`models.py`**: **Data Schemas.** Defines the structure of database tables (`User`, `Session`, `Task`) using `SQLModel`.

- **`worker.py`**: **Background Task Processor.** The "workhorse" that performs heavy tasks (photo analysis) without blocking the main bot. It listens to a Redis queue and processes jobs as they arrive.

- **`task_queue.py`**: **Task Queue Manager.** Manages the connection to **Redis** and provides simple functions to add tasks to the queue.

- **`payments.py`**: **Payment Processor.** Integrates with **YooKassa**.
  - **Payment Creation**: Generates payment links.
  - **Webhook Handling**: Processes notifications from YooKassa about payment status.

- **`validators.py`**: **Upload Validator.** Checks if user-uploaded photos meet the requirements (e.g., correct face angle) before sending them for analysis.

---

## 🧠 3. Модуль Анализа (`analyzers/`)

This directory contains all the logic related to facial analysis.

- **`analyzers/client.py`**: **API Clients.** Handles communication with external services.
  - `FacePlusPlusClient`: Sends photos to the Face++ API.
  - `DeepSeekClient`: Sends metrics to the DeepSeek language model to generate reports and Q&A answers.

- **`analyzers/metrics.py`**: **Metrics Calculation.** The most science-intensive part. Takes raw facial landmark data from the API and computes specific "looksmax" metrics (gonial angle, midface ratio, etc.).

- **`analyzers/report_generator.py`**: **Report Generator.** Assembles the calculated metrics into a structured, user-friendly text report using a predefined template.

---

## 🗑️ 4. Устаревшие, Тестовые и Ненужные Файлы (Obsolete & Test Files)

These files are likely no longer in use or are artifacts from development.

- **`core/`**: **(Obsolete)** Likely an **old version** of the analysis module, replaced by the `analyzers/` directory. **Can be deleted.**
- **`simple_bot.py`**: **(Test)** A simplified version of the bot for quick testing, works without a database or webhooks. Not for production.
- **`test_yookassa_webhook.py`**: A script for locally testing the YooKassa webhook.
- **`3DDFA_V2/`**: **(Obsolete Library)** Likely a third-party library for 3D facial analysis that was considered but not integrated. **Can be deleted.**
- **`venv/`, `.venv/`, `.venv2/`**: **(Environments)** It's best to keep only one virtual environment and remove the others to avoid confusion.
- **`__pycache__/`**: **(Cache)** Auto-generated by Python. Safe to delete.
- **`bot.db`, `database.db`, `lookism.db`**: **(Old DBs)** SQLite database files from early development. The project now uses PostgreSQL. **Can be archived and deleted.**
- **`bot.log`, `run.log`**: Log files. Can be periodically cleared or archived.
- **`создаём/`, `←/`, `#/`**: **(Junk)** Temporary or accidentally created folders. **Should be deleted.**

---

## 📚 5. Документация (Documentation)

- **`context.md`**: **(This File)** The technical specification, describing the initial idea, features, and now the project structure.
- **`README.md`**: The main documentation, usually with setup and launch instructions.
- **`TROUBLESHOOTING.md`**: A document describing potential issues and their solutions.

