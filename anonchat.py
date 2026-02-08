#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Anon Chat Bot (pyTelegramBotAPI) — обновлённый:
- если пользователь пришёл по реферальной ссылке, получает подсказку:
  "Вы перешли по рефералу, напишите сообщение и оно будет как от анонима!"
- кнопка "Моя ссылка" заменена на "👤 Профиль"
- сохранены все предыдущие функции:
  /start, /stop, анонимные сообщения, Ответить (inline), Премиум, админ-панель выдачи премиума
"""

import sqlite3
import time
import re
import logging
from threading import Lock
from datetime import datetime
import telebot
from telebot import types

# ===================== НАСТРОЙКИ =====================
BOT_TOKEN = "BOT_TOKEN"
ADMIN_ID = 8128381503
DB_PATH = "anoo_chat.db"
# ======================================================

# Логирование
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="Markdown")
lock = Lock()

# ===================== БД =====================
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    premium_until INTEGER DEFAULT 0,
    last_reply_to INTEGER,
    state TEXT
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS refs (
    user_id INTEGER PRIMARY KEY,
    target_id INTEGER
)
""")
conn.commit()

# ===================== УТИЛИТЫ DB =====================
def user_exists(user_id):
    with lock:
        cur.execute("SELECT 1 FROM users WHERE user_id=?", (user_id,))
        return cur.fetchone() is not None

def save_user_on_start(user):
    with lock:
        cur.execute("""
        INSERT OR IGNORE INTO users (user_id, username, premium_until, last_reply_to, state)
        VALUES (?, ?, 0, NULL, NULL)
        """, (user.id, user.username))
        cur.execute("UPDATE users SET username=? WHERE user_id=?", (user.username, user.id))
        conn.commit()

def update_username(user_id, username):
    with lock:
        cur.execute("UPDATE users SET username=? WHERE user_id=?", (username, user_id))
        conn.commit()

def set_ref(user_id, target_id):
    with lock:
        cur.execute("INSERT OR REPLACE INTO refs (user_id, target_id) VALUES (?, ?)", (user_id, target_id))
        conn.commit()

def get_ref(user_id):
    with lock:
        cur.execute("SELECT target_id FROM refs WHERE user_id=?", (user_id,))
        r = cur.fetchone()
        return r[0] if r else None

def get_user(user_id):
    with lock:
        cur.execute("SELECT user_id, username, premium_until, last_reply_to, state FROM users WHERE user_id=?", (user_id,))
        return cur.fetchone()

def set_last_reply_to(user_id, target_id):
    with lock:
        cur.execute("UPDATE users SET last_reply_to=? WHERE user_id=?", (target_id, user_id))
        conn.commit()

def clear_last_reply_to(user_id):
    with lock:
        cur.execute("UPDATE users SET last_reply_to=NULL WHERE user_id=?", (user_id,))
        conn.commit()

def get_last_reply_to(user_id):
    with lock:
        cur.execute("SELECT last_reply_to FROM users WHERE user_id=?", (user_id,))
        r = cur.fetchone()
        return r[0] if r and r[0] else None

def set_state(user_id, state):
    with lock:
        cur.execute("UPDATE users SET state=? WHERE user_id=?", (state, user_id))
        conn.commit()

def get_state(user_id):
    with lock:
        cur.execute("SELECT state FROM users WHERE user_id=?", (user_id,))
        r = cur.fetchone()
        return r[0] if r else None

def set_premium(user_id, until_ts):
    with lock:
        cur.execute("UPDATE users SET premium_until=? WHERE user_id=?", (int(until_ts), user_id))
        conn.commit()

def get_premium_until(user_id):
    with lock:
        cur.execute("SELECT premium_until FROM users WHERE user_id=?", (user_id,))
        r = cur.fetchone()
        return r[0] if r else 0

def is_premium(user_id):
    until = get_premium_until(user_id)
    try:
        return int(until) > int(time.time())
    except:
        return False

def find_user_by_username(username):
    if not username:
        return None
    username = username.lstrip("@").lower()
    with lock:
        cur.execute("SELECT user_id FROM users WHERE lower(username)=?", (username,))
        r = cur.fetchone()
        return r[0] if r else None

# ===================== Форматирование =====================
def escape_md(text: str) -> str:
    if not text:
        return ""
    return re.sub(r'([*_`\[])', r'\\\1', text)

