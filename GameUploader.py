# GameUploader.py

import os
import json
import glob
from dotenv import load_dotenv
import requests
from pathlib import Path
import mimetypes
import sys
import shutil
import time
import logging
import base64

load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("logs/game_uploader.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

ALLOWED_IMAGE_MIME_TYPES = [
    'image/png', 'image/jpeg', 'image/gif', 'image/webp', 'image/avif', 'image/svg+xml'
]

EXTENSION_TO_MIME = {
    '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
    '.gif': 'image/gif', '.webp': 'image/webp', '.avif': 'image/avif', '.svg': 'image/svg+xml'
}

class AuthorManager:
    def __init__(self, base_url, token):
        self.base_url = base_url
        self.token = token
        self.authors_cache = {}
        logger.info("AuthorManager initialized")

    def load_authors(self):
        logger.info("Loading existing authors from API")
        try:
            if not self.token:
                raise Exception("Not authenticated")
            headers = {'Authorization': self.token}
            all_authors = []
            page = 1
            per_page = 200
            while True:
                response = requests.get(
                    f'{self.base_url}/collections/authors/records',
                    headers=headers,
                    params={'page': page, 'perPage': per_page}
                )
                response.raise_for_status()
                data = response.json()
                authors_chunk = data.get('items', [])
                all_authors.extend(authors_chunk)
                if len(authors_chunk) < per_page:
                    break
                page += 1
            logger.info(f'Downloaded {len(all_authors)} existing authors')
            for author in all_authors:
                self.authors_cache[author['name'].lower()] = author['id']
            return all_authors
        except Exception as e:
            logger.error(f'Error getting existing authors: {e}')
            return []

    def create_author(self, name, description=""):
        logger.info(f"Creating new author: {name}")
        try:
            if not self.token:
                raise Exception("Not authenticated")
            headers = {'Authorization': self.token}
            response = requests.post(
                f'{self.base_url}/collections/authors/records',
                headers=headers,
                json={'name': name, 'description': description}
            )
            response.raise_for_status()
            author_data = response.json()
            logger.info(f'Created author: {name} with ID: {author_data["id"]}')
            self.authors_cache[name.lower()] = author_data["id"]
            return author_data["id"]
        except Exception as e:
            logger.error(f'Error creating author "{name}": {e}')
            return None

    def get_or_create_author(self, name, description=""):
        # Поддержка списка авторов: обрабатываем только одного автора здесь
        if isinstance(name, list):
            logger.warning("get_or_create_author received a list; use get_or_create_authors for multiple authors")
            if not name:
                return None
            name = name[0]  # Для обратной совместимости берём первого
        name_lower = name.lower()
        if name_lower in self.authors_cache:
            logger.info(f"Found existing author: {name} (ID: {self.authors_cache[name_lower]})")
            return self.authors_cache[name_lower]
        return self.create_author(name, description)

    def get_or_create_authors(self, authors, description=""):
        """Обрабатывает список авторов и возвращает их ID."""
        if not isinstance(authors, list):
            authors = [authors]  # Преобразуем строку в список из одного элемента
        author_ids = []
        for name in authors:
            if not name:
                logger.warning("Empty author name encountered, skipping")
                continue
            name_lower = name.lower()
            if name_lower in self.authors_cache:
                logger.info(f"Found existing author: {name} (ID: {self.authors_cache[name_lower]})")
                author_ids.append(self.authors_cache[name_lower])
            else:
                author_id = self.create_author(name, description)
                if author_id:
                    author_ids.append(author_id)
        return author_ids

class TagManager:
    def __init__(self):
        self.base_url = 'https://cyoa.cafe/api'
        self.email = os.getenv('EMAIL')
        self.password = os.getenv('PASSWORD')
        self.token = None
        self.category_id = "phc2n4pqe7hxe36"
        self.existing_tags = {}
        logger.info("TagManager initialized")

    def login(self):
        logger.info("Attempting TagManager login")
        try:
            response = requests.post(
                f'{self.base_url}/collections/users/auth-with-password',
                json={'identity': self.email, 'password': self.password}
            )
            response.raise_for_status()
            data = response.json()
            self.token = data['token']
            logger.info('TagManager successfully logged in')
            return True
        except Exception as e:
            logger.error(f'TagManager login error: {e}')
            return False

    def get_all_tags(self):
        logger.info("Loading all existing tags")
        try:
            if not self.token:
                raise Exception("Not authenticated")
            headers = {'Authorization': self.token}
            all_tags = []
            page = 1
            per_page = 200
            while True:
                response = requests.get(
                    f'{self.base_url}/collections/tags/records',
                    headers=headers,
                    params={'page': page, 'perPage': per_page}
                )
                response.raise_for_status()
                data = response.json()
                tags_chunk = data.get('items', [])
                all_tags.extend(tags_chunk)
                if len(tags_chunk) < per_page:
                    break
                page += 1
            logger.info(f'Downloaded {len(all_tags)} existing tags')
            self.existing_tags = {}
            for tag in all_tags:
                tag_name_lower = tag['name'].lower()
                self.existing_tags[tag_name_lower] = {
                    'id': tag['id'], 'name': tag['name'], 'description': tag.get('description', '')
                }
            return all_tags
        except Exception as e:
            logger.error(f'Error getting existing tags: {e}')
            return []

    def create_tag(self, name, description=""):
        logger.info(f"Creating new tag: {name}")
        try:
            if not self.token:
                raise Exception("Not authenticated")
            headers = {'Authorization': self.token}
            response = requests.post(
                f'{self.base_url}/collections/tags/records',
                headers=headers,
                json={'name': name, 'description': description}
            )
            response.raise_for_status()
            tag_data = response.json()
            logger.info(f'Created tag: {name} with ID: {tag_data["id"]}')
            self.existing_tags[name.lower()] = {
                'id': tag_data["id"], 'name': name, 'description': description
            }
            self.add_tag_to_category(tag_data["id"])
            return tag_data["id"]
        except Exception as e:
            logger.error(f'Error creating tag "{name}": {e}')
            return None

    def add_tag_to_category(self, tag_id):
        logger.info(f"Adding tag {tag_id} to category Custom")
        try:
            if not self.token:
                raise Exception("Not authenticated")
            headers = {'Authorization': self.token}
            response = requests.get(
                f'{self.base_url}/collections/tag_categories/records/{self.category_id}',
                headers=headers
            )
            response.raise_for_status()
            category_data = response.json()
            current_tags = category_data.get('tags', [])
            if tag_id not in current_tags:
                current_tags.append(tag_id)
                response = requests.patch(
                    f'{self.base_url}/collections/tag_categories/records/{self.category_id}',
                    headers=headers,
                    json={'tags': current_tags}
                )
                response.raise_for_status()
                logger.info(f'Added tag {tag_id} to category Custom')
                return True
            else:
                logger.info(f'Tag {tag_id} already in category Custom')
                return True
        except Exception as e:
            logger.error(f'Error adding tag {tag_id} to category: {e}')
            return False

    def get_or_create_tag(self, tag_name):
        tag_name_lower = tag_name.lower()
        if tag_name_lower in self.existing_tags:
            logger.info(f"Found existing tag: {tag_name} (ID: {self.existing_tags[tag_name_lower]['id']})")
            return self.existing_tags[tag_name_lower]['id']
        return self.create_tag(tag_name)

class GameUploader:
    def __init__(self):
        self.base_url = 'https://cyoa.cafe/api'
        self.email = os.getenv('EMAIL')
        self.password = os.getenv('PASSWORD')
        self.token = None
        self.tag_manager = TagManager()
        self.author_manager = None
        self.request_delay = 3
        logger.info("GameUploader initialized")

    def login(self):
        logger.info("Attempting to login")
        try:
            response = requests.post(
                f'{self.base_url}/collections/users/auth-with-password',
                json={'identity': self.email, 'password': self.password}
            )
            response.raise_for_status()
            data = response.json()
            self.token = data['token']
            logger.info("Successfully logged in")
            self.tag_manager.login()
            self.tag_manager.get_all_tags()
            logger.info(f"Loaded {len(self.tag_manager.existing_tags)} tags into cache")
            self.author_manager = AuthorManager(self.base_url, self.token)
            self.author_manager.load_authors()
            logger.info(f"Loaded {len(self.author_manager.authors_cache)} authors into cache")
            return data
        except Exception as e:
            logger.error(f'Login failed: {str(e)}')
            return None

    def create_game(self, game_data):
        game_data['img_or_link'] = game_data['img_or_link'].lower()
        logger.info(f"Creating game: {game_data['title']}")
        try:
            if not self.token:
                raise Exception("Not authenticated")
            headers = {'Authorization': self.token}
            image_path = Path(game_data['image'])
            if not image_path.exists():
                raise FileNotFoundError(f"Cover image not found: {image_path}")

            file_ext = image_path.suffix.lower()
            mime_type = EXTENSION_TO_MIME.get(file_ext, mimetypes.guess_type(str(image_path))[0])
            if mime_type not in ALLOWED_IMAGE_MIME_TYPES:
                raise ValueError(f"Unsupported image format: {mime_type}")

            tag_ids = []
            if game_data.get('tags'):
                for tag_name in game_data['tags']:
                    tag_id = self.tag_manager.get_or_create_tag(tag_name)
                    if tag_id:
                        tag_ids.append(tag_id)
                    else:
                        logger.warning(f"Failed to get or create tag '{tag_name}'")

            # Получаем список ID авторов
            author_ids = []
            if 'author' in game_data:
                author_ids = self.author_manager.get_or_create_authors(game_data['author'])
                logger.info(f"Authors for game: {game_data['author']} (IDs: {author_ids})")

            form_data = [
                ('title', game_data['title']),
                ('description', game_data['description']),
                ('img_or_link', game_data['img_or_link']),
                ('uploader', game_data['uploader']),
            ]

            # Добавляем image_base64, если присутствует
            if 'image_base64' in game_data:
                logger.info(f"Using image_base64 for {game_data['title']}")
                form_data.append(('image_base64', game_data['image_base64']))

            if game_data['img_or_link'] == 'link' and game_data.get('iframe_url'):
                form_data.append(('iframe_url', game_data['iframe_url']))
            for tag_id in tag_ids:
                form_data.append(('tags', tag_id))
            # Добавляем всех авторов в form_data
            for author_id in author_ids:
                form_data.append(('authors', author_id))

            files = {}
            with open(image_path, 'rb') as cover_image_file:
                files['image'] = ('blob', cover_image_file, mime_type)
                if game_data['img_or_link'] == 'img' and game_data.get('cyoa_pages'):
                    for i, page_path in enumerate(game_data['cyoa_pages']):
                        page_path_obj = Path(page_path)
                        if page_path_obj.exists():
                            page_mime_type = EXTENSION_TO_MIME.get(page_path_obj.suffix.lower(), mimetypes.guess_type(str(page_path_obj))[0])
                            if page_mime_type not in ALLOWED_IMAGE_MIME_TYPES:
                                logger.warning(f"Unsupported format for page {page_path}: {page_mime_type}")
                                continue
                            with open(page_path_obj, 'rb') as page_file:
                                files[f'cyoa_pages[{i}]'] = (f'page_{i}', page_file, page_mime_type)
                        else:
                            logger.warning(f"CYOA page not found: {page_path}")

                logger.debug(f"Form data: {form_data}")
                logger.debug(f"Files: {[k for k in files.keys()]}")
                response = requests.post(
                    f'{self.base_url}/collections/games/records',
                    headers=headers,
                    data=form_data,
                    files=files
                )
                logger.info(f"API response status: {response.status_code}")
                logger.debug(f"API response text: {response.text}")
                response.raise_for_status()
                game_record = response.json()
                logger.info(f"Game created successfully: {game_record['id']}")

            # Связываем авторов с игрой (на случай, если API не обработал authors в form_data)
            for author_id in author_ids:
                time.sleep(self.request_delay)
                self.link_game_to_author(game_record['id'], author_id)

            return game_record
        except Exception as e:
            logger.error(f"Failed to create game '{game_data['title']}': {str(e)}", exc_info=True)
            raise

    def link_game_to_author(self, game_id, author_id):
        logger.info(f"Linking game {game_id} to author {author_id}")
        try:
            if not self.token:
                raise Exception("Not authenticated")
            headers = {'Authorization': self.token}
            # Получаем текущие данные игры
            response = requests.get(
                f'{self.base_url}/collections/games/records/{game_id}',
                headers=headers
            )
            response.raise_for_status()
            game_data = response.json()
            current_authors = game_data.get('authors', [])
            if author_id not in current_authors:
                current_authors.append(author_id)
                response = requests.patch(
                    f'{self.base_url}/collections/games/records/{game_id}',
                    headers=headers,
                    json={'authors': current_authors}
                )
                response.raise_for_status()
                logger.info(f'Linked game {game_id} to author {author_id}')
            else:
                logger.info(f'Game {game_id} already linked to author {author_id}')
            # Обновляем автора (двусторонняя связь)
            response = requests.get(
                f'{self.base_url}/collections/authors/records/{author_id}',
                headers=headers
            )
            response.raise_for_status()
            author_data = response.json()
            current_games = author_data.get('games', [])
            if game_id not in current_games:
                current_games.append(game_id)
                response = requests.patch(
                    f'{self.base_url}/collections/authors/records/{author_id}',
                    headers=headers,
                    json={'games': current_games}
                )
                response.raise_for_status()
                logger.info(f'Updated author {author_id} with game {game_id}')
            return True
        except Exception as e:
            logger.error(f'Error linking game {game_id} to author {author_id}: {e}')
            return False

def move_processed_files(game_data, processed_folder):
    logger.info(f"Moving processed files for {game_data['title']} to {processed_folder}")
    try:
        os.makedirs(processed_folder, exist_ok=True)
        logger.info(f"Ensured folder exists: {processed_folder}")
        json_path = game_data.get('json_path')
        if not json_path or not os.path.exists(json_path):
            json_path = None
            for file in os.listdir("New_Games"):
                if file.endswith(".json"):
                    candidate_path = os.path.join("New_Games", file)
                    if os.path.getsize(candidate_path) == 0:
                        logger.warning(f"Found empty file {file}")
                        continue
                    try:
                        with open(candidate_path, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                            if data.get('title') == game_data['title']:
                                json_path = candidate_path
                                break
                    except json.JSONDecodeError as e:
                        logger.error(f"Error decoding JSON in {candidate_path}: {e}")
                        continue
        if not json_path:
            logger.warning(f"Could not find JSON file for game {game_data['title']}")
            return False
        json_filename = os.path.basename(json_path)
        base_name = os.path.splitext(json_filename)[0]
        shutil.move(json_path, os.path.join(processed_folder, json_filename))
        logger.info(f"Moved JSON file: {json_filename}")
        cover_path = game_data['image']
        cover_filename = os.path.basename(cover_path)
        shutil.move(cover_path, os.path.join(processed_folder, cover_filename))
        logger.info(f"Moved cover image: {cover_filename}")
        if game_data['img_or_link'] == 'img' and game_data.get('cyoa_pages'):
            pages_folder = os.path.join("New_Games", base_name)
            if os.path.isdir(pages_folder):
                processed_pages_folder = os.path.join(processed_folder, base_name)
                os.makedirs(processed_pages_folder, exist_ok=True)
                for page_file in os.listdir(pages_folder):
                    page_path = os.path.join(pages_folder, page_file)
                    if os.path.isfile(page_path):
                        shutil.move(page_path, os.path.join(processed_pages_folder, page_file))
                if len(os.listdir(pages_folder)) == 0:
                    os.rmdir(pages_folder)
                logger.info(f"Moved CYOA pages folder: {base_name}")
        return True
    except Exception as e:
        logger.error(f"Error moving processed files: {e}")
        return False

def load_games_from_folder(folder_path):
    logger.info(f"Loading games from folder: {folder_path}")
    games = []
    json_files = glob.glob(os.path.join(folder_path, "*.json"))
    for json_file in json_files:
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                game_data = json.load(f)
            base_name = os.path.splitext(os.path.basename(json_file))[0]
            image_path = None
            for ext in EXTENSION_TO_MIME.keys():
                img_path = os.path.join(folder_path, f"{base_name}{ext}")
                if os.path.exists(img_path):
                    image_path = img_path
                    break
            if not image_path:
                logger.warning(f"Cover image not found for {json_file}")
                continue
            game_data['image'] = image_path
            game_data['json_path'] = json_file
            if 'img_or_link' not in game_data:
                game_data['img_or_link'] = "img"
            if game_data['img_or_link'] == 'link' and 'iframe_url' not in game_data:
                logger.warning(f"iframe_url missing for link-type game in {json_file}")
                continue
            if game_data['img_or_link'] == 'img':
                if 'cyoa_pages' not in game_data or not game_data['cyoa_pages']:
                    pages_folder = os.path.join(folder_path, base_name)
                    if os.path.isdir(pages_folder):
                        page_files = []
                        for ext in EXTENSION_TO_MIME.keys():
                            page_files.extend(glob.glob(os.path.join(pages_folder, f"*{ext}")))
                        page_files.sort()
                        if page_files:
                            game_data['cyoa_pages'] = page_files
                        else:
                            logger.warning(f"No CYOA pages found in folder {pages_folder}")
                    else:
                        logger.warning(f"CYOA pages folder {pages_folder} not found")
                if 'cyoa_pages' not in game_data or not game_data['cyoa_pages']:
                    logger.warning(f"No CYOA pages specified for img-type game in {json_file}")
                    continue
            if 'uploader' not in game_data:
                game_data['uploader'] = "mar1q123caruaaw"
            games.append(game_data)
            logger.info(f"Loaded game: {game_data['title']} ({game_data['img_or_link']})")
        except Exception as e:
            logger.error(f"Error loading {json_file}: {e}")
    return games

def main():
    uploader = GameUploader()
    processed_folder = "Processed_Games"
    try:
        auth_data = uploader.login()
        if not auth_data:
            raise Exception("Failed to login")
        games = load_games_from_folder("New_Games")
        logger.info(f"Found {len(games)} games to upload")
        for i, game_data in enumerate(games):
            try:
                logger.info(f"Uploading game {i+1}/{len(games)}: {game_data['title']}")
                record = uploader.create_game(game_data)
                logger.info(f"Successfully uploaded: {game_data['title']} (ID: {record['id']})")
                if move_processed_files(game_data, processed_folder):
                    logger.info(f"Files for {game_data['title']} moved to {processed_folder}")
                if i < len(games) - 1:
                    logger.info(f"Waiting {uploader.request_delay} seconds before next upload")
                    time.sleep(uploader.request_delay)
            except Exception as e:
                logger.error(f"Failed to upload {game_data.get('title', 'Unknown')}: {str(e)}")
    except Exception as e:
        logger.critical(f"Critical error in main: {str(e)}", exc_info=True)

if __name__ == "__main__":
    main()