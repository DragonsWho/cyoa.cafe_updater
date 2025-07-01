# image_replacer.py

import os
import sys
import subprocess
import requests
import logging
import base64 # Добавлено
from io import BytesIO # Добавлено
from dotenv import load_dotenv
from pathlib import Path
from PIL import Image, UnidentifiedImageError # Добавлено
import argparse # Добавлено для обработки аргументов командной строки

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("logs/replace_game_image.log", encoding='utf-8'), # Явно указываем кодировку
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)
# Уменьшаем "шум" от библиотеки Pillow в логах
logging.getLogger("PIL").setLevel(logging.WARNING)

# Константы
SCREENSHOTS_DIR = "screenshots"
API_BASE_URL = "https://cyoa.cafe/api"
PUPPETEER_SCRIPT = "get_screenshoot_puppy.js"
ALLOWED_MIME_TYPES = [
    "image/png", "image/jpeg", "image/gif", "image/webp",
    "image/avif", "image/svg+xml"
]

# Параметры для Base64 плейсхолдера (скопировано из образца)
PLACEHOLDER_TARGET_WIDTH = 100
PLACEHOLDER_TARGET_HEIGHT = 133
PLACEHOLDER_QUALITY = 40
PLACEHOLDER_LOSSLESS = False
PLACEHOLDER_RESAMPLE_METHOD = Image.Resampling.LANCZOS
PLACEHOLDER_FORMAT = "WEBP"

load_dotenv()

