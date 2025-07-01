# components/project_downloader.py

import os
import re
import json
import logging
from urllib.parse import urljoin, urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from time import sleep
from bs4 import BeautifulSoup
from functools import lru_cache
from pathlib import Path
from email.utils import formatdate
from time import time
import chardet
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import threading
# from pathlib import Path # Убрал дублирующийся импорт pathlib
# import requests # Убрал дублирующийся импорт requests
# import logging # Убрал дублирующийся импорт logging

# Set up logging
log_file_path = os.path.join('logs', 'project_downloader.log')
logging.basicConfig(
    filename=log_file_path,
    level=logging.DEBUG,  # Установим DEBUG для более детального анализа
    format='%(asctime)s - %(levelname)s - %(message)s'
)

metadata_lock = threading.Lock()

# -------------------- Helper Functions -------------------- #

def detect_encoding(content):
    logging.debug("Detecting encoding for content.")
    result = chardet.detect(content)
    return result['encoding'] if result['encoding'] else 'utf-8'

@lru_cache(maxsize=1000)
def is_valid_url(url, base_domain):
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return False
    if parsed.scheme not in {'http', 'https'}:
        return False
    if parsed.netloc != base_domain:
        return False
    # Убрал излишне строгую проверку на символы, т.к. urlparse должен справляться
    # if re.search(r'[()<>{}\s\\]', parsed.path):
    #     return False
    return True # Упрощенная проверка

def extract_urls_from_css(css_content):
    urls = re.findall(r'url\((?:\'|"|)(.*?)(?:\'|"|)\)', css_content)
    return urls

def is_local_resource(src, base_url):
    if src.startswith('http://') or src.startswith('https://'):
        return urlparse(src).netloc == urlparse(base_url).netloc
    if src.startswith('//'):
        # Корректное сравнение для протокол-относительных URL
        return urlparse(f"http:{src}").netloc == urlparse(base_url).netloc
    # Пустые строки или data: не являются локальными ресурсами для скачивания
    if not src or src.startswith('data:'):
        return False
    return True # Все остальные относительные пути считаем локальными

def sanitize_folder_name(name):
    # Оставляем эту функцию как есть, controller.py ее не использует для папки игры
    return re.sub(r'[<>:"/\\|?*]', '_', name)

def get_game_name(url):
    # Оставляем эту функцию как есть, controller.py вычисляет имя сам
    parsed_url = urlparse(url)
    domain = parsed_url.netloc
    path = parsed_url.path.strip('/')
    if not path:
        return domain, ''
    path_parts = path.split('/')
    game_name = path_parts[-1] if path_parts else ''
    return domain, game_name

# --- ИЗМЕНЕНИЕ ТОЛЬКО ЗДЕСЬ ---
def enumerate_project_resources(data, directories=['images', 'music', 'videos', 'fonts', 'css', 'js', 'audio', 'assets', 'img']):
    """
    Рекурсивно обходит структуру данных (словарь или список) и извлекает строки,
    которые начинаются с одного из указанных префиксов директорий.
    Добавлен 'img' в список по умолчанию.
    """
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, str):
                for directory in directories:
                    # Проверяем, начинается ли строка с префикса папки + '/'
                    if value.startswith(f"{directory}/"):
                        yield value
                        break # Нашли совпадение, переходим к следующему значению
            elif isinstance(value, (dict, list)):
                # Рекурсивный вызов с тем же списком директорий
                yield from enumerate_project_resources(value, directories)
    elif isinstance(data, list):
        for item in data:
            # Рекурсивный вызов с тем же списком директорий
            yield from enumerate_project_resources(item, directories)
# --- КОНЕЦ ИЗМЕНЕНИЯ ---

# -------------------- Downloading Function -------------------- #

