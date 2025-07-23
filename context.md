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