class GameImageReplacer:
    def __init__(self):
        self.email = os.getenv('EMAIL')
        self.password = os.getenv('PASSWORD')
        self.token = None
        self.games_cache = {}
        logger.info("GameImageReplacer initialized")

    def login(self):
        """Аутентификация в API"""
        logger.info("Attempting to login")
        try:
            response = requests.post(
                f"{API_BASE_URL}/collections/users/auth-with-password",
                json={'identity': self.email, 'password': self.password}
            )
            response.raise_for_status()
            self.token = response.json()['token']
            logger.info("Successfully logged in")
            return True
        except Exception as e:
            # Добавим вывод текста ответа при ошибке
            err_msg = f"Login failed: {str(e)}"
            if hasattr(e, 'response') and e.response is not None:
                err_msg += f" | Response: {e.response.text[:500]}"
            logger.error(err_msg)
            return False

    def load_all_games(self):
        """Загрузка всех игр с сервера"""
        logger.info("Loading all games from API")
        try:
            if not self.token:
                raise Exception("Not authenticated")
            headers = {'Authorization': self.token}
            all_games = []
            page = 1
            per_page = 200
            while True:
                response = requests.get(
                    f"{API_BASE_URL}/collections/games/records",
                    headers=headers,
                    params={'page': page, 'perPage': per_page, 'skipTotal': '1'} # skipTotal может ускорить запрос
                )
                response.raise_for_status()
                data = response.json()
                games_chunk = data.get('items', [])
                all_games.extend(games_chunk)
                # Корректное условие остановки для Pocketbase
                if not games_chunk or len(games_chunk) < per_page:
                    break
                page += 1
            self.games_cache = {game['title'].lower(): game for game in all_games}
            logger.info(f"Loaded {len(self.games_cache)} games")
            return True
        except Exception as e:
            err_msg = f"Error loading games: {str(e)}"
            if hasattr(e, 'response') and e.response is not None:
                err_msg += f" | Response: {e.response.text[:500]}"
            logger.error(err_msg)
            return False

    def find_game_by_title(self, title):
        """Поиск игры по названию"""
        title_lower = title.lower()
        if title_lower in self.games_cache:
            logger.info(f"Found game: {title} (ID: {self.games_cache[title_lower]['id']})")
            return self.games_cache[title_lower]
        logger.warning(f"Game not found: {title}")
        return None

    def capture_screenshot(self, url):
        """Запуск Puppeteer для захвата скриншота"""
        logger.info(f"Capturing screenshot for URL: {url}")
        try:
            if not os.path.exists(PUPPETEER_SCRIPT):
                raise FileNotFoundError(f"Puppeteer script not found: {PUPPETEER_SCRIPT}")

            os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
            # Используем encoding='utf-8' для корректного чтения вывода node.js
            result = subprocess.run(
                ["node", PUPPETEER_SCRIPT, url, "--pause"],
                capture_output=True,
                text=True,
                check=True,
                encoding='utf-8'
            )
            logger.debug(f"Puppeteer output: {result.stdout}") # Логируем весь вывод

            # --- Извлечение пути из вывода Puppeteer (улучшено, но без изменения оригинальной логики угадывания) ---
            screenshot_path_str = None
            output_lines = result.stdout.strip().splitlines()
            # Ищем последнюю строку, начинающуюся с "Screenshot saved:"
            saved_path_line = next((line for line in reversed(output_lines) if line.startswith("Screenshot saved:")), None)

            if saved_path_line:
                 # Извлекаем путь после "Screenshot saved: "
                 actual_path_str_from_log = saved_path_line.split("Screenshot saved:", 1)[1].strip()
                 actual_path = Path(actual_path_str_from_log)
                 if actual_path.exists():
                     logger.info(f"Screenshot path extracted from Puppeteer output: {actual_path}")
                     screenshot_path_str = str(actual_path) # Возвращаем строку
                 else:
                     # Если файл по пути из лога не найден, это ошибка
                     logger.error(f"Path found in Puppeteer output, but file does not exist: {actual_path}")
                     # НЕ используем fallback угадывание, если лог есть, но файл пропал
                     return None
            else:
                 # Если строка "Screenshot saved:" НЕ найдена, используем ОРИГИНАЛЬНУЮ логику угадывания имени
                 logger.warning("Could not find 'Screenshot saved:' in Puppeteer output. Falling back to original name guessing logic.")
                 # --- НАЧАЛО ОРИГИНАЛЬНОЙ ЛОГИКИ УГАДЫВАНИЯ ---
                 from urllib.parse import urlparse # Импорт здесь, т.к. нужен только в fallback
                 parsed_uri = urlparse(url)
                 # Оригинальная логика определения имени из URL
                 screenshot_name_part = parsed_uri.path.rstrip('/').split('/')[-1]
                 if not screenshot_name_part: # Если путь пустой или '/'
                     screenshot_name_part = parsed_uri.netloc.split('.')[0] # Берем первую часть хоста

                 # Строим путь как в оригинальном коде
                 screenshot_path_obj = Path(SCREENSHOTS_DIR) / f"{screenshot_name_part}.webp"
                 # --- КОНЕЦ ОРИГИНАЛЬНОЙ ЛОГИКИ УГАДЫВАНИЯ ---

                 if screenshot_path_obj.exists():
                     logger.info(f"Using guessed screenshot path: {screenshot_path_obj}")
                     screenshot_path_str = str(screenshot_path_obj)
                 else:
                     logger.error(f"Screenshot file not found using original guessing logic: {screenshot_path_obj}")
                     return None # Ошибка, если и угадывание не помогло

            return screenshot_path_str # Возвращаем строку пути

        except subprocess.CalledProcessError as e:
            logger.error(f"Puppeteer script failed with exit code {e.returncode}")
            # Логируем и stdout, и stderr для полной картины
            logger.error(f"Puppeteer stderr:\n{e.stderr}")
            logger.error(f"Puppeteer stdout:\n{e.stdout}")
            return None
        except FileNotFoundError as e: # Если node или сам скрипт не найден
            logger.error(f"File not found error during Puppeteer execution: {e}")
            return None
        except Exception as e:
            logger.error(f"Error capturing screenshot: {str(e)}", exc_info=True) # Добавляем traceback
            return None

    def replace_game_image(self, game_id, screenshot_path):
        """Замена изображения игры через API"""
        logger.info(f"Replacing image file for game ID: {game_id}") # Уточнено лог сообщение
        try:
            if not self.token:
                raise Exception("Not authenticated")
            headers = {'Authorization': self.token}

            screenshot_path_obj = Path(screenshot_path) # Используем Path для работы с файлом
            if not screenshot_path_obj.exists():
                # Используем FileNotFoundError для ясности
                raise FileNotFoundError(f"Screenshot file not found: {screenshot_path_obj}")

            mime_type = "image/webp"  # Предполагаем, что Puppeteer сохраняет в .webp
            if mime_type not in ALLOWED_MIME_TYPES:
                # Оставим эту проверку, хотя она может быть избыточной
                raise ValueError(f"Unsupported mime type: {mime_type}")

            # Используем 'with open' для гарантии закрытия файла
            with open(screenshot_path_obj, 'rb') as image_file:
                # Используем имя файла из Path объекта для корректной отправки multipart
                files = {'image': (screenshot_path_obj.name, image_file, mime_type)}
                response = requests.patch(
                    f"{API_BASE_URL}/collections/games/records/{game_id}",
                    headers=headers,
                    files=files
                )
            # Логируем статус и пытаемся получить тело ответа
            logger.debug(f"API response status for image replace: {response.status_code}")
            response_text = response.text[:500] # Ограничим длину для лога
            logger.debug(f"API response body preview: {response_text}...")
            response.raise_for_status() # Проверка на ошибки HTTP 4xx/5xx

            logger.info(f"Successfully replaced image file for game ID: {game_id}")
            return True
        # Явно ловим FileNotFoundError
        except FileNotFoundError as e:
             logger.error(f"Failed to replace image for game ID {game_id}: {e}")
             return False
        # Обработка ошибок requests
        except requests.exceptions.RequestException as e:
             logger.error(f"API error replacing image for game ID {game_id}: {e}")
             if e.response is not None:
                  logger.error(f"API Error details: Status={e.response.status_code}, Body={e.response.text[:500]}...")
             return False
        # Обработка прочих ошибок
        except Exception as e:
            logger.error(f"Unexpected error replacing image for game ID {game_id}: {str(e)}", exc_info=True)
            return False

    # --- Начало добавленного кода ---

    def _generate_base64_placeholder(self, image_path, game_id="N/A"):
        """Вспомогательная функция для генерации Base64 плейсхолдера."""
        img = None
        image_path_obj = Path(image_path)
        if not image_path_obj.exists():
             logger.error(f"[{game_id}] Image file not found for Base64 generation: {image_path_obj}")
             return None
        try:
            logger.info(f"[{game_id}] Generating Base64 placeholder from {image_path_obj.name}...")
            img = Image.open(image_path_obj)
            # Конвертация в RGB если необходимо (например, для GIF с палитрой или P mode)
            if img.mode in ('P', 'RGBA', 'LA'):
                 logger.debug(f"[{game_id}] Converting image mode from {img.mode} to RGB for Base64 generation.")
                 img = img.convert('RGB')
            elif img.mode != 'RGB':
                 logger.warning(f"[{game_id}] Image mode is {img.mode}. Attempting Base64 generation, but might fail if target format requires RGB.")

            img.thumbnail((PLACEHOLDER_TARGET_WIDTH, PLACEHOLDER_TARGET_HEIGHT), PLACEHOLDER_RESAMPLE_METHOD)
            buffer = BytesIO()
            # Сохраняем в буфер с заданными параметрами
            img.save(buffer, format=PLACEHOLDER_FORMAT, quality=PLACEHOLDER_QUALITY, lossless=PLACEHOLDER_LOSSLESS)
            buffer.seek(0)
            # Кодируем в Base64
            encoded_string = base64.b64encode(buffer.getvalue()).decode('utf-8')
            # Формируем data URI
            base64_data_uri = f"data:image/{PLACEHOLDER_FORMAT.lower()};base64,{encoded_string}"
            logger.info(f"[{game_id}] Base64 placeholder generated (length: {len(base64_data_uri)}).")
            return base64_data_uri
        except UnidentifiedImageError:
            logger.error(f"[{game_id}] Failed to identify image file for Base64 generation (PIL error): {image_path_obj.name}")
            return None
        except Exception as e:
            logger.error(f"[{game_id}] Error generating Base64 placeholder from {image_path_obj.name}: {e}", exc_info=True)
            return None
        finally:
            # Гарантированно закрываем объект изображения Pillow
            if img and hasattr(img, 'close'):
                try: img.close()
                except Exception as close_err: logger.warning(f"[{game_id}] Failed to close PIL image object: {close_err}")

    def _update_game_base64(self, game_id, base64_string):
        """Вспомогательная функция для обновления только поля image_base64."""
        logger.info(f"Updating Base64 placeholder for game ID: {game_id}")
        if not base64_string:
            logger.warning(f"[{game_id}] Attempted to update Base64 with an empty string. Aborting.")
            return False
        try:
            if not self.token:
                raise Exception("Not authenticated for Base64 update")
            # Заголовки для JSON запроса
            headers = {'Authorization': self.token, 'Content-Type': 'application/json'}
            # Тело запроса
            payload = {'image_base64': base64_string}

            response = requests.patch(
                f"{API_BASE_URL}/collections/games/records/{game_id}",
                headers=headers,
                json=payload # Отправляем данные как JSON
            )
            logger.debug(f"API response status for Base64 update: {response.status_code}")
            response_text = response.text[:500] # Ограничим для лога
            logger.debug(f"API response body preview: {response_text}...")
            response.raise_for_status() # Проверка на ошибки HTTP 4xx/5xx

            logger.info(f"Successfully updated Base64 placeholder for game ID: {game_id}")
            return True
        # Обработка ошибок requests
        except requests.exceptions.RequestException as e:
             logger.error(f"API error updating Base64 for game ID {game_id}: {e}")
             if e.response is not None:
                  logger.error(f"API Error details: Status={e.response.status_code}, Body={e.response.text[:500]}...")
             return False
        # Обработка прочих ошибок
        except Exception as e:
            logger.error(f"Unexpected error updating Base64 for game ID {game_id}: {str(e)}", exc_info=True)
            return False

    # --- Конец добавленного кода ---


    def process_game(self, game_title):
        """Основной процесс обработки игры"""
        # Поиск игры
        game = self.find_game_by_title(game_title)
        if not game:
            logger.error(f"Game '{game_title}' not found on server")
            return False

        game_id = game['id']
        iframe_url = game.get('iframe_url', '')

        # Проверяем, есть ли URL для захвата скриншота (используем get для безопасности)
        if not iframe_url or game.get('img_or_link') != 'link':
            # Добавим деталей в лог для ясности
            current_type = game.get('img_or_link', 'N/A')
            logger.error(f"Game '{game_title}' (ID: {game_id}) cannot be processed: img_or_link='{current_type}' (expected 'link'), iframe_url='{iframe_url}'")
            return False

        # Захватываем новый скриншот
        screenshot_path = self.capture_screenshot(iframe_url)
        if not screenshot_path:
            logger.error(f"Failed to capture screenshot for '{game_title}' (ID: {game_id})")
            return False

        # Заменяем изображение (основной файл)
        success = self.replace_game_image(game_id, screenshot_path)

        # --- Вызов добавленного функционала Base64 ---
        if success:
            logger.info(f"[{game_id}] Main image file updated. Attempting to generate and update Base64 placeholder...")
            # Генерируем Base64 из свежего скриншота
            base64_string = self._generate_base64_placeholder(screenshot_path, game_id)
            if base64_string:
                # Если генерация прошла успешно, обновляем на сервере
                base64_update_success = self._update_game_base64(game_id, base64_string)
                if not base64_update_success:
                    # Логируем ошибку обновления Base64, но не меняем общий статус `success`
                    logger.error(f"[{game_id}] Failed to update the Base64 placeholder on the server, although the main image was updated.")
            else:
                # Логируем ошибку генерации Base64
                logger.warning(f"[{game_id}] Failed to generate Base64 placeholder from the new screenshot. Base64 field was not updated.")
        else:
            logger.error(f"[{game_id}] Failed to update the main image file. Base64 generation and update will be skipped.")
        # --- Конец вызова ---

        if success:
            # Закомментировано удаление файла для сохранения скриншотов локально
            # try:
            #     os.remove(screenshot_path)
            #     logger.info(f"Cleaned up screenshot file: {screenshot_path}")
            # except Exception as e:
            #     logger.warning(f"Failed to remove screenshot file: {e}")
            logger.info(f"Screenshot retained at: {screenshot_path}")
            # Возвращаем True, если основная операция (замена файла) удалась
            return True
        else:
            # Возвращаем False, если основная операция не удалась
            return False