def create_session():
    session = requests.Session()
    retry_strategy = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
    )
    adapter = HTTPAdapter(
        max_retries=retry_strategy,
        pool_connections=100, # Значения из оригинала
        pool_maxsize=100,
        pool_block=False # Значение из оригинала
    )
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36', # User-Agent из оригинала
        'Accept': '*/*', # Accept из оригинала
        'Accept-Encoding': 'gzip, deflate', # Accept-Encoding из оригинала
        'Connection': 'keep-alive' # Connection из оригинала
    })
    return session

def download_file(url, path, session, base_domain, metadata_path, retries=3, delay=5, request_delay=0.1):
    """
    Скачивает файл и обновляет метаданные, полагаясь только на ETag для проверки актуальности.
    (Логика идентична оригинальной версии)
    """
    path = Path(path)
    metadata_path = Path(metadata_path)

    # Пропускаем специальные случаи (как в оригинале)
    if url.endswith('favicon.ico') or url.startswith('data:'):
        logging.debug(f"Skipping special URL: {url}")
        return True, False

    # Читаем существующие метаданные (как в оригинале)
    metadata = {}
    if metadata_path.exists():
        try:
            with metadata_path.open('r', encoding='utf-8') as f:
                metadata = json.load(f)
        except Exception as e:
            logging.warning(f"Could not load metadata from {metadata_path}: {e}")

    # Проверка актуальности по ETag (как в оригинале)
    if path.exists() and url in metadata:
        local_metadata = metadata.get(url, {})
        local_etag = local_metadata.get('ETag')
        logging.debug(f"Checking file: {url}, Local ETag: {local_etag}, File exists: {path.exists()}")

        if local_etag:
            try:
                headers = {'If-None-Match': local_etag}
                head = session.head(url, allow_redirects=True, timeout=15, headers=headers) # Таймаут из оригинала
                head.raise_for_status()

                if head.status_code == 304:
                    logging.debug(f"File up to date (304 Not Modified): {path}")
                    return True, False

                # Проверка ETag из HEAD ответа (как в оригинале)
                server_etag = head.headers.get('ETag')
                if server_etag == local_etag:
                    logging.debug(f"File matches by ETag: {path}")
                    return True, False
            except requests.RequestException as e:
                logging.warning(f"HEAD request failed for {url}: {e}, proceeding to download")
            # Добавил обработку других исключений при HEAD запросе
            except Exception as e:
                logging.warning(f"Non-request exception during HEAD for {url}: {e}, proceeding to download")


    # Скачивание файла (как в оригинале)
    try:
        path.parent.mkdir(parents=True, exist_ok=True) # Создаем родительские папки
        with session.get(url, stream=True, timeout=15) as response: # Таймаут из оригинала
            response.raise_for_status()
            content_type = response.headers.get('Content-Type', '')
            server_etag = response.headers.get('ETag')

            is_text_file = (
                path.suffix.lower() in {'.html', '.htm', '.js', '.css', '.json', '.txt', '.xml', '.svg'} or
                'text' in content_type or 'javascript' in content_type
            )
            if is_text_file:
                content = response.content
                encoding = detect_encoding(content)
                text = content.decode(encoding, errors='replace')
                path.write_text(text, encoding='utf-8')
            else:
                with path.open('wb') as f:
                    for chunk in response.iter_content(chunk_size=8192): # chunk_size из оригинала
                        if chunk:
                            f.write(chunk)

            # Обновляем метаданные с синхронизацией (как в оригинале)
            with metadata_lock:
                if metadata_path.exists():
                    try:
                        # Перезагружаем метаданные перед обновлением на случай параллельной записи
                        with metadata_path.open('r', encoding='utf-8') as f:
                            metadata = json.load(f)
                    except Exception:
                        logging.warning(f"Reloading metadata failed, using empty dict: {metadata_path}")
                        metadata = {} # Используем пустой словарь, если не удалось прочитать
                else:
                     metadata = {} # Если файла нет, начинаем с пустого словаря

                metadata[url] = {'ETag': server_etag} # Обновляем или добавляем запись
                metadata_path.parent.mkdir(parents=True, exist_ok=True) # Убедимся, что папка для метаданных есть
                with metadata_path.open('w', encoding='utf-8') as f:
                    json.dump(metadata, f, indent=2) # Сохраняем обновленные метаданные

            logging.debug(f"Downloaded and updated metadata: {url} -> {path}, Server ETag: {server_etag}")
            sleep(request_delay) # Задержка из оригинала
            return True, True
    except Exception as e:
        logging.error(f"Failed to download {url}: {e}")
        # Возвращаем False, если была любая ошибка при скачивании (как в оригинале)
        return False, False