def human_premium_label(until_ts):
    if not until_ts:
        return "Обычный"
    try:
        until = int(until_ts)
    except:
        return "Обычный"
    if until > 10**11:
        return "⭐ Премиум⭐ (навсегда)"
    if until <= int(time.time()):
        return "Обычный"
    dt = datetime.fromtimestamp(until)
    return f"⭐ Премиум⭐ до {dt.strftime('%Y-%m-%d %H:%M')}"

def make_main_menu(user_id):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("👤 Профиль", "⭐ Премиум")
    kb.add("ℹ️ Как это работает")
    if user_id == ADMIN_ID:
        kb.add("👑 Выдать премиум")
    return kb

# ===================== /start =====================
@bot.message_handler(commands=['start'])
def handle_start(message):
    user = message.from_user
    new = not user_exists(user.id)
    save_user_on_start(user)
    update_username(user.id, user.username)

    # уведомление админу при первом заходе
    if new:
        try:
            admin_text = f"🚀 *Новый пользователь зашел в бота!*\nID: `{user.id}`"
            if user.username:
                admin_text += f"\nUsername: @{user.username}"
            bot.send_message(ADMIN_ID, admin_text)
        except Exception as e:
            logger.exception("Не удалось отправить уведомление админу: %s", e)

    # обработка реферального токена ?start=ref<ID>
    ref_set = False
    args = message.text.split()
    if len(args) > 1:
        token = args[1]
        if token.startswith("ref"):
            try:
                target = int(token.replace("ref", ""))
                if target != user.id:
                    set_ref(user.id, target)
                    ref_set = True
            except:
                pass
    else:
        # иногда телеграм может прислать payload сразу после /start без пробела
        if "ref" in message.text:
            try:
                idx = message.text.find("ref")
                token = message.text[idx:]
                target = int(token.replace("ref", ""))
                if target != user.id:
                    set_ref(user.id, target)
                    ref_set = True
            except:
                pass

    # Отправляем привет и меню
    try:
        me = bot.get_me()
        bot_username = me.username or "bot"
    except:
        bot_username = "bot"
    link = f"https://t.me/{bot_username}?start=ref{user.id}"
    text = (
        "👋 *Добро пожаловать в аноним чат!*\n\n"
        "📩 Здесь тебе могут писать *анонимно*.\n"
        "🔗 Размести свою реферальную ссылку в профиле — и люди смогут писать тебе анонимно.\n\n"
        f"*Твоя ссылка:*\n`{link}`\n\n"
        "Используй меню ниже."
    )
    bot.send_message(user.id, text, reply_markup=make_main_menu(user.id))

    # Если пришли по реферальной ссылке — подсказываем, что писать
    if ref_set:
        try:
            bot.send_message(user.id,
                             "✅ Вы перешли по рефералу — напишите сообщение ниже, и оно будет отправлено как от анонима!",
                             reply_markup=make_main_menu(user.id))
        except Exception:
            pass

# ===================== /stop =====================
@bot.message_handler(commands=['stop'])
def handle_stop(message):
    user_id = message.from_user.id
    clear_last_reply_to(user_id)
    bot.send_message(user_id,
                     "🛑 *Диалог остановлен.*\n"
                     "Ты больше не общаешься с этим пользователем.\n"
                     "Чтобы снова ответить — нажми кнопку «Ответить» под новым сообщением.",
                     reply_markup=make_main_menu(user_id))

# ===================== Admin: старт выдачи премиума (кнопка) =====================
@bot.message_handler(func=lambda m: m.text == "👑 Выдать премиум" and m.from_user.id == ADMIN_ID)
def admin_start_give_premium(message):
    set_state(ADMIN_ID, "wait_username_for_premium")
    bot.send_message(ADMIN_ID, "✏️ Напишите юзернейм пользователя (пример: @username). Или пришлите ID пользователя.")

# ===================== Admin: обработка ввода username (FSM) =====================
@bot.message_handler(func=lambda m: get_state(m.from_user.id) == "wait_username_for_premium" and m.from_user.id == ADMIN_ID)
def admin_receive_username(message):
    text = message.text.strip()
    target_id = None
    if text.startswith("@"):
        target_id = find_user_by_username(text)
    else:
        if text.isdigit():
            tid = int(text)
            if user_exists(tid):
                target_id = tid
    if not target_id:
        bot.send_message(ADMIN_ID, "❌ Пользователь не найден в базе. Убедитесь, что он нажал /start.")
        return

    set_state(ADMIN_ID, f"wait_time_for_{target_id}")
    bot.send_message(ADMIN_ID, "⏳ Напишите срок: 3 дня / 7 дней / 1 месяц / навсегда\nПример: `3 дня` или `навсегда`", parse_mode="Markdown")