def main():
    # Используем argparse для более гибкой работы с аргументами
    parser = argparse.ArgumentParser(description='Replace game image and generate/update its Base64 placeholder on cyoa.cafe.')
    parser.add_argument('game_title', help='The title of the game to update.')
    # Сюда можно будет легко добавить флаги в будущем, например:
    # parser.add_argument('--skip-base64', action='store_true', help='Only replace the main image, skip Base64.')
    args = parser.parse_args()

    game_title = args.game_title
    logger.info(f"Starting image and Base64 update process for game: '{game_title}'")

    replacer = GameImageReplacer()

    # Логин
    if not replacer.login():
        logger.critical("Authentication failed. Please check EMAIL and PASSWORD in your .env file.")
        sys.exit(1)

    # Загрузка кэша игр (делаем один раз)
    if not replacer.load_all_games():
        logger.critical("Failed to load the list of games from the server.")
        sys.exit(1)

    # Обработка конкретной игры
    success = replacer.process_game(game_title)

    # Вывод итога в консоль
    if success:
        # Основная операция (замена файла) прошла успешно
        logger.info(f"Successfully processed '{game_title}'. Main image updated. Check logs for Base64 status.")
        print(f"Main image for '{game_title}' updated successfully. See logs for Base64 details.")
    else:
        # Основная операция не удалась
        logger.error(f"Failed to update the main image for '{game_title}'. Check logs/replace_game_image.log for details.")
        print(f"Error updating image for '{game_title}'. Check logs.")
        sys.exit(1)

if __name__ == "__main__":
    # Убедимся, что директория для логов существует перед запуском
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    main()