import os
import sqlite3
import asyncio
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
import aiohttp

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Токены
TELEGRAM_TOKEN = "8511592619:AAHPFOr6MBXq8PNFCdEfNe37J9YDIX8kQes"
GROQ_API_KEY = "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"

# Инициализация бота с новым синтаксисом
bot = Bot(
    token=TELEGRAM_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()

# Константы
BOT_NAME = "сирис"
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL_NAME = "llama-3.3-70b-versatile"

# Инициализация БД
def init_db():
    try:
        conn = sqlite3.connect('bot.db')
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                username TEXT,
                message_text TEXT NOT NULL,
                is_bot BOOLEAN NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        conn.close()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Database initialization error: {e}")

def save_message(user_id: int, chat_id: int, username: str, message_text: str, is_bot: bool):
    try:
        conn = sqlite3.connect('bot.db')
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO messages (user_id, chat_id, username, message_text, is_bot)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, chat_id, username, message_text, is_bot))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Error saving message: {e}")

def get_chat_history(chat_id: int, user_id: int, limit: int = 10):
    try:
        conn = sqlite3.connect('bot.db')
        cursor = conn.cursor()
        cursor.execute('''
            SELECT message_text, is_bot FROM messages
            WHERE chat_id = ? AND user_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
        ''', (chat_id, user_id, limit))
        rows = cursor.fetchall()
        conn.close()
        
        history = []
        for text, is_bot in reversed(rows):
            role = "assistant" if is_bot else "user"
            history.append({"role": role, "content": text})
        return history
    except Exception as e:
        logger.error(f"Error getting chat history: {e}")
        return []

