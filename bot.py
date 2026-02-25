# bot.py
import telebot
from telebot import types
import config
from summarizer import MediaSummarizer
import os
import tempfile
import time
import logging
import re  # Добавляем для работы с регулярными выражениями

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Инициализация бота
bot = telebot.TeleBot(config.TOKEN)

# Инициализация обработчика
logger.info("🚀 Запуск бота...")
try:
    summarizer = MediaSummarizer(model_size=config.MODEL_SIZE)
    logger.info("✅ Модель успешно загружена")
except Exception as e:
    logger.error(f"❌ Ошибка загрузки модели: {e}")
    summarizer = None

# Хранилище состояний пользователей (в памяти)
user_states = {}


@bot.message_handler(commands=['start'])
def send_welcome(message):
    """Приветственное сообщение"""
    if summarizer is None:
        bot.send_message(
            message.chat.id,
            "❌ Бот временно недоступен. Попробуйте позже."
        )
        return

    bot.send_message(
        message.chat.id,
        config.WELCOME_TEXT,
        parse_mode='HTML'
    )
    logger.info(f"👤 Новый пользователь: {message.from_user.username or message.from_user.id}")


@bot.message_handler(commands=['help'])
def send_help(message):
    """Справка"""
    bot.send_message(
        message.chat.id,
        config.HELP_TEXT,
        parse_mode='HTML'
    )


@bot.message_handler(commands=['about'])
def send_about(message):
    """О проекте"""
    bot.send_message(
        message.chat.id,
        config.ABOUT_TEXT,
        parse_mode='HTML'
    )