def parse_html_for_resources(html_content, base_url, base_domain):
    """ Логика парсинга HTML идентична оригинальной версии """
    soup = BeautifulSoup(html_content, 'html.parser')
    resources = set()
    parsed_base = urlparse(base_url)
    # Важно: используем base_url напрямую для urljoin, как в оригинале
    # if not base_url.endswith('/'):
    #     base_url += '/' # Оригинал не добавлял слеш здесь

    tags = soup.find_all(['link', 'script', 'img', 'video', 'audio', 'source'])
    logging.debug(f"Found {len(tags)} tags with potential resources")

    for tag in tags:
        src = tag.get('href') or tag.get('src')
        if src:
            logging.debug(f"Processing resource: {src} from tag: {tag.name}")
            src = src.replace('\\', '/').strip() # Нормализация из оригинала
            # Проверяем, что ресурс локальный и не data: URI (как в оригинале)
            if is_local_resource(src, base_url):
                # Используем urljoin для корректного разрешения относительных и абсолютных путей (как в оригинале)
                full_url = urljoin(base_url, src)
                if is_valid_url(full_url, base_domain):
                    logging.debug(f"Adding resource: {full_url}")
                    resources.add(full_url)
                else:
                    logging.debug(f"Skipping invalid URL: {full_url}")
            else:
                 logging.debug(f"Skipping non-local/data URI resource: {src}")


    # Поиск в <style> (как в оригинале)
    for style_tag in soup.find_all('style'):
        css_content = style_tag.string
        if css_content:
            urls = extract_urls_from_css(css_content)
            for url in urls:
                url = url.replace('\\', '/').strip()
                if is_local_resource(url, base_url): # Проверяем локальность
                    full_url = urljoin(base_url, url)
                    if is_valid_url(full_url, base_domain):
                        resources.add(full_url)
                    else:
                         logging.debug(f"Skipping invalid URL from inline CSS: {full_url}")
                else:
                    logging.debug(f"Skipping non-local/data URI from inline CSS: {url}")


    # Поиск в style="..." (как в оригинале)
    for tag in soup.find_all(style=True):
        style_content = tag['style']
        urls = extract_urls_from_css(style_content)
        for url in urls:
            url = url.replace('\\', '/').strip()
            if is_local_resource(url, base_url): # Проверяем локальность
                full_url = urljoin(base_url, url)
                if is_valid_url(full_url, base_domain):
                    resources.add(full_url)
                else:
                    logging.debug(f"Skipping invalid URL from style attribute: {full_url}")
            else:
                logging.debug(f"Skipping non-local/data URI from style attribute: {url}")


    # Поиск в <script> (как в оригинале)
    embedded_scripts = soup.find_all('script')
    for script in embedded_scripts:
        if script.string:
            # Регулярное выражение из оригинала для поиска *.js
            js_urls = re.findall(r"""['"]([^'"]+?\.js(?:\?.*)?)['"]""", script.string)
            for js_url in js_urls:
                js_url = js_url.replace('\\', '/').strip()
                if is_local_resource(js_url, base_url): # Проверяем локальность
                    full_js_url = urljoin(base_url, js_url)
                    if is_valid_url(full_js_url, base_domain):
                        resources.add(full_js_url)
                    else:
                        logging.debug(f"Skipping invalid JS URL from inline script: {full_js_url}")
                else:
                    logging.debug(f"Skipping non-local/data URI JS URL from inline script: {js_url}")


    logging.debug(f"Total resources found: {len(resources)}")
    return resources

