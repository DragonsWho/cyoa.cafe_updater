# image_replacer.py

import os
import sys
import subprocess
import requests
import logging
import base64
from io import BytesIO
from dotenv import load_dotenv
from pathlib import Path
from PIL import Image, UnidentifiedImageError
import argparse

# --- Configuration regarding console encoding for Windows ---
# This ensures that print() and logging to stdout handle UTF-8 correctly,
# which is important if Puppeteer returns paths with non-ASCII characters.
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        # Python < 3.7 doesn't have reconfigure, but highly likely using >= 3.9
        pass

# Logging setup
log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("logs/replace_game_image.log", encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)
logging.getLogger("PIL").setLevel(logging.WARNING)

# Constants
SCREENSHOTS_DIR = "screenshots"
API_BASE_URL = "https://cyoa.cafe/api"
PUPPETEER_SCRIPT = "get_screenshoot_puppy.js"
ALLOWED_MIME_TYPES = [
    "image/png", "image/jpeg", "image/gif", "image/webp",
    "image/avif", "image/svg+xml"
]

# Base64 placeholder parameters
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

    def login(self):
        """Authenticates with the API."""
        logger.info("Attempting to login...")
        if not self.email or not self.password:
            logger.error("Email or Password not set in .env")
            return False
        try:
            response = requests.post(
                f"{API_BASE_URL}/collections/users/auth-with-password",
                json={'identity': self.email, 'password': self.password},
                timeout=10
            )
            response.raise_for_status()
            self.token = response.json()['token']
            logger.info("Successfully logged in")
            return True
        except Exception as e:
            err_msg = f"Login failed: {str(e)}"
            if hasattr(e, 'response') and e.response is not None:
                err_msg += f" | Response: {e.response.text[:200]}"
            logger.error(err_msg)
            return False

    def load_all_games(self):
        """Loads all games from the server."""
        logger.info("Loading games list...")
        try:
            if not self.token: raise Exception("Not authenticated")
            headers = {'Authorization': self.token}
            all_games = []
            page = 1
            while True:
                response = requests.get(
                    f"{API_BASE_URL}/collections/games/records",
                    headers=headers,
                    params={'page': page, 'perPage': 500, 'skipTotal': '1'},
                    timeout=30
                )
                response.raise_for_status()
                data = response.json()
                items = data.get('items', [])
                if not items: break
                all_games.extend(items)
                if len(items) < 500: break
                page += 1
            
            self.games_cache = {g['title'].strip().lower(): g for g in all_games}
            logger.info(f"Loaded {len(self.games_cache)} games.")
            return True
        except Exception as e:
            logger.error(f"Error loading games: {e}")
            return False

    def capture_screenshot(self, url):
        """Runs Puppeteer. Handles both auto-snap and manual user upload from JS."""
        logger.info(f"Launching Puppeteer for: {url}")
        
        if not os.path.exists(PUPPETEER_SCRIPT):
            logger.error(f"Script missing: {PUPPETEER_SCRIPT}")
            return None
            
        Path(SCREENSHOTS_DIR).mkdir(exist_ok=True)

        try:
            # We use --pause to ensure the menu shows up immediately
            cmd = ["node", PUPPETEER_SCRIPT, url, "--pause"]
            
            # Run node. Important: encoding='utf-8' to parse paths correctly.
            # Assuming node is in PATH.
            process = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding='utf-8',
                check=True
            )

            # In updated JS, logs intended for user go to stderr, 
            # the final result goes to stdout.
            stdout_lines = process.stdout.strip().splitlines()
            
            # Look for the specific success marker
            final_path = None
            for line in reversed(stdout_lines):
                if line.startswith("Screenshot saved:"):
                    # Extract path part, strip whitespace
                    raw_path = line.split("Screenshot saved:", 1)[1].strip()
                    final_path = Path(raw_path)
                    break
            
            if final_path and final_path.exists():
                logger.info(f"Received image path from Puppeteer: {final_path}")
                return str(final_path)
            else:
                logger.error("Puppeteer finished, but could not find 'Screenshot saved:' marker or file is missing.")
                logger.debug(f"STDOUT: {process.stdout}")
                logger.debug(f"STDERR: {process.stderr}")
                return None

        except subprocess.CalledProcessError as e:
            logger.error(f"Puppeteer exited with error code {e.returncode}")
            logger.error(f"STDERR output:\n{e.stderr}")
            return None
        except FileNotFoundError:
            logger.error("Node.js executable not found. Is it installed and in PATH?")
            return None
        except Exception as e:
            logger.error(f"Unexpected error running Puppeteer: {e}")
            return None

    def replace_game_image(self, game_id, file_path):
        """Uploads the file to the API."""
        logger.info(f"Uploading image for game ID: {game_id}")
        path_obj = Path(file_path)
        
        if not path_obj.exists():
            logger.error(f"File to upload not found: {path_obj}")
            return False

        try:
            with open(path_obj, 'rb') as f:
                files = {'image': (path_obj.name, f, 'image/webp')}
                resp = requests.patch(
                    f"{API_BASE_URL}/collections/games/records/{game_id}",
                    headers={'Authorization': self.token},
                    files=files,
                    timeout=60
                )
                resp.raise_for_status()
                logger.info("Main image uploaded successfully.")
                return True
        except Exception as e:
            logger.error(f"Failed to upload image: {e}")
            if hasattr(e, 'response') and e.response:
                logger.error(f"API Response: {e.response.text}")
            return False

    def update_base64(self, game_id, file_path):
        """Generates and updates Base64 placeholder."""
        logger.info("Generating Base64 placeholder...")
        try:
            img = Image.open(file_path)
            if img.mode not in ('RGB', 'L'):
                img = img.convert('RGB')
            
            img.thumbnail((PLACEHOLDER_TARGET_WIDTH, PLACEHOLDER_TARGET_HEIGHT), PLACEHOLDER_RESAMPLE_METHOD)
            
            buf = BytesIO()
            img.save(buf, format=PLACEHOLDER_FORMAT, quality=PLACEHOLDER_QUALITY)
            b64_str = base64.b64encode(buf.getvalue()).decode('utf-8')
            data_uri = f"data:image/{PLACEHOLDER_FORMAT.lower()};base64,{b64_str}"
            
            resp = requests.patch(
                f"{API_BASE_URL}/collections/games/records/{game_id}",
                headers={'Authorization': self.token, 'Content-Type': 'application/json'},
                json={'image_base64': data_uri},
                timeout=30
            )
            resp.raise_for_status()
            logger.info("Base64 placeholder updated successfully.")
            return True
        except Exception as e:
            logger.warning(f"Failed to update Base64 (main image is fine): {e}")
            return False

    def process_game(self, game_title):
        title_key = game_title.strip().lower()
        game = self.games_cache.get(title_key)
        
        if not game:
            logger.error(f"Game not found: {game_title}")
            # Try partial match for better UX
            matches = [g['title'] for t, g in self.games_cache.items() if title_key in t]
            if matches:
                logger.info(f"Did you mean: {', '.join(matches[:3])}?")
            return False

        if not game.get('iframe_url') or game.get('img_or_link') != 'link':
            logger.error(f"Game '{game['title']}' is not configured for link screenshots.")
            return False

        # 1. Get Image Path (either autosnapped or uploaded via JS UI)
        image_path = self.capture_screenshot(game['iframe_url'])
        if not image_path:
            return False

        print(f"--> Preparing to upload: {image_path}")

        # 2. Upload Main Image
        if self.replace_game_image(game['id'], image_path):
            # 3. Update Base64
            self.update_base64(game['id'], image_path)
            return True
        
        return False

def main():
    parser = argparse.ArgumentParser(description='Update game image via Puppeteer (Auto or Manual Upload).')
    parser.add_argument('game_title', help='Exact title of the game.')
    args = parser.parse_args()

    replacer = GameImageReplacer()

    if not replacer.login(): return
    if not replacer.load_all_games(): return

    print(f"\nProcessing: {args.game_title}")
    print("Browser window will open. Use UI to Pause, Save to Disk, Upload, or Continue.")
    
    if replacer.process_game(args.game_title):
        print(f"\nSUCCESS: Updated '{args.game_title}'.")
    else:
        print(f"\nFAILED: Could not update '{args.game_title}'. Check logs.")
        sys.exit(1)

if __name__ == "__main__":
    main()