async def get_ai_response(messages: list) -> str:
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": MODEL_NAME,
        "messages": [
            {
                "role": "system",
                "content": "Ты умный AI-ассистент по имени Сирис. Отвечай дружелюбно, помогай пользователям и поддерживай разговор. Используй emoji когда это уместно. Отвечай на русском языке."
            }
        ] + messages,
        "temperature": 0.7,
        "max_tokens": 1024
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(GROQ_API_URL, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as response:
                if response.status == 200:
                    data = await response.json()
                    return data['choices'][0]['message']['content']
                else:
                    error_text = await response.text()
                    logger.error(f"Groq API error: {response.status} - {error_text}")
                    return "Извините, произошла ошибка при обработке запроса 😔"
    except asyncio.TimeoutError:
        logger.error("Groq API timeout")
        return "Время ожидания истекло. Попробуйте еще раз 🕐"
    except Exception as e:
        logger.error(f"Error calling Groq API: {e}")
        return "Произошла ошибка при подключении к AI 😔"

async def should_respond(message: Message) -> bool:
    try:
        # В личных чатах отвечаем всегда
        if message.chat.type == 'private':
            return True
        
        # В группах проверяем условия
        text_lower = message.text.lower() if message.text else ""
        
        # Если это ответ на сообщение бота
        if message.reply_to_message and message.reply_to_message.from_user.id == bot.id:
            return True
        
        # Если упомянуто имя бота
        if BOT_NAME in text_lower:
            return True
        
        # Если бот упомянут через @
        if message.entities:
            for entity in message.entities:
                if entity.type == "mention":
                    bot_info = await bot.get_me()
                    mention = message.text[entity.offset:entity.offset + entity.length]
                    if mention.lower().replace('@', '') == bot_info.username.lower():
                        return True
        
        return False
    except Exception as e:
        logger.error(f"Error in should_respond: {e}")
        return False

@dp.message(CommandStart())
async def cmd_start(message: Message):
    try:
        user_name = message.from_user.first_name
        welcome_text = f"""
<b>👋 Привет, {user_name}!</b>

Я <b>Сирис</b> - AI-ассистент на базе Groq (LLaMA 3.3 70B) 🤖

<b>Как я работаю:</b>
• В <i>личных чатах</i> отвечаю на все сообщения
• В <i>группах</i> отвечаю когда:
  - Вы отвечаете на мое сообщение
  - Упоминаете мое имя "сирис"
  - Упоминаете меня через @

<b>Команды:</b>
/start - Показать это сообщение
/clear - Очистить историю разговора
/help - Помощь

Готов пообщаться! 💬
"""
        await message.answer(welcome_text)
        save_message(
            message.from_user.id,
            message.chat.id,
            message.from_user.username or message.from_user.first_name,
            "/start",
            False
        )
        logger.info(f"User {message.from_user.id} started bot")
    except Exception as e:
        logger.error(f"Error in cmd_start: {e}")

@dp.message(Command("clear"))
async def cmd_clear(message: Message):
    try:
        conn = sqlite3.connect('bot.db')
        cursor = conn.cursor()
        cursor.execute('DELETE FROM messages WHERE chat_id = ? AND user_id = ?', 
                      (message.chat.id, message.from_user.id))
        conn.commit()
        conn.close()
        await message.answer("<b>✅ История разговора очищена!</b>")
        logger.info(f"User {message.from_user.id} cleared history")
    except Exception as e:
        logger.error(f"Error in cmd_clear: {e}")
        await message.answer("Произошла ошибка при очистке истории")

@dp.message(Command("help"))
async def cmd_help(message: Message):
    try:
        help_text = """
<b>📖 Помощь по боту Сирис</b>

<b>Основные возможности:</b>
• Веду диалог и запоминаю контекст
• Отвечаю на вопросы
• Помогаю с задачами
• Работаю в группах

<b>В группах:</b>
Чтобы я ответил, нужно:
1️⃣ Ответить на мое сообщение (Reply)
2️⃣ Написать "сирис" в сообщении
3️⃣ Упомянуть меня через @

<b>Команды:</b>
/start - Приветствие
/clear - Очистить историю
/help - Эта справка

<i>Powered by Groq AI 🚀</i>
"""
        await message.answer(help_text)
    except Exception as e:
        logger.error(f"Error in cmd_help: {e}")

@dp.message(F.text)
async def handle_message(message: Message):
    try:
        # Проверяем, нужно ли отвечать
        if not await should_respond(message):
            return
        
        logger.info(f"Processing message from user {message.from_user.id}: {message.text[:50]}")
        
        # Показываем индикатор печати
        await bot.send_chat_action(message.chat.id, "typing")
        
        user_text = message.text
        user_id = message.from_user.id
        chat_id = message.chat.id
        username = message.from_user.username or message.from_user.first_name
        
        # Сохраняем сообщение пользователя
        save_message(user_id, chat_id, username, user_text, False)
        
        # Получаем историю разговора
        history = get_chat_history(chat_id, user_id, limit=10)
        
        # Добавляем текущее сообщение
        history.append({"role": "user", "content": user_text})
        
        # Получаем ответ от AI
        ai_response = await get_ai_response(history)
        
        # Сохраняем ответ бота
        save_message(user_id, chat_id, "bot", ai_response, True)
        
        # Отправляем ответ
        try:
            await message.answer(f"<b>🤖 Сирис:</b>\n\n{ai_response}")
            logger.info(f"Response sent to user {message.from_user.id}")
        except Exception as e:
            logger.error(f"Error sending formatted message: {e}")
            await message.answer(ai_response)
            
    except Exception as e:
        logger.error(f"Error in handle_message: {e}", exc_info=True)
        try:
            await message.answer("Произошла ошибка при обработке сообщения 😔")
        except:
            pass

@dp.message(F.new_chat_members)
async def new_member(message: Message):
    try:
        for member in message.new_chat_members:
            if member.id == bot.id:
                greeting = """
<b>👋 Привет всем!</b>

Я <b>Сирис</b> - AI-ассистент 🤖

Чтобы я ответил в группе:
• Ответьте на мое сообщение
• Напишите "сирис" в сообщении
• Упомяните меня через @

<i>Давайте общаться!</i> 💬
"""
                await message.answer(greeting)
                logger.info(f"Bot added to group {message.chat.id}")
    except Exception as e:
        logger.error(f"Error in new_member: {e}")

async def main():
    try:
        # Инициализация БД
        init_db()
        
        # Получаем информацию о боте
        bot_info = await bot.get_me()
        logger.info(f"╔════════════════════════════════════════╗")
        logger.info(f"║  Bot started successfully!             ║")
        logger.info(f"║  Username: @{bot_info.username:<24} ║")
        logger.info(f"║  Name: {bot_info.first_name:<29} ║")
        logger.info(f"╚════════════════════════════════════════╝")
        
        # Удаляем вебхуки
        await bot.delete_webhook(drop_pending_updates=True)
        
        # Запускаем polling
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
        
    except Exception as e:
        logger.error(f"Fatal error in main: {e}", exc_info=True)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Bot crashed: {e}", exc_info=True)