def parse_css_for_resources(css_content, base_url, base_domain):
    """ Логика парсинга CSS идентична оригинальной версии """
    resources = set()
    urls = extract_urls_from_css(css_content)
    for url in urls:
        url = url.replace('\\', '/').strip()
        # Проверяем локальность ДО urljoin, т.к. urljoin может сделать его абсолютным
        if is_local_resource(url, base_url):
            full_url = urljoin(base_url, url)
            if is_valid_url(full_url, base_domain):
                resources.add(full_url)
            else:
                logging.debug(f"Skipping invalid URL from CSS ({base_url}): {full_url}")
        else:
             logging.debug(f"Skipping non-local/data URI from CSS ({base_url}): {url}")

    return resources

def handle_resource(full_url, session, base_path, base_url_path, base_domain, metadata_path):
    """
    Обрабатывает ресурс. Логика определения пути и парсинга CSS идентична оригинальной.
    Возвращает только флаг успеха (bool).
    """
    logging.debug(f"Starting to handle resource: {full_url}")
    parsed_url = urlparse(full_url)
    path_from_url = parsed_url.path.lstrip('/') # Путь из URL ресурса

    # Определение относительного пути для сохранения (логика из оригинала)
    # base_url_path - это path от ИСХОДНОГО URL страницы (передается из crawl_and_download)
    base_url_path_clean = base_url_path.lstrip('/').rstrip('/')
    # Сравнение должно быть точным или с добавлением '/' для папок
    # path_from_url: /game/images/a.png
    # base_url_path_clean: game
    # path_from_url.startswith(base_url_path_clean + '/') -> True
    if base_url_path_clean and path_from_url.startswith(base_url_path_clean + '/'):
        relative_path = path_from_url[len(base_url_path_clean):].lstrip('/')
    else:
        # Если ресурс лежит вне базового пути (например, /assets/common.css),
        # сохраняем его путь как есть от корня.
        relative_path = path_from_url

    # Соединение базового пути сохранения и относительного пути ресурса (как в оригинале)
    # base_path: downloaded_games/domain/game
    # relative_path: images/a.png ИЛИ assets/common.css
    # os.path.join корректно их соединит
    file_path = os.path.join(base_path, relative_path)
    logging.debug(f"Resource {full_url} mapped to local path: '{file_path}'")

    # Проверка валидности URL (как в оригинале)
    if not is_valid_url(full_url, base_domain):
        logging.warning(f"Invalid or external URL skipped: {full_url}")
        return False # Возвращаем False для невалидных URL

    # Скачивание файла (как в оригинале)
    success, was_downloaded = download_file(full_url, file_path, session, base_domain, metadata_path)

    if not success:
        logging.error(f"Failed to download resource: {full_url}")
        return False # Возвращаем False при ошибке скачивания

    # Парсинг CSS для поиска вложенных ресурсов (как в оригинале)
    # Проверяем расширение файла после скачивания
    if file_path.lower().endswith('.css'):
        logging.debug(f"Resource is CSS, parsing for nested resources: {file_path}")
        try:
            # Используем pathlib для чтения, т.к. file_path уже строка
            css_path = Path(file_path)
            if css_path.exists(): # Убедимся, что файл существует
                 # Читаем байты для определения кодировки
                 css_raw_content = css_path.read_bytes()
                 css_encoding = detect_encoding(css_raw_content)
                 css_content = css_raw_content.decode(css_encoding, errors='replace')

                 # Передаем URL самого CSS файла как base_url для разрешения относительных путей внутри него
                 css_resources = parse_css_for_resources(css_content, full_url, base_domain)
                 logging.debug(f"Found {len(css_resources)} nested resources in CSS: {file_path}")
                 # Рекурсивно обрабатываем найденные ресурсы (как в оригинале)
                 # Важно: нужна защита от бесконечной рекурсии, если CSS ссылается сам на себя
                 # Оригинал не имел явной защиты, но ThreadPoolExecutor мог косвенно помогать
                 # Для простоты пока оставим как есть, но это потенциальная проблема
                 for css_res_url in css_resources:
                      # Рекурсивный вызов для обработки ресурсов из CSS
                      # Передаем те же base_path, base_url_path и т.д.
                      handle_resource(css_res_url, session, base_path, base_url_path, base_domain, metadata_path)
            else:
                 logging.warning(f"CSS file path not found after download for parsing: {file_path}")

        except Exception as e:
            logging.error(f"Error parsing CSS file {file_path} from URL {full_url}: {e}")
            # Не возвращаем False здесь, т.к. основной файл скачался

    return success # Возвращаем успех скачивания основного файла

