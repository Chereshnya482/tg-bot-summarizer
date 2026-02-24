import whisper
import os
import tempfile
import logging
from collections import Counter
import re
import subprocess
from tqdm import tqdm
import time

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class MediaSummarizer:
    def __init__(self, model_size="tiny"):
        """Инициализация с моделью Whisper"""
        logger.info(f"Загрузка модели Whisper ({model_size})...")
        self.model = whisper.load_model(model_size)
        logger.info("✅ Модель загружена!")

        # Проверяем ffmpeg
        self._check_ffmpeg()

    def _check_ffmpeg(self):
        """Проверка наличия ffmpeg"""
        try:
            result = subprocess.run(['ffmpeg', '-version'],
                                    capture_output=True, text=True)
            if result.returncode == 0:
                logger.info("✅ FFmpeg найден")
                return True
            else:
                logger.error("❌ FFmpeg не работает")
                return False
        except:
            logger.error("❌ FFmpeg не установлен")
            return False

    def extract_audio_from_video(self, video_path):
        """Извлечение аудио из видео через ffmpeg"""
        logger.info(f"🎬 Извлечение аудио из видео...")

        # Создаем временный WAV файл
        temp_audio = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
        temp_audio.close()

        try:
            # Команда ffmpeg для извлечения аудио
            cmd = [
                'ffmpeg',
                '-i', video_path,
                '-vn',
                '-acodec', 'pcm_s16le',
                '-ar', '16000',
                '-ac', '1',
                '-y',
                temp_audio.name
            ]

            # Запускаем ffmpeg
            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode != 0:
                logger.error(f"FFmpeg ошибка: {result.stderr}")
                raise Exception("Ошибка извлечения аудио")

            # Проверяем размер файла
            if os.path.getsize(temp_audio.name) < 1000:
                raise Exception("Аудио файл слишком маленький")

            logger.info(f"✅ Аудио извлечено")
            return temp_audio.name

        except Exception as e:
            logger.error(f"❌ Ошибка: {e}")
            if os.path.exists(temp_audio.name):
                os.unlink(temp_audio.name)
            raise

    def transcribe(self, audio_path):
        """Распознавание речи с красивым прогресс-баром"""
        logger.info("🎤 Распознавание речи...")

        # Создаем прогресс-бар
        with tqdm(total=100, desc="Прогресс", unit="%", ncols=80) as pbar:
            # Показываем начало
            pbar.set_description("🎤 Загрузка аудио")
            pbar.update(10)

            try:
                # Само распознавание
                result = self.model.transcribe(
                    audio_path,
                    language='ru',
                    fp16=False,
                    verbose=False  # Выключаем встроенный вывод
                )

                # Обновляем прогресс
                pbar.update(90)
                pbar.set_description("✅ Готово")

            except Exception as e:
                pbar.set_description("❌ Ошибка")
                logger.error(f"Ошибка транскрибации: {e}")
                raise

        text = result['text'].strip()
        words_count = len(text.split())
        logger.info(f"✅ Распознано {words_count} слов")

        return text, result.get('segments', [])

    def summarize_text(self, text):
        """Создание краткого конспекта"""
        if not text or len(text) < 50:
            return text

        # Разбиваем на предложения
        sentences = re.split(r'[.!?]+', text)
        sentences = [s.strip() for s in sentences if len(s.strip()) > 20]

        if len(sentences) <= 3:
            return text

        # Берем ключевые предложения
        summary = []
        summary.append(sentences[0])  # первое

        if len(sentences) >= 3:
            mid = len(sentences) // 2
            summary.append(sentences[mid])  # среднее

        summary.append(sentences[-1])  # последнее

        return '. '.join(summary) + '.'

    def denoise_audio(self, audio_path):
        """Простое шумоподавление через ffmpeg"""
        denoised = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
        denoised.close()

        cmd = [
            'ffmpeg',
            '-i', audio_path,
            '-af', 'afftdn=nf=-25',  # Фильтр шумоподавления
            '-y',
            denoised.name
        ]

        subprocess.run(cmd, capture_output=True)
        return denoised.name

    def extract_keywords(self, text, top_n=10):
        """Извлечение ключевых слов"""
        stop_words = {'и', 'в', 'на', 'с', 'по', 'для', 'это', 'как', 'то',
                      'что', 'не', 'но', 'а', 'из', 'у', 'за', 'о', 'от', 'до',
                      'мы', 'вы', 'он', 'она', 'они', 'к', 'при', 'так', 'все'}

        words = re.findall(r'[а-яёА-ЯЁ]{4,}', text.lower())
        filtered = [w for w in words if w not in stop_words]
        word_freq = Counter(filtered)

        return [word for word, count in word_freq.most_common(top_n)]

    def process_file(self, file_path):
        """Полная обработка файла"""
        temp_files = []

        try:
            logger.info(f"📁 Начало обработки: {file_path}")

            # Определяем тип файла
            is_video = file_path.lower().endswith(('.mp4', '.avi', '.mov', '.mkv'))
            is_audio = file_path.lower().endswith(('.mp3', '.wav', '.ogg', '.m4a'))

            # Извлекаем аудио если это видео
            if is_video:
                logger.info("🎬 Это видео, извлекаем аудио...")
                audio_path = self.extract_audio_from_video(file_path)
                temp_files.append(audio_path)
            elif is_audio:
                logger.info("🎵 Это аудио, обрабатываем напрямую")
                audio_path = file_path
            else:
                raise Exception("Неподдерживаемый формат файла")

            # Распознаем речь
            transcript, segments = self.transcribe(audio_path)

            if not transcript:
                raise Exception("Речь не распознана")

            # Создаем конспект
            summary = self.summarize_text(transcript)
            keywords = self.extract_keywords(transcript)

            # Статистика
            words_count = len(transcript.split())
            duration = segments[-1]['end'] if segments else 0
            minutes = int(duration // 60)
            seconds = int(duration % 60)

            result = {
                'transcript': transcript,
                'summary': summary,
                'keywords': keywords,
                'duration_str': f"{minutes} мин {seconds} сек",
                'stats': {
                    'words': words_count,
                    'duration': duration
                }
            }

            logger.info(f"✅ Готово! {words_count} слов")
            return result

        except Exception as e:
            logger.error(f"❌ Ошибка: {e}")
            raise

        finally:
            # Чистим временные файлы
            for f in temp_files:
                try:
                    if os.path.exists(f):
                        os.unlink(f)
                        logger.info(f"🧹 Удален: {f}")
                except:
                    pass