# ===================== Admin: обработка ввода времени (FSM) =====================
@bot.message_handler(func=lambda m: get_state(m.from_user.id) and m.from_user.id == ADMIN_ID)
def admin_receive_time(message):
    state = get_state(ADMIN_ID)
    if not state or not state.startswith("wait_time_for_"):
        return
    try:
        target_id = int(state.split("_for_")[1])
    except:
        bot.send_message(ADMIN_ID, "❌ Ошибка внутреннего состояния.")
        set_state(ADMIN_ID, None)
        return

    text = message.text.lower()
    if "3" in text and "д" in text:
        seconds = 3 * 86400
        label = "3 дня"
    elif ("7" in text and "д" in text) or ("нед" in text):
        seconds = 7 * 86400
        label = "7 дней"
    elif "месяц" in text or ("1" in text and "м" in text):
        seconds = 30 * 86400
        label = "1 месяц"
    elif "навс" in text or "навсегда" in text:
        seconds = -1
        label = "навсегда"
    else:
        bot.send_message(ADMIN_ID, "❌ Неверный формат срока. Введите например: `3 дня`, `7 дней`, `1 месяц`, `навсегда`", parse_mode="Markdown")
        return

    if seconds == -1:
        until = 10**12
    else:
        until = int(time.time()) + seconds
    set_premium(target_id, until)
    set_state(ADMIN_ID, None)

    bot.send_message(ADMIN_ID, f"✅ Премиум выдан пользователю `{target_id}` на *{label}*", parse_mode="Markdown")
    try:
        bot.send_message(target_id,
                         f"⭐ *Вы получили премиум на {label}!*\nТеперь вы можете видеть, от кого приходят сообщения.",
                         parse_mode="Markdown")
    except Exception:
        logger.warning("Не удалось уведомить пользователя %s о премиуме", target_id)

# ===================== Меню — кнопки =====================
@bot.message_handler(func=lambda m: m.text == "👤 Профиль")
def profile_handler(message):
    user = message.from_user
    if user.username is not None:
        update_username(user.id, user.username)
    until = get_premium_until(user.id)
    status_label = human_premium_label(until)
    try:
        me = bot.get_me()
        bot_username = me.username or "bot"
    except:
        bot_username = "bot"
    link = f"https://t.me/{bot_username}?start=ref{user.id}"
    text = (
        f"*Профиль*\n\n"
        f"Ваш статус: {status_label}\n\n"
        f"Ваша реф ссылка:\n`{link}`\n\n"
        "Вы можете разместить эту ссылку в профиле, чтобы получать анонимные сообщения."
    )
    bot.send_message(user.id, text, parse_mode="Markdown", reply_markup=make_main_menu(user.id))

@bot.message_handler(func=lambda m: m.text == "⭐ Премиум")
def premium_info_handler(message):
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("Показать пример", callback_data="show_example"))
    kb.add(types.InlineKeyboardButton("Купить у @cexonov", url="https://t.me/cexonov"))
    text = (
        "⭐ *Премиум*\n\n"
        "Вы будете видеть, *кто* написал сообщение.\n"
        "Отправитель не узнает, что у вас премиум.\n\n"
        "3 дня — 25 ⭐\n"
        "7 дней — 50 ⭐\n"
        "1 месяц — 150 ⭐\n"
        "Навсегда — ~~250~~ *125 ⭐*\n\n"
        "Связь и оплата — через @cexonov"
    )
    bot.send_message(message.chat.id, text, reply_markup=kb)

@bot.message_handler(func=lambda m: m.text == "ℹ️ Как это работает")
def how_handler(message):
    text = (
        "ℹ️ *Как это работает*\n\n"
        "1️⃣ Ты размещаешь свою реферальную ссылку\n"
        "2️⃣ Человек открывает ссылку и пишет тебе анонимно\n"
        "3️⃣ Под сообщением у тебя кнопка «Ответить» — нажал и пишешь\n"
        "4️⃣ /stop — прекратить текущий диалог\n\n"
        "⭐ С премиумом видно автора сообщения"
    )
    bot.send_message(message.chat.id, text)