def crawl_and_download(url, base_path, session=None, max_workers=5):
    """ Логика обхода и загрузки идентична оригинальной версии """
    if session is None:
        session = create_session()

    base_path = Path(base_path) # Используем Path для удобства создания папок
    base_path.mkdir(parents=True, exist_ok=True) # Создаем базовую папку, если ее нет
    metadata_path = base_path / 'metadata.json'

    parsed_base = urlparse(url)
    base_domain = parsed_base.netloc
    # Определяем base_url для разрешения относительных ссылок (как в оригинале)
    base_url_for_links = url # Используем исходный URL как базу для urljoin
    # Определяем base_url_path для функции handle_resource (как в оригинале)
    base_url_path = parsed_base.path # Путь из исходного URL

    logging.info(f"Starting crawl for URL: {url}")
    logging.info(f"Saving files to: {base_path}")

    # Определяем путь к index.html относительно base_path (как в оригинале)
    # Считаем, что controller.py передает путь к ПАПКЕ игры
    index_filename = "index.html"
    index_path = base_path / index_filename

    # Скачиваем index.html (как в оригинале)
    index_success, index_downloaded = download_file(
        url, index_path, session, base_domain, metadata_path
    )
    if not index_success:
        logging.error(f"Failed to download index.html for {url}")
        # Возвращаем 0, 0, 1 (1 провал), как в оригинале (?)
        # Оригинал возвращал 0, 0, 0 - исправим на 1 провал
        return 0, 0, 1

    # Парсим скачанный index.html (как в оригинале)
    resources = set()
    if index_path.exists():
        raw_content = index_path.read_bytes()
        encoding = detect_encoding(raw_content)
        try:
            html_content = raw_content.decode(encoding, errors='replace')
            # Передаем base_url_for_links (исходный URL) для разрешения ссылок
            html_resources = parse_html_for_resources(
                html_content,
                base_url_for_links,
                base_domain
            )
            resources.update(html_resources)
        except Exception as e:
            logging.error(f"Error decoding or parsing content from {index_path}: {e}")

    # Скачиваем и парсим project.json (как в оригинале)
    project_json_relative_path = 'project.json'
    # Собираем URL к project.json относительно исходного URL
    project_json_url = urljoin(base_url_for_links, project_json_relative_path)
    # Путь для сохранения project.json внутри base_path
    project_json_path = base_path / project_json_relative_path

    project_json_success, project_json_downloaded = download_file(
        project_json_url,
        project_json_path,
        session,
        base_domain,
        metadata_path
    )

    if project_json_success and project_json_path.exists():
        logging.debug(f"Successfully downloaded or verified project.json from {project_json_url}")
        try:
            project_data = json.loads(project_json_path.read_text(encoding='utf-8'))
            # Используем функцию с обновленным списком папок (включая 'img')
            project_resources_relative = list(enumerate_project_resources(project_data))
            logging.debug(f"Found {len(project_resources_relative)} resource paths in project.json")
            for res_rel in project_resources_relative:
                # Собираем полный URL ресурса из project.json относительно исходного URL
                full_res_url = urljoin(base_url_for_links, res_rel)
                if is_valid_url(full_res_url, base_domain):
                    resources.add(full_res_url)
                    logging.debug(f"Added resource from project.json: {full_res_url}")
        except json.JSONDecodeError:
            logging.error(f"Error decoding project.json from {project_json_url}")
        except Exception as e:
            logging.error(f"Unexpected error processing project.json from {project_json_url}: {e}")
    else:
        logging.warning(f"Could not download or find project.json at {project_json_url}")


    # Статистика (как в оригинале)
    completed = 1 if index_success else 0 # index.html обработан
    downloaded = 1 if index_downloaded else 0 # index.html скачан
    failed = 0 if index_success else 1 # index.html провален

    # Учитываем project.json в статистике (как в оригинале)
    if project_json_success:
        # completed += 1 # Оригинал не увеличивал completed
        if project_json_downloaded:
            downloaded += 1
    # else: # Оригинал не увеличивал failed для project.json
    #     failed += 1


    logging.debug(f"Starting download pool for {len(resources)} resources found in HTML/JSON")
    # Запуск загрузки в потоках (как в оригинале)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Создаем задачи для каждого ресурса
        future_to_resource = {
            executor.submit(
                handle_resource,
                res_url,
                session,
                str(base_path), # Передаем base_path как строку для os.path.join
                base_url_path, # Передаем путь исходного URL
                base_domain,
                metadata_path
            ): res_url for res_url in resources
        }

        # Собираем результаты по мере завершения (как в оригинале)
        for future in as_completed(future_to_resource):
            res_url = future_to_resource[future]
            try:
                success = future.result() # Получаем результат handle_resource (True/False)
                completed += 1 # Считаем каждую завершенную задачу
                if success:
                    # Считаем +1 к downloaded, если handle_resource вернул True
                    # Это не точно отражает скачивание (мог быть 304), но соответствует логике оригинала
                    downloaded += 1
                else:
                    failed += 1 # Увеличиваем failed, если handle_resource вернул False
                logging.debug(f"Resource {res_url} processing completed. Success: {success}")
            except Exception as e:
                failed += 1 # Считаем провалом при любом исключении
                logging.error(f"Exception processing resource {res_url}: {e}")

    # Логирование и возврат статистики (как в оригинале)
    logging.info(f"Download completed. Successfully processed: {completed}, Downloaded/Up-to-date: {downloaded}, Failed: {failed}")
    return completed, downloaded, failed # Возвращаем статистику