@bot.message_handler(content_types=['document', 'audio', 'video', 'voice'])
def handle_file(message):
    """Обработка полученных файлов и голосовых сообщений"""
    if summarizer is None:
        bot.send_message(message.chat.id, "❌ Бот временно недоступен")
        return

    chat_id = message.chat.id

    # Проверяем, не обрабатывает ли бот уже файл от этого пользователя
    if user_states.get(chat_id) == 'processing':
        bot.send_message(
            chat_id,
            "⏳ Сейчас обрабатываю другой файл. Подождите немного."
        )
        return

    # Определяем тип файла и получаем информацию
    file_id = None
    file_name = None
    file_size = None

    if message.document:
        file_id = message.document.file_id
        file_name = message.document.file_name
        file_size = message.document.file_size
    elif message.audio:
        file_id = message.audio.file_id
        file_name = message.audio.file_name or f"audio_{int(time.time())}.mp3"
        file_size = message.audio.file_size
    elif message.video:
        file_id = message.video.file_id
        file_name = message.video.file_name or f"video_{int(time.time())}.mp4"
        file_size = message.video.file_size
    elif message.voice:
        file_id = message.voice.file_id
        file_name = f"voice_{int(time.time())}.ogg"  # Голосовые в формате OGG
        file_size = message.voice.file_size
        logger.info(f"🎤 Получено голосовое сообщение, длительность: {message.voice.duration} сек")
    else:
        bot.send_message(chat_id, "❌ Неподдерживаемый тип файла")
        return

    # Проверка размера
    if file_size > config.MAX_FILE_SIZE:
        bot.send_message(
            chat_id,
            f"❌ Файл слишком большой (максимум {config.MAX_FILE_SIZE // 1024 // 1024} МБ)"
        )
        return

    # Проверка формата
    ext = os.path.splitext(file_name)[1].lower()
    if ext not in config.SUPPORTED_FORMATS:
        bot.send_message(
            chat_id,
            f"❌ Неподдерживаемый формат. Поддерживаются: {', '.join(config.SUPPORTED_FORMATS)}"
        )
        return

    # Отправляем подтверждение
    file_type = "голосовое сообщение" if message.voice else "файл"
    msg = bot.send_message(
        chat_id,
        f"✅ {file_type} получено: {file_name}\n⏳ Начинаю обработку..."
    )

    # Устанавливаем состояние "в обработке"
    user_states[chat_id] = 'processing'

    try:
        # Скачиваем файл
        file_info = bot.get_file(file_id)
        downloaded_file = bot.download_file(file_info.file_path)

        # Сохраняем во временный файл
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            tmp.write(downloaded_file)
            tmp_path = tmp.name

        logger.info(f"📥 Файл сохранен: {tmp_path}")

        # Обновляем сообщение о статусе
        bot.edit_message_text(
            "🔄 Обработка: распознавание речи... (это может занять 10-30 секунд)",
            chat_id,
            msg.message_id
        )

        # Обрабатываем файл
        result = summarizer.process_file(tmp_path)

        # Формируем красивые ключевые слова
        keywords_text = ', '.join(result['keywords'][:8])
        if len(result['keywords']) > 8:
            keywords_text += f" и ещё {len(result['keywords']) - 8}"

        # Создаем ответ
        response = f"""
🎯 <b>ГОТОВО! Ваш конспект</b>

📊 <b>Статистика:</b>
• Длительность: {result['duration_str']}
• Объем текста: {result['stats']['words']} слов
• Ключевых слов: {len(result['keywords'])}

🔑 <b>Ключевые слова:</b>
{keywords_text}

📝 <b>Краткое содержание:</b>
{result['summary'][:300]}{'...' if len(result['summary']) > 300 else ''}

⏱ <b>Длительность:</b> {result['duration_str']}

<i>Полный текст сохранен в файле ниже 👇</i>
        """

        # Отправляем результат
        bot.send_message(chat_id, response, parse_mode='HTML')

        # ========== УЛУЧШЕННОЕ ФОРМАТИРОВАНИЕ ТЕКСТОВОГО ФАЙЛА ==========
        # Создаем красивый текстовый файл с абзацами
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                                         delete=False, suffix='.txt') as f:

            # Заголовок
            f.write("=" * 60 + "\n")
            f.write("ПОЛНЫЙ ТРАНСКРИПТ\n")
            f.write("=" * 60 + "\n\n")

            # Разбиваем текст на предложения
            sentences = re.split(r'[.!?]+', result['transcript'])
            sentences = [s.strip() for s in sentences if s.strip()]

            # Группируем предложения в абзацы (по 3-5 предложений)
            paragraph = []
            paragraph_size = 0

            for i, sentence in enumerate(sentences, 1):
                paragraph.append(sentence)
                paragraph_size += 1

                # Создаем новый абзац каждые 3-5 предложений
                if paragraph_size >= 3 or i % 3 == 0 or i == len(sentences):
                    if paragraph:
                        # Соединяем предложения в абзац
                        paragraph_text = ". ".join(paragraph) + "."

                        # Разбиваем длинные абзацы на строки (макс 80 символов)
                        words = paragraph_text.split()
                        line = []
                        line_length = 0

                        for word in words:
                            if line_length + len(word) + 1 <= 80:
                                line.append(word)
                                line_length += len(word) + 1
                            else:
                                if line:
                                    f.write("   " + " ".join(line) + "\n")
                                line = [word]
                                line_length = len(word) + 1

                        if line:
                            f.write("   " + " ".join(line) + "\n")

                        f.write("\n")  # Пустая строка между абзацами
                        paragraph = []
                        paragraph_size = 0

            # Ключевые слова
            f.write("\n" + "=" * 60 + "\n")
            f.write("КЛЮЧЕВЫЕ СЛОВА:\n")
            f.write("=" * 60 + "\n")

            # Выводим ключевые слова в 3 колонки
            keywords = result['keywords']
            for i in range(0, len(keywords), 3):
                row = keywords[i:i + 3]
                # Дополняем пустыми строками до 3 элементов
                while len(row) < 3:
                    row.append("")
                f.write(f"   {row[0]:<20} {row[1]:<20} {row[2]:<20}\n")

            transcript_path = f.name
        # ========== КОНЕЦ УЛУЧШЕННОГО ФОРМАТИРОВАНИЯ ==========

        # Отправляем файл
        with open(transcript_path, 'rb') as f:
            bot.send_document(
                chat_id,
                f,
                caption="📄 Полный текст транскрипции"
            )

        # Удаляем временные файлы
        os.unlink(tmp_path)
        os.unlink(transcript_path)

        logger.info(f"✅ Файл {file_name} успешно обработан для {message.from_user.username or message.from_user.id}")

    except Exception as e:
        logger.error(f"❌ Ошибка обработки: {e}", exc_info=True)
        bot.send_message(
            chat_id,
            "❌ Произошла ошибка при обработке. Попробуйте:\n"
            "• Использовать другой файл\n"
            "• Убедиться, что в файле есть речь\n"
            "• Попробовать позже"
        )

    finally:
        # Сбрасываем состояние пользователя
        user_states[chat_id] = None


@bot.message_handler(func=lambda message: True)
def handle_text(message):
    """Обработка текстовых сообщений"""
    bot.send_message(
        message.chat.id,
        "📤 Отправьте аудио или видео файл для создания конспекта.\n"
        "Используйте /help для справки."
    )


if __name__ == '__main__':
    logger.info("✅ Бот запущен и готов к работе!")
    logger.info(f"🤔 Информация о боте: {bot.get_me()}")

    # Запуск бота
    try:
        bot.infinity_polling()
    except Exception as e:
        logger.error(f"❌ Ошибка запуска бота: {e}")