# ===================== Inline callback (Показать пример, Ответить) =====================
@bot.callback_query_handler(func=lambda c: True)
def callback_handler(call):
    data = call.data or ""
    user_id = call.from_user.id

    if data == "show_example":
        bot.answer_callback_query(call.id, "Пример показан")
        bot.send_message(user_id, "*Пример:*\n`Сообщение от @user: Ты мне нравишься!`", parse_mode="Markdown")
        return

    if data.startswith("reply_"):
        try:
            sender_id = int(data.split("_", 1)[1])
        except:
            bot.answer_callback_query(call.id, "Ошибка.")
            return
        set_last_reply_to(user_id, sender_id)
        bot.answer_callback_query(call.id, "Напишите сообщение — оно будет отправлено пользователю анонимно.")
        bot.send_message(user_id, "✏️ Напишите свой ответ. Чтобы прекратить диалог — /stop", reply_markup=make_main_menu(user_id))
        return

    bot.answer_callback_query(call.id, "Неизвестная кнопка.")

# ===================== Основная логика: текстовые сообщения =====================
@bot.message_handler(func=lambda m: True, content_types=['text'])
def general_text_handler(message):
    user = message.from_user
    text = message.text or ""
    user_id = user.id

    # Обновим username (без трогания last_reply_to)
    if user.username is not None:
        update_username(user_id, user.username)

    # Если админ в FSM — обработаем в admin хендлерах (они выше)
    state = get_state(user_id)
    if user_id == ADMIN_ID and state:
        return

    # Сначала проверяем last_reply_to
    last = get_last_reply_to(user_id)
    if last:
        target = last
    else:
        target = get_ref(user_id)

    if not target:
        bot.send_message(user_id, "❗ Чтобы написать человеку, открой его реферальную ссылку (нажми на её ссылку).")
        return

    sender_display = f"@{user.username}" if user.username else (user.first_name or f"user{user.id}")
    if is_premium(target):
        out_text = f"*Сообщение от {escape_md(sender_display)}:*\n{escape_md(text)}"
    else:
        out_text = f"*Анонимное сообщение:*\n{escape_md(text)}"

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("Ответить", callback_data=f"reply_{user_id}"))

    try:
        bot.send_message(target, out_text, reply_markup=kb, parse_mode="Markdown")
        bot.send_message(user_id, "✅ Ваше сообщение отправлено.", reply_markup=make_main_menu(user_id))
    except Exception as e:
        logger.exception("Ошибка при отправке сообщения: %s", e)
        bot.send_message(user_id, "❌ Не удалось доставить сообщение — получатель недоступен.")

# ===================== /premium команда (быстрая выдача админом) =====================
@bot.message_handler(commands=['premium'])
def premium_command(message):
    if message.from_user.id != ADMIN_ID:
        bot.send_message(message.from_user.id, "Команда доступна только администратору.")
        return

    parts = message.text.split()
    if len(parts) < 3:
        bot.send_message(ADMIN_ID, "Использование: /premium <user_id> <3д|7д|1м|навсегда>")
        return

    try:
        target_id = int(parts[1])
    except:
        bot.send_message(ADMIN_ID, "Первый аргумент должен быть numeric user_id.")
        return

    period = parts[2].lower()
    if "3" in period:
        seconds = 3 * 86400
        label = "3 дня"
    elif "7" in period or "нед" in period:
        seconds = 7 * 86400
        label = "7 дней"
    elif "1" in period or "м" in period:
        seconds = 30 * 86400
        label = "1 месяц"
    elif "нав" in period:
        seconds = -1
        label = "навсегда"
    else:
        bot.send_message(ADMIN_ID, "Неверный период.")
        return

    until = 10**12 if seconds == -1 else int(time.time()) + seconds
    set_premium(target_id, until)
    bot.send_message(ADMIN_ID, f"✅ Премиум выдан {target_id} на {label}")
    try:
        bot.send_message(target_id, f"⭐ *Вы получили премиум на {label}!*\nТеперь вы можете видеть, от кого приходят сообщения.", parse_mode="Markdown")
    except Exception:
        logger.warning("Не удалось уведомить пользователя %s о премиуме", target_id)

# ===================== Запуск =====================
if __name__ == "__main__":
    logger.info("Bot is starting...")
    try:
        bot.infinity_polling(timeout=60, long_polling_timeout=60)
    except KeyboardInterrupt:
        logger.info("Stopping bot (KeyboardInterrupt).")
    except Exception as e:
        logger.exception("Bot stopped with exception: %s", e)