# components/game_checker.py

import os
from dotenv import load_dotenv
import requests
import logging

load_dotenv()

class GameChecker:
    def __init__(self):
        self.base_url = 'https://cyoa.cafe/api'
        self.email = os.getenv('EMAIL')
        self.password = os.getenv('PASSWORD')
        self.token = None
        self.existing_games = {}  # Словарь для хранения игр: {link: game_data}
        self.logger = logging.getLogger(__name__)
        self.logger.info("GameChecker initialized")

    def login(self):
        """Аутентификация с API"""
        self.logger.info(f"Attempting to login with email: {self.email}")
        try:
            response = requests.post(
                f'{self.base_url}/collections/users/auth-with-password',
                json={
                    'identity': self.email,
                    'password': self.password
                }
            )
            response.raise_for_status()
            self.token = response.json()['token']
            self.logger.info("Successfully authenticated with API")
            return True
        except Exception as e:
            self.logger.error(f"Failed to authenticate with API: {str(e)}")
            return False

    def load_existing_games(self):
        """Загрузка всех существующих игр из базы данных один раз"""
        if not self.token:
            self.logger.error("Cannot load games: Not authenticated")
            raise Exception("Not authenticated")

        headers = {'Authorization': self.token}
        all_games = []
        page = 1
        per_page = 200

        self.logger.info("Starting to load existing games from API")
        try:
            while True:
                self.logger.debug(f"Fetching page {page} with {per_page} items per page")
                response = requests.get(
                    f'{self.base_url}/collections/games/records',
                    headers=headers,
                    params={'page': page, 'perPage': per_page}
                )
                response.raise_for_status()

                data = response.json()
                games_chunk = data.get('items', [])
                self.logger.debug(f"Received {len(games_chunk)} games on page {page}")
                all_games.extend(games_chunk)

                if len(games_chunk) < per_page:
                    self.logger.info(f"Finished loading games. Total pages: {page}")
                    break
                page += 1

            # Сохраняем игры в словарь с ключом по полю iframe_url
            for game in all_games:
                link = game.get('iframe_url', '')
                if link:
                    normalized_link = self.normalize_url(link)
                    self.existing_games[normalized_link] = game
                    self.logger.debug(f"Added game to dictionary: {normalized_link}")

            self.logger.info(f"Loaded {len(self.existing_games)} existing games into memory")
        except Exception as e:
            self.logger.error(f"Error loading existing games: {str(e)}")
            raise

    def game_exists(self, url):
        """
        Проверка, существует ли игра с заданной ссылкой

        Args:
            url: URL игры для проверки

        Returns:
            bool: True если игра уже существует, False если нет
        """
        normalized_url = self.normalize_url(url)
        self.logger.info(f"Checking if game exists with URL: {normalized_url}")
        exists = normalized_url in self.existing_games
        if exists:
            self.logger.info(f"Game with URL {normalized_url} already exists in database")
            self.logger.debug(f"Existing game data: {self.existing_games[normalized_url]}")
        else:
            self.logger.info(f"Game with URL {normalized_url} does not exist in database")
        return exists

    def normalize_url(self, url):
        """Нормализация URL для согласованности"""
        original_url = url
        url = url.rstrip('/')
        if url.endswith('/index.html'):
            url = url[:-len('/index.html')]
        self.logger.debug(f"Normalized URL: {original_url} -> {url}")
        return url

def main():
    # Тестовый запуск компонента
    logging.basicConfig(level=logging.DEBUG)  # Устанавливаем уровень DEBUG для подробных логов
    checker = GameChecker()
    if checker.login():
        checker.load_existing_games()
        test_url = "https://example.com/game/project.json"
        print(f"Game exists: {checker.game_exists(test_url)}")

if __name__ == "__main__":
    main()