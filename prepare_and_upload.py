# prepare_and_upload.py

import os
import shutil
import subprocess
import sys
import json
import re # Нужен для удаления висячих запятых
from pathlib import Path
import logging
import traceback

# --- (Настройка логирования без изменений) ---
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
    handlers=[
        logging.FileHandler("logs/prepare_and_upload.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# --- (Константы без изменений) ---
CATALOG_JSON_DIR = "catalog_json"
SCREENSHOTS_DIR = "screenshots"
NEW_GAMES_DIR = "New_Games"
PROCESSED_GAMES_DIR = "Processed_Games"
GAME_UPLOADER_SCRIPT = "GameUploader.py"

logger.info("--- Prepare_and_upload.py script started ---")
logger.info(f"Current Working Directory: {os.getcwd()}")

# --- Функции очистки JSON (добавляем удаление висячих запятых) ---
def remove_json_comments(json_text):
    # ... (код функции без изменений) ...
    lines = json_text.splitlines(); cleaned_lines = []; in_string = False
    for line in lines:
        cleaned_line = ""; i = 0
        while i < len(line):
            char = line[i]
            if char == '"' and (i == 0 or line[i-1] != '\\'): in_string = not in_string; cleaned_line += char
            elif not in_string and i + 1 < len(line) and char == '/' and line[i+1] == '/': break
            else: cleaned_line += char
            i += 1
        if cleaned_line.strip(): cleaned_lines.append(cleaned_line)
    return '\n'.join(cleaned_lines)

def strip_markdown_wrappers(json_text):
    # ... (код функции без изменений) ...
    lines = json_text.splitlines(); cleaned_lines = []
    for line in lines:
        stripped_line = line.strip()
        if stripped_line == "```json" or stripped_line == "```": continue
        cleaned_lines.append(line)
    return '\n'.join(cleaned_lines)

def remove_trailing_commas(json_text):
    """Attempt to remove trailing commas before closing braces/brackets."""
    # Убираем запятые перед } и ] с возможными пробелами между ними
    cleaned_text = re.sub(r',\s*(\}|\])', r'\1', json_text)
    return cleaned_text

def validate_and_clean_json(json_path):
    """Validate and clean JSON, return original and cleaned text."""
    logger.info(f"Processing JSON file: {json_path}")
    absolute_json_path = os.path.abspath(json_path)
    logger.info(f"Absolute path: {absolute_json_path}")
    if not os.path.exists(json_path):
        logger.error(f"JSON file not found at: {json_path}")
        return None, None
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            original_content = f.read()
        logger.debug(f"Read original content (first 500 chars):\n{original_content[:500]}...")

        logger.debug("Stripping markdown wrappers...")
        content_no_markdown = strip_markdown_wrappers(original_content)
        logger.debug(f"After markdown strip (first 500 chars):\n{content_no_markdown[:500]}...")

        logger.debug("Removing comments...")
        content_no_comments = remove_json_comments(content_no_markdown)
        logger.debug(f"After comment removal (first 500 chars):\n{content_no_comments[:500]}...")

        # --- НОВЫЙ ШАГ: Удаление висячих запятых ---
        logger.debug("Attempting to remove trailing commas...")
        content_no_trailing_commas = remove_trailing_commas(content_no_comments)
        if content_no_trailing_commas != content_no_comments:
            logger.info("Trailing commas potentially removed.") # Лог, если что-то заменилось
            logger.debug(f"After trailing comma removal (first 500 chars):\n{content_no_trailing_commas[:500]}...")
        else:
             logger.debug("No trailing commas found or removed by regex.")
        # ------------------------------------------

        # Финальная валидация
        final_cleaned_content = content_no_trailing_commas
        try:
            json.loads(final_cleaned_content) # Проверяем финальный результат
            logger.info(f"JSON validation successful after ALL cleaning steps: {json_path}")
            return original_content, final_cleaned_content # Возвращаем ОРИГИНАЛ и ПОЛНОСТЬЮ ОЧИЩЕННЫЙ
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON structure in {json_path} EVEN AFTER ALL CLEANING: {e}")
            logger.error(f"Problematic section (approx.): ...{final_cleaned_content[max(0, e.pos-40):e.pos+40]}...")
            return None, None # Очистка не помогла

    except Exception as e:
        logger.error(f"Unexpected error processing JSON file {json_path}: {e}", exc_info=True)
        return None, None

# --- (load_base64_image без изменений) ---
def load_base64_image(project_name):
    """Load base64 image string from file if it exists."""
    base64_path = os.path.join(SCREENSHOTS_DIR, f"{project_name}_base64.txt")
    logger.debug(f"Looking for base64 image at: {base64_path}")
    if os.path.exists(base64_path):
        try:
            with open(base64_path, 'r', encoding='utf-8') as f:
                base64_string = f.read().strip()
            logger.info(f"Loaded base64 image from: {base64_path}")
            return base64_string
        except Exception as e:
            logger.error(f"Error loading base64 image {base64_path}: {e}")
            return None
    else:
        logger.warning(f"Base64 image file not found: {base64_path}")
        return None

# --- prepare_game_files (Исправлено возвращаемое значение) ---
def prepare_game_files(test_mode=False):
    logger.info(f"--- Starting file preparation (test_mode={test_mode}) ---")
    catalog_dir_abs = os.path.abspath(CATALOG_JSON_DIR)
    logger.info(f"Checking for JSON files in directory: {CATALOG_JSON_DIR} (Absolute: {catalog_dir_abs})")

    if not os.path.exists(CATALOG_JSON_DIR) or not os.path.isdir(CATALOG_JSON_DIR):
        logger.error(f"Source directory not found: {CATALOG_JSON_DIR}")
        return False, [] # <-- Возвращаем кортеж

    try:
        json_files = [f for f in os.listdir(CATALOG_JSON_DIR) if f.endswith(".json")]
    except Exception as e:
        logger.error(f"Error listing files in {CATALOG_JSON_DIR}: {e}", exc_info=True)
        return False, [] # <-- Возвращаем кортеж

    if not json_files:
        logger.warning(f"No JSON files found in {CATALOG_JSON_DIR}. Nothing to prepare.")
        return True, [] # <-- Возвращаем кортеж (успех, т.к. нечего делать)

    logger.info(f"Found {len(json_files)} JSON files to process: {json_files}")
    os.makedirs(NEW_GAMES_DIR, exist_ok=True)
    logger.info(f"Ensured destination directory exists: {NEW_GAMES_DIR}")

    success_count = 0
    processed_files = []

    for json_file in json_files:
        logger.info(f"Processing file: {json_file}")
        try:
            project_name = os.path.splitext(json_file)[0]
            json_src = os.path.join(CATALOG_JSON_DIR, json_file)
            screenshot_src = os.path.join(SCREENSHOTS_DIR, f"{project_name}.webp")
            json_dest = os.path.join(NEW_GAMES_DIR, json_file)
            json_with_comments_dest = os.path.join(NEW_GAMES_DIR, f"{project_name}_with_comments.json")
            screenshot_dest = os.path.join(NEW_GAMES_DIR, f"{project_name}.webp")

            original_json, cleaned_json_str = validate_and_clean_json(json_src)
            if cleaned_json_str is None:
                logger.warning(f"Skipping '{json_file}' due to invalid/uncleanable JSON content.")
                continue

            game_data = json.loads(cleaned_json_str)
            base64_image = load_base64_image(project_name)
            if base64_image:
                game_data['image_base64'] = base64_image
                logger.info(f"Added base64 image to data for '{project_name}'")

            logger.debug(f"Saving cleaned+modified JSON to: {json_dest}")
            with open(json_dest, 'w', encoding='utf-8') as f:
                json.dump(game_data, f, ensure_ascii=False, indent=2)

            logger.debug(f"Saving original JSON with comments to: {json_with_comments_dest}")
            with open(json_with_comments_dest, 'w', encoding='utf-8') as f:
                f.write(original_json)

            if os.path.exists(screenshot_src):
                logger.debug(f"Copying screenshot from {screenshot_src} to {screenshot_dest}")
                shutil.copy2(screenshot_src, screenshot_dest)
                logger.info(f"Copied screenshot for '{project_name}'")
            else:
                logger.warning(f"Screenshot not found, not copied: {screenshot_src}")

            logger.info(f"Successfully prepared files for: {json_file}")
            success_count += 1
            processed_files.append(json_src)

        except Exception as e:
            logger.error(f"Unexpected error preparing files for '{json_file}': {e}", exc_info=True)
            continue

    if success_count == 0 and len(json_files) > 0:
        logger.error("No files were successfully prepared, though source files existed.")
        return False, [] # <-- Возвращаем кортеж
    elif success_count > 0:
         logger.info(f"Successfully prepared {success_count} out of {len(json_files)} games.")
         return True, processed_files # <-- Возвращаем кортеж
    else: # json_files был пуст
         logger.info("No source JSON files to prepare.")
         return True, [] # <-- Возвращаем кортеж


# --- (run_game_uploader, cleanup_processed_files, move_comments_files_to_processed - без изменений) ---
def run_game_uploader():  
    """Run GameUploader.py."""
    logger.info(f"Attempting to run script: {GAME_UPLOADER_SCRIPT}")
    if not os.path.exists(GAME_UPLOADER_SCRIPT):
        logger.error(f"Upload script not found: {GAME_UPLOADER_SCRIPT}")
        return False

    try:
        logger.info("--- Starting GameUploader.py subprocess ---")
        # Используем тот же метод запуска, что и в controller.py для консистентности
        process = subprocess.Popen(
            [sys.executable, GAME_UPLOADER_SCRIPT],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8' # Укажем кодировку
        )

        stdout_lines = []
        stderr_lines = []

        # Читаем вывод по мере поступления (неблокирующее чтение может быть сложным)
        # Используем communicate для простоты, но он ждет завершения
        stdout, stderr = process.communicate()

        logger.info("--- GameUploader.py subprocess finished ---")
        logger.info(f"Return Code: {process.returncode}")
        if stdout:
             logger.info(f"GameUploader STDOUT:\n{stdout.strip()}")
        if stderr:
             logger.warning(f"GameUploader STDERR:\n{stderr.strip()}") # Логируем stderr как warning

        if process.returncode != 0:
            logger.error(f"GameUploader.py failed with exit code {process.returncode}")
            return False

        logger.info("GameUploader.py completed successfully (return code 0).")
        return True

    except Exception as e:
        logger.error(f"Unexpected error running GameUploader.py: {e}", exc_info=True)
        return False
def cleanup_processed_files(processed_json_sources):
    """Remove successfully processed files from catalog_json."""
    logger.info(f"--- Starting cleanup of processed source files ---")
    if not processed_json_sources:
        logger.info("No processed files list provided, skipping cleanup.")
        return

    logger.info(f"Attempting to remove {len(processed_json_sources)} files from {CATALOG_JSON_DIR}")
    for file_path in processed_json_sources:
        try:
            if os.path.isfile(file_path):
                os.remove(file_path)
                logger.info(f"Removed processed file: {file_path}")
            else:
                 logger.warning(f"Tried to remove non-file or missing file: {file_path}")
        except Exception as e:
            logger.error(f"Error removing processed file {file_path}: {e}", exc_info=True)
    logger.info("--- Cleanup finished ---")


def move_comments_files_to_processed():
    """Move files with comments from New_Games to Processed_Games."""
    logger.info(f"--- Moving files with comments to {PROCESSED_GAMES_DIR} ---")
    os.makedirs(PROCESSED_GAMES_DIR, exist_ok=True)
    moved_count = 0
    try:
        for file in os.listdir(NEW_GAMES_DIR):
            if file.endswith("_with_comments.json"):
                src = os.path.join(NEW_GAMES_DIR, file)
                dest = os.path.join(PROCESSED_GAMES_DIR, file)
                try:
                    shutil.move(src, dest)
                    logger.info(f"Moved {file} to {PROCESSED_GAMES_DIR}")
                    moved_count += 1
                except Exception as e:
                    logger.error(f"Error moving file {src} to {dest}: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Error listing files in {NEW_GAMES_DIR} for moving comments: {e}", exc_info=True)
    logger.info(f"Moved {moved_count} files with comments.")
    logger.info(f"--- Finished moving comments files ---")

# --- main (без изменений в логике, но теперь распаковка кортежа сработает) ---
def main():
    logger.info("=== Prepare and Upload Process Starting ===")
    processed_files_list = [] # Инициализация
    try:
        test_mode = "--test" in sys.argv
        logger.info(f"Running in {'test' if test_mode else 'live'} mode")

        # Теперь распаковка будет работать всегда, т.к. prepare_game_files возвращает кортеж
        prepare_success, processed_files_list = prepare_game_files(test_mode)

        if not prepare_success:
            logger.error("Failed to prepare game files (check logs above). Aborting.")
            sys.exit(1) # Выход с ошибкой

        # Проверяем, были ли файлы для обработки и удалось ли их обработать
        if not processed_files_list:
             # Проверяем, были ли вообще исходные файлы
             source_files_existed = False
             if os.path.exists(CATALOG_JSON_DIR) and os.path.isdir(CATALOG_JSON_DIR):
                 try:
                      if any(f.endswith(".json") for f in os.listdir(CATALOG_JSON_DIR)):
                           source_files_existed = True
                 except Exception:
                      pass # Ошибки чтения директории уже залогированы

             if source_files_existed:
                 logger.error("Source JSON files existed, but none were successfully prepared (likely all invalid). Aborting.")
                 sys.exit(1)
             else:
                 logger.info("No source JSON files found to process. Exiting successfully.")
                 sys.exit(0) # Успешный выход, если файлов не было

        # Если дошли сюда, значит prepare_success == True и processed_files_list не пуст

        if not test_mode:
            logger.info("--- Starting game upload process ---")
            upload_success = run_game_uploader()
            if not upload_success:
                logger.error("GameUploader failed. Aborting upload process. Files remain in New_Games.")
                sys.exit(1)
            logger.info("--- Game uploading completed successfully ---")

            move_comments_files_to_processed()
            cleanup_processed_files(processed_files_list)

        else:
            logger.info("Test mode: Skipping upload, comments moving, and cleanup.")
            logger.info("Prepared files are available in 'New_Games' directory for inspection.")

        logger.info("=== Prepare and Upload Process Finished Successfully ===")
        sys.exit(0)

    except Exception as e:
        logger.critical(f"CRITICAL UNHANDLED ERROR in prepare_and_upload main: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()