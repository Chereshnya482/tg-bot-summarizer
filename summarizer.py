# summarizer.py
import whisper
import os
import tempfile
import logging
from collections import Counter
import re

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class MediaSummarizer:
    def __init__(self, model_size="tiny"):
        """Инициализация с моделью Whisper"""
        logger.info(f"Загрузка модели Whisper ({model_size})...")
        self.model = whisper.load_model(model_size)
        logger.info("✅ Модель загружена!")

    def extract_audio(self, file_path):
        """Извлечение аудио из видео с помощью moviepy"""
        # Если это уже аудио, возвращаем как есть
        if file_path.lower().endswith(('.mp3', '.wav', '.ogg', '.m4a')):
            logger.info("Файл уже является аудио")
            return file_path

        logger.info("Извлечение аудио из видео...")

        try:
            from moviepy.editor import VideoFileClip

            # Создаем временный файл для аудио
            temp_audio = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
            temp_audio.close()

            # Загружаем видео
            video = VideoFileClip(file_path)

            # Извлекаем аудио - убираем problematic параметры
            video.audio.write_audiofile(temp_audio.name)

            # Закрываем видео
            video.close()

            logger.info(f"✅ Аудио извлечено: {temp_audio.name}")
            return temp_audio.name

        except ImportError:
            logger.error("MoviePy не установлен. Установите: pip install moviepy")
            raise Exception("MoviePy не установлен")
        except Exception as e:
            logger.error(f"Ошибка извлечения аудио: {e}")
            # Пробуем альтернативный метод
            return self._extract_audio_alternative(file_path)

    def _extract_audio_alternative(self, file_path):
        """Альтернативный метод извлечения аудио"""
        try:
            # Пробуем использовать ffmpeg напрямую
            import subprocess

            temp_audio = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
            temp_audio.close()

            # Команда ffmpeg для извлечения аудио
            cmd = [
                'ffmpeg',
                '-i', file_path,
                '-vn',  # Без видео
                '-acodec', 'pcm_s16le',  # Кодек для WAV
                '-ar', '16000',  # Частота 16kHz
                '-ac', '1',  # Моно
                '-y',  # Перезаписывать
                temp_audio.name
            ]

            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode == 0:
                logger.info(f"✅ Аудио извлечено через ffmpeg: {temp_audio.name}")
                return temp_audio.name
            else:
                logger.error(f"FFmpeg ошибка: {result.stderr}")
                raise Exception("FFmpeg не смог извлечь аудио")

        except Exception as e:
            logger.error(f"Альтернативный метод тоже не сработал: {e}")
            raise Exception("Не удалось извлечь аудио из видео")

    def transcribe(self, audio_path):
        """Распознавание речи"""
        logger.info("Распознавание речи...")

        try:
            result = self.model.transcribe(
                audio_path,
                language='ru',
                task='transcribe',
                fp16=False
            )

            text = result['text'].strip()
            words_count = len(text.split())
            logger.info(f"✅ Распознано {words_count} слов")

            return text, result.get('segments', [])

        except Exception as e:
            logger.error(f"Ошибка транскрибации: {e}")
            raise Exception("Не удалось распознать речь")

    def summarize_text(self, text, max_sentences=3):
        """Создание краткого конспекта"""
        if not text:
            return ""

        # Разбиваем на предложения
        sentences = re.split(r'[.!?]+', text)
        sentences = [s.strip() for s in sentences if len(s.strip()) > 10]

        if len(sentences) <= max_sentences:
            return text

        # Берем ключевые предложения
        summary = []

        # Первое предложение (обычно введение)
        if sentences:
            summary.append(sentences[0])

        # Предложение из середины (основная мысль)
        if len(sentences) >= 3:
            mid_idx = len(sentences) // 2
            summary.append(sentences[mid_idx])

        # Последнее предложение (заключение)
        if len(sentences) >= 2:
            summary.append(sentences[-1])

        return '. '.join(summary) + '.'

    def extract_keywords(self, text, top_n=10):
        """Извлечение ключевых слов"""
        # Стоп-слова для русского языка
        stop_words = {
            'и', 'в', 'на', 'с', 'по', 'для', 'это', 'как', 'то',
            'что', 'не', 'но', 'а', 'из', 'у', 'за', 'о', 'от', 'до',
            'мы', 'вы', 'он', 'она', 'они', 'к', 'при', 'так', 'все',
            'еще', 'даже', 'где', 'там', 'тут', 'когда', 'потом', 'зачем',
            'потому', 'поэтому', 'который', 'которая', 'которые', 'чтобы',
            'можно', 'нужно', 'надо', 'будет', 'был', 'была', 'были',
            'очень', 'такой', 'этот', 'эта', 'эти'
        }

        # Находим все слова (только русские, минимум 4 буквы)
        words = re.findall(r'[а-яёА-ЯЁ]{4,}', text.lower())

        # Убираем стоп-слова
        filtered = [w for w in words if w not in stop_words]

        # Считаем частоту
        word_freq = Counter(filtered)

        # Берем топ
        keywords = [word for word, count in word_freq.most_common(top_n)]

        return keywords

    def process_file(self, file_path):
        """Полная обработка файла"""
        temp_files = []  # Для временных файлов

        try:
            # Проверяем существование файла
            if not os.path.exists(file_path):
                raise Exception(f"Файл не найден: {file_path}")

            logger.info(f"📁 Начало обработки: {file_path}")

            # 1. Извлечение аудио (если нужно)
            audio_path = self.extract_audio(file_path)
            if audio_path != file_path:
                temp_files.append(audio_path)

            # 2. Распознавание речи
            transcript, segments = self.transcribe(audio_path)

            if not transcript:
                raise Exception("Не удалось распознать речь")

            # 3. Создание конспекта
            summary = self.summarize_text(transcript)

            # 4. Извлечение ключевых слов
            keywords = self.extract_keywords(transcript)

            # 5. Подсчет статистики
            words_count = len(transcript.split())
            duration = segments[-1]['end'] if segments else 0
            minutes = int(duration // 60)
            seconds = int(duration % 60)

            # Формируем результат
            result = {
                'transcript': transcript,
                'summary': summary,
                'keywords': keywords,
                'duration_str': f"{minutes} мин {seconds} сек",
                'stats': {
                    'words': words_count,
                    'duration': duration,
                    'keywords_count': len(keywords)
                }
            }

            logger.info(f"✅ Обработка завершена: {words_count} слов")
            return result

        except Exception as e:
            logger.error(f"❌ Ошибка обработки: {e}")
            raise

        finally:
            # Удаляем временные файлы
            for temp_file in temp_files:
                try:
                    if os.path.exists(temp_file):
                        os.unlink(temp_file)
                        logger.info(f"Удален временный файл: {temp_file}")
                except Exception as e:
                    logger.warning(f"Не удалось удалить {temp_file}: {e}")