if __name__ == "__main__":
    # Блок запуска из командной строки оставлен без изменений от оригинала
    import sys
    if len(sys.argv) != 2:
        print("Usage: python project_downloader.py <url>")
        sys.exit(1)
    url = sys.argv[1]
    # Определение base_path как в оригинале (предполагает, что URL оканчивается на /folder/)
    # Эта логика может отличаться от той, что в controller.py
    try:
         output_folder_name = url.split('/')[-2] # Может вызвать IndexError, если URL не имеет нужной структуры
    except IndexError:
         output_folder_name = urlparse(url).netloc # Запасной вариант - имя домена
         logging.warning(f"Could not determine folder name from URL path, using domain: {output_folder_name}")

    # Создаем папку downloaded_games, если ее нет
    base_download_dir = "downloaded_games"
    os.makedirs(base_download_dir, exist_ok=True)

    base_path = os.path.join(base_download_dir, output_folder_name)

    # Очищаем лог перед запуском, если нужно
    # if os.path.exists(log_file_path):
    #     open(log_file_path, 'w').close()

    print(f"Starting download for URL: {url}")
    print(f"Saving files to: {base_path}")

    start_time = time()
    completed, downloaded, failed = crawl_and_download(url, base_path)
    end_time = time()

    print("\n--- Download Summary ---")
    print(f"URL: {url}")
    print(f"Saved to: {base_path}")
    print(f"Processing Time: {end_time - start_time:.2f} seconds")
    # Выводим статистику в терминах оригинала
    print(f"Total resources processed (attempts): {completed}")
    print(f"Resources downloaded or up-to-date: {downloaded}")
    print(f"Resources failed to download: {failed}")
    print(f"Detailed logs available at: {log_file_path}")