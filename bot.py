import asyncio
import logging
import os
import random
import sys
from datetime import datetime

import aiosqlite
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder
from telethon import TelegramClient, events
from telethon.errors import SessionPasswordNeededError, FloodWaitError
from telethon.sessions import StringSession

# ========== НАСТРОЙКИ ==========
API_ID = 36118877              # Ваш API ID (число)
API_HASH = '80a0818180c09f35ee04af8e85c5552d'    # Ваш API Hash
PHONE = '+14323339298'       # Номер телефона аккаунта
BOT_TOKEN = '8120789440:AAG6OC71xLVURNAxjYXdgZrfNeTtUuc9IHU' # Токен бота от @BotFather
OWNER_ID = 5883796026        # Ваш Telegram ID (узнайте у @userinfobot)

# Session string – оставьте пустой при первом запуске, потом вставьте полученную строку
SESSION_STRING = ''

# Настройки мониторинга
REACT_ONLY_TO_FORWARDS = True  # True = только пересланные из каналов
# ===============================

# Логирование
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# База данных
DB_PATH = 'contest_bot.db'

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS chats (
                chat_id INTEGER PRIMARY KEY,
                title TEXT,
                added_date TEXT
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS keywords (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                keyword TEXT UNIQUE
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS replies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reply_text TEXT UNIQUE
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')
        await db.execute('INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)', ('monitoring_active', '0'))
        await db.commit()

async def get_chats():
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute('SELECT chat_id, title FROM chats')
        rows = await cursor.fetchall()
        return rows

async def add_chat(chat_id, title):
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute('INSERT INTO chats (chat_id, title, added_date) VALUES (?, ?, ?)',
                             (chat_id, title, datetime.now().isoformat()))
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False

async def remove_chat(chat_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('DELETE FROM chats WHERE chat_id = ?', (chat_id,))
        await db.commit()

async def get_keywords():
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute('SELECT keyword FROM keywords')
        rows = await cursor.fetchall()
        return [row[0] for row in rows]

async def add_keyword(keyword):
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute('INSERT INTO keywords (keyword) VALUES (?)', (keyword,))
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False

async def remove_keyword(keyword):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('DELETE FROM keywords WHERE keyword = ?', (keyword,))
        await db.commit()

async def get_replies():
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute('SELECT reply_text FROM replies')
        rows = await cursor.fetchall()
        return [row[0] for row in rows]

async def add_reply(reply):
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute('INSERT INTO replies (reply_text) VALUES (?)', (reply,))
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False

async def remove_reply(reply):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('DELETE FROM replies WHERE reply_text = ?', (reply,))
        await db.commit()

async def get_setting(key):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute('SELECT value FROM settings WHERE key = ?', (key,))
        row = await cursor.fetchone()
        return row[0] if row else None

async def set_setting(key, value):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('REPLACE INTO settings (key, value) VALUES (?, ?)', (key, value))
        await db.commit()

# Инициализация клиентов
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

if SESSION_STRING:
    user_client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
else:
    user_client = TelegramClient('user_session', API_ID, API_HASH)

def is_owner(user_id):
    return user_id == OWNER_ID

# ========== КЛАВИАТУРЫ ==========
def main_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Добавить чат", callback_data="add_chat")
    kb.button(text="➖ Удалить чат", callback_data="del_chat")
    kb.button(text="📋 Список чатов", callback_data="list_chats")
    kb.button(text="🔑 Ключевые фразы", callback_data="keywords_menu")
    kb.button(text="💬 Ответы", callback_data="replies_menu")
    kb.button(text="▶️ Запустить мониторинг", callback_data="start_monitor")
    kb.button(text="⏸️ Остановить мониторинг", callback_data="stop_monitor")
    kb.button(text="📊 Статус", callback_data="status")
    kb.adjust(2)
    return kb.as_markup()

def back_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="🔙 Назад", callback_data="back_to_main")
    return kb.as_markup()

# ========== СОСТОЯНИЯ FSM ==========
class AddChat(StatesGroup):
    waiting = State()

class AddKeyword(StatesGroup):
    waiting = State()

class AddReply(StatesGroup):
    waiting = State()

# ========== ОБРАБОТЧИКИ AIOGRAM ==========
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    if not is_owner(message.from_user.id):
        await message.answer("⛔ Доступ запрещён.")
        return
    await message.answer(
        "👋 **Бот для конкурсов**\n\n"
        "Управляйте мониторингом чатов и настройками через кнопки ниже.",
        reply_markup=main_keyboard(),
        parse_mode="Markdown"
    )

@dp.callback_query(F.data == "back_to_main")
async def back_to_main(callback: types.CallbackQuery):
    if not is_owner(callback.from_user.id):
        await callback.answer("Нет доступа")
        return
    await callback.message.edit_text("👋 Главное меню:", reply_markup=main_keyboard())

# Добавление чата (с сохранением правильного положительного ID)
@dp.callback_query(F.data == "add_chat")
async def add_chat_start(callback: types.CallbackQuery, state: FSMContext):
    if not is_owner(callback.from_user.id):
        await callback.answer("Нет доступа")
        return
    await callback.message.edit_text(
        "📎 **Отправьте ссылку, юзернейм или ID чата/канала**",
        parse_mode="Markdown"
    )
    await state.set_state(AddChat.waiting)

@dp.message(AddChat.waiting)
async def add_chat_input(message: types.Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        await state.clear()
        return
    input_text = message.text.strip()
    try:
        entity = await user_client.get_entity(input_text)
        raw_id = entity.id
        # Преобразуем в правильный положительный ID
        if str(raw_id).startswith('-100'):
            chat_id = int(str(raw_id)[4:])
        else:
            chat_id = abs(raw_id)
        title = getattr(entity, 'title', None) or getattr(entity, 'username', str(chat_id))
        if await add_chat(chat_id, title):
            await message.answer(f"✅ Чат **{title}** добавлен (ID: {chat_id}).", parse_mode="Markdown")
        else:
            await message.answer("❌ Чат уже в списке.")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")
    await state.clear()
    await message.answer("👋 Возврат в меню.", reply_markup=main_keyboard())

# Удаление чата
@dp.callback_query(F.data == "del_chat")
async def del_chat_start(callback: types.CallbackQuery):
    if not is_owner(callback.from_user.id):
        await callback.answer("Нет доступа")
        return
    chats = await get_chats()
    if not chats:
        await callback.message.edit_text("📭 Список чатов пуст.", reply_markup=back_keyboard())
        return
    kb = InlineKeyboardBuilder()
    for chat_id, title in chats:
        kb.button(text=title, callback_data=f"delchat_{chat_id}")
    kb.button(text="🔙 Назад", callback_data="back_to_main")
    kb.adjust(1)
    await callback.message.edit_text("Выберите чат для удаления:", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("delchat_"))
async def del_chat_confirm(callback: types.CallbackQuery):
    if not is_owner(callback.from_user.id):
        await callback.answer("Нет доступа")
        return
    chat_id = int(callback.data.split("_")[1])
    await remove_chat(chat_id)
    await callback.answer("Чат удалён")
    await callback.message.edit_text("👋 Главное меню:", reply_markup=main_keyboard())

# Список чатов
@dp.callback_query(F.data == "list_chats")
async def list_chats(callback: types.CallbackQuery):
    if not is_owner(callback.from_user.id):
        await callback.answer("Нет доступа")
        return
    chats = await get_chats()
    if not chats:
        await callback.message.edit_text("📭 Список чатов пуст.", reply_markup=back_keyboard())
        return
    text = "**Список чатов (ID для проверки):**\n\n"
    for chat_id, title in chats:
        text += f"• `{chat_id}` — {title}\n"
    await callback.message.edit_text(text, reply_markup=back_keyboard(), parse_mode="Markdown")

# Меню ключевых фраз
@dp.callback_query(F.data == "keywords_menu")
async def keywords_menu(callback: types.CallbackQuery):
    if not is_owner(callback.from_user.id):
        await callback.answer("Нет доступа")
        return
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Добавить фразу", callback_data="add_keyword")
    kb.button(text="➖ Удалить фразу", callback_data="del_keyword")
    kb.button(text="📋 Список фраз", callback_data="list_keywords")
    kb.button(text="🔙 Назад", callback_data="back_to_main")
    kb.adjust(1)
    await callback.message.edit_text("🔑 **Управление ключевыми фразами**", reply_markup=kb.as_markup(), parse_mode="Markdown")

@dp.callback_query(F.data == "add_keyword")
async def add_keyword_start(callback: types.CallbackQuery, state: FSMContext):
    if not is_owner(callback.from_user.id):
        await callback.answer("Нет доступа")
        return
    await callback.message.edit_text("✏️ **Введите ключевую фразу** (например, «первые 100 комментариев»):")
    await state.set_state(AddKeyword.waiting)

@dp.message(AddKeyword.waiting)
async def add_keyword_input(message: types.Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        await state.clear()
        return
    keyword = message.text.strip().lower()
    if await add_keyword(keyword):
        await message.answer(f"✅ Ключевая фраза **{keyword}** добавлена.")
    else:
        await message.answer("❌ Такая фраза уже есть.")
    await state.clear()
    await message.answer("👋 Возврат в меню.", reply_markup=main_keyboard())

@dp.callback_query(F.data == "del_keyword")
async def del_keyword_start(callback: types.CallbackQuery):
    if not is_owner(callback.from_user.id):
        await callback.answer("Нет доступа")
        return
    keywords = await get_keywords()
    if not keywords:
        await callback.message.edit_text("📭 Список ключевых фраз пуст.", reply_markup=back_keyboard())
        return
    kb = InlineKeyboardBuilder()
    for kw in keywords:
        kb.button(text=kw, callback_data=f"delkw_{kw}")
    kb.button(text="🔙 Назад", callback_data="keywords_menu")
    kb.adjust(1)
    await callback.message.edit_text("Выберите фразу для удаления:", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("delkw_"))
async def del_keyword_confirm(callback: types.CallbackQuery):
    if not is_owner(callback.from_user.id):
        await callback.answer("Нет доступа")
        return
    keyword = callback.data[6:]
    await remove_keyword(keyword)
    await callback.answer("Фраза удалена")
    await callback.message.edit_text("👋 Главное меню:", reply_markup=main_keyboard())

@dp.callback_query(F.data == "list_keywords")
async def list_keywords(callback: types.CallbackQuery):
    if not is_owner(callback.from_user.id):
        await callback.answer("Нет доступа")
        return
    keywords = await get_keywords()
    if not keywords:
        await callback.message.edit_text("📭 Список ключевых фраз пуст.", reply_markup=back_keyboard())
        return
    text = "**Ключевые фразы:**\n" + "\n".join(f"• {kw}" for kw in keywords)
    await callback.message.edit_text(text, reply_markup=back_keyboard(), parse_mode="Markdown")

# Меню ответов
@dp.callback_query(F.data == "replies_menu")
async def replies_menu(callback: types.CallbackQuery):
    if not is_owner(callback.from_user.id):
        await callback.answer("Нет доступа")
        return
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Добавить ответ", callback_data="add_reply")
    kb.button(text="➖ Удалить ответ", callback_data="del_reply")
    kb.button(text="📋 Список ответов", callback_data="list_replies")
    kb.button(text="🔙 Назад", callback_data="back_to_main")
    kb.adjust(1)
    await callback.message.edit_text("💬 **Управление ответами**", reply_markup=kb.as_markup(), parse_mode="Markdown")

@dp.callback_query(F.data == "add_reply")
async def add_reply_start(callback: types.CallbackQuery, state: FSMContext):
    if not is_owner(callback.from_user.id):
        await callback.answer("Нет доступа")
        return
    await callback.message.edit_text("✏️ **Введите текст ответа**, который будет отправляться при обнаружении ключевой фразы:")
    await state.set_state(AddReply.waiting)

@dp.message(AddReply.waiting)
async def add_reply_input(message: types.Message, state: FSMContext):
    if not is_owner(message.from_user.id):
        await state.clear()
        return
    reply = message.text.strip()
    if await add_reply(reply):
        await message.answer(f"✅ Ответ добавлен.")
    else:
        await message.answer("❌ Такой ответ уже есть.")
    await state.clear()
    await message.answer("👋 Возврат в меню.", reply_markup=main_keyboard())

@dp.callback_query(F.data == "del_reply")
async def del_reply_start(callback: types.CallbackQuery):
    if not is_owner(callback.from_user.id):
        await callback.answer("Нет доступа")
        return
    replies = await get_replies()
    if not replies:
        await callback.message.edit_text("📭 Список ответов пуст.", reply_markup=back_keyboard())
        return
    kb = InlineKeyboardBuilder()
    for r in replies:
        btn_text = r if len(r) <= 30 else r[:27] + "..."
        kb.button(text=btn_text, callback_data=f"delrep_{r}")
    kb.button(text="🔙 Назад", callback_data="replies_menu")
    kb.adjust(1)
    await callback.message.edit_text("Выберите ответ для удаления:", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("delrep_"))
async def del_reply_confirm(callback: types.CallbackQuery):
    if not is_owner(callback.from_user.id):
        await callback.answer("Нет доступа")
        return
    reply = callback.data[7:]
    await remove_reply(reply)
    await callback.answer("Ответ удалён")
    await callback.message.edit_text("👋 Главное меню:", reply_markup=main_keyboard())

@dp.callback_query(F.data == "list_replies")
async def list_replies(callback: types.CallbackQuery):
    if not is_owner(callback.from_user.id):
        await callback.answer("Нет доступа")
        return
    replies = await get_replies()
    if not replies:
        await callback.message.edit_text("📭 Список ответов пуст.", reply_markup=back_keyboard())
        return
    text = "**Ответы:**\n" + "\n".join(f"• {r}" for r in replies)
    await callback.message.edit_text(text, reply_markup=back_keyboard(), parse_mode="Markdown")

# Управление мониторингом
@dp.callback_query(F.data == "start_monitor")
async def start_monitor(callback: types.CallbackQuery):
    if not is_owner(callback.from_user.id):
        await callback.answer("Нет доступа")
        return
    await set_setting('monitoring_active', '1')
    await callback.message.edit_text("▶️ Мониторинг запущен.", reply_markup=main_keyboard())

@dp.callback_query(F.data == "stop_monitor")
async def stop_monitor(callback: types.CallbackQuery):
    if not is_owner(callback.from_user.id):
        await callback.answer("Нет доступа")
        return
    await set_setting('monitoring_active', '0')
    await callback.message.edit_text("⏸️ Мониторинг остановлен.", reply_markup=main_keyboard())

@dp.callback_query(F.data == "status")
async def status(callback: types.CallbackQuery):
    if not is_owner(callback.from_user.id):
        await callback.answer("Нет доступа")
        return
    active = await get_setting('monitoring_active')
    chats = await get_chats()
    keywords = await get_keywords()
    replies = await get_replies()
    status_text = "🟢 Активен" if active == '1' else "🔴 Остановлен"
    text = (
        f"**Статус мониторинга:** {status_text}\n"
        f"**Чатов:** {len(chats)}\n"
        f"**Ключевых фраз:** {len(keywords)}\n"
        f"**Ответов:** {len(replies)}"
    )
    await callback.message.edit_text(text, reply_markup=back_keyboard(), parse_mode="Markdown")

# ========== ОБРАБОТЧИК С ИСПРАВЛЕННОЙ ПРОВЕРКОЙ ID ==========
@user_client.on(events.NewMessage(incoming=True))
async def message_handler(event):
    try:
        # Всегда логируем факт получения сообщения из любого чата
        logger.info(f"📩 Новое сообщение в чате {event.chat_id} от {event.sender_id}: {event.message.text[:50]}...")

        # Правильное преобразование ID канала/супергруппы
        raw_id = event.chat_id
        if str(raw_id).startswith('-100'):
            chat_id_pos = int(str(raw_id)[4:])  # убираем '-100'
        else:
            chat_id_pos = abs(raw_id)

        logger.info(f"🔍 Преобразованный ID: {chat_id_pos} (исходный: {event.chat_id})")

        active = await get_setting('monitoring_active')
        if active != '1':
            logger.info("Мониторинг неактивен, игнорируем")
            return

        chats = await get_chats()
        chat_ids = [c[0] for c in chats]
        logger.info(f"📋 Список ID из базы: {chat_ids}")

        if chat_id_pos not in chat_ids:
            logger.info(f"❌ Чат {chat_id_pos} не в списке")
            return
        else:
            logger.info(f"✅ Чат {chat_id_pos} найден в списке")

        if REACT_ONLY_TO_FORWARDS and not event.message.fwd_from:
            logger.info("Сообщение не переслано, игнорируем (режим только форварды)")
            return

        msg_text = event.message.text or event.message.caption or ''
        if not msg_text:
            logger.info("Пустое сообщение, игнорируем")
            return

        keywords = await get_keywords()
        msg_lower = msg_text.lower()
        found = any(kw.lower() in msg_lower for kw in keywords)
        if not found:
            logger.info(f"Ключевые слова не найдены в: {msg_text}")
            return

        replies = await get_replies()
        if not replies:
            logger.warning("Нет ответов для отправки")
            return

        reply_text = random.choice(replies)
        try:
            await event.reply(reply_text)
            logger.info(f"✅ Ответ отправлен в чат {event.chat_id}: {reply_text}")
        except FloodWaitError as e:
            logger.warning(f"Flood wait {e.seconds} сек")
            await asyncio.sleep(e.seconds)
        except Exception as e:
            logger.error(f"Ошибка отправки: {e}")

    except Exception as e:
        logger.exception(f"❌ КРИТИЧЕСКАЯ ОШИБКА В ОБРАБОТЧИКЕ: {e}")

# ========== ОСНОВНАЯ ФУНКЦИЯ ==========
async def main():
    await init_db()
    logger.info("База данных инициализирована")

    # Подключение пользовательского аккаунта
    try:
        if not SESSION_STRING:
            logger.info("Сессия не найдена. Начинаем авторизацию...")
            await user_client.start(phone=PHONE)
            session_str = user_client.session.save()
            if session_str:
                logger.info("=" * 50)
                logger.info("СОХРАНИТЕ ЭТУ СТРОКУ И ВСТАВЬТЕ В SESSION_STRING:")
                logger.info(session_str)
                logger.info("=" * 50)
            else:
                logger.warning("Не удалось получить session string, но авторизация прошла.")
        else:
            await user_client.start()
        logger.info("Пользовательский аккаунт подключён")
    except SessionPasswordNeededError:
        password = input("Введите пароль двухфакторной аутентификации: ")
        await user_client.start(phone=PHONE, password=password)
        session_str = user_client.session.save()
        if session_str:
            logger.info("=" * 50)
            logger.info("СОХРАНИТЕ ЭТУ СТРОКУ И ВСТАВЬТЕ В SESSION_STRING:")
            logger.info(session_str)
            logger.info("=" * 50)
        else:
            logger.warning("Не удалось получить session string, но авторизация прошла.")
    except Exception as e:
        logger.error(f"Ошибка подключения пользователя: {e}")
        return

    me = await user_client.get_me()
    logger.info(f"Аккаунт: {me.first_name} (@{me.username})")

    # Запуск бота управления
    logger.info("Запуск бота управления...")
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Ошибка при работе бота: {e}")

if __name__ == '__main__':
    asyncio.run(main())
