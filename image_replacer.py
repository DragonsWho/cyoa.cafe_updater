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
import argparse  # For command-line argument processing

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        # Explicitly specify the encoding
        logging.FileHandler("logs/replace_game_image.log", encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)
# Reduce "noise" from the Pillow library in the logs
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
        logger.info("GameImageReplacer initialized")

    def login(self):
        """Authenticates with the API."""
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
            # Include response text on error for better debugging
            err_msg = f"Login failed: {str(e)}"
            if hasattr(e, 'response') and e.response is not None:
                err_msg += f" | Response: {e.response.text[:500]}"
            logger.error(err_msg)
            return False

    def load_all_games(self):
        """Loads all games from the server."""
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
                    # skipTotal can speed up the request
                    params={'page': page, 'perPage': per_page, 'skipTotal': '1'}
                )
                response.raise_for_status()
                data = response.json()
                games_chunk = data.get('items', [])
                all_games.extend(games_chunk)
                # Correct stopping condition for Pocketbase
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
        """Finds a game by its title."""
        title_lower = title.lower()
        if title_lower in self.games_cache:
            logger.info(f"Found game: {title} (ID: {self.games_cache[title_lower]['id']})")
            return self.games_cache[title_lower]
        logger.warning(f"Game not found: {title}")
        return None

    def capture_screenshot(self, url):
        """Runs Puppeteer to capture a screenshot."""
        logger.info(f"Capturing screenshot for URL: {url}")
        try:
            if not os.path.exists(PUPPETEER_SCRIPT):
                raise FileNotFoundError(f"Puppeteer script not found: {PUPPETEER_SCRIPT}")

            os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
            # Use encoding='utf-8' for correct parsing of node.js output
            result = subprocess.run(
                ["node", PUPPETEER_SCRIPT, url, "--pause"],
                capture_output=True,
                text=True,
                check=True,
                encoding='utf-8'
            )
            # Log the entire output for debugging
            logger.debug(f"Puppeteer output: {result.stdout}")

            # Extract the path from Puppeteer's output.
            screenshot_path_str = None
            output_lines = result.stdout.strip().splitlines()
            # Find the last line starting with "Screenshot saved:"
            saved_path_line = next((line for line in reversed(output_lines) if line.startswith("Screenshot saved:")), None)

            if saved_path_line:
                 # Extract the path after "Screenshot saved: "
                 actual_path_str_from_log = saved_path_line.split("Screenshot saved:", 1)[1].strip()
                 actual_path = Path(actual_path_str_from_log)
                 if actual_path.exists():
                     logger.info(f"Screenshot path extracted from Puppeteer output: {actual_path}")
                     screenshot_path_str = str(actual_path) # Return a string
                 else:
                     # If the file from the log path is not found, it's an error.
                     logger.error(f"Path found in Puppeteer output, but file does not exist: {actual_path}")
                     # Do not use fallback guessing if the log entry exists but the file is missing.
                     return None
            else:
                 # If "Screenshot saved:" is NOT found, use the ORIGINAL name guessing logic.
                 logger.warning("Could not find 'Screenshot saved:' in Puppeteer output. Falling back to original name guessing logic.")
                 # --- START ORIGINAL GUESSING LOGIC ---
                 from urllib.parse import urlparse # Import here as it's only needed for the fallback
                 parsed_uri = urlparse(url)
                 # Original logic for determining the name from the URL
                 screenshot_name_part = parsed_uri.path.rstrip('/').split('/')[-1]
                 if not screenshot_name_part: # If path is empty or '/'
                     screenshot_name_part = parsed_uri.netloc.split('.')[0] # Take the first part of the host

                 # Build the path as in the original code
                 screenshot_path_obj = Path(SCREENSHOTS_DIR) / f"{screenshot_name_part}.webp"
                 # --- END ORIGINAL GUESSING LOGIC ---

                 if screenshot_path_obj.exists():
                     logger.info(f"Using guessed screenshot path: {screenshot_path_obj}")
                     screenshot_path_str = str(screenshot_path_obj)
                 else:
                     logger.error(f"Screenshot file not found using original guessing logic: {screenshot_path_obj}")
                     return None # Error if guessing also fails

            return screenshot_path_str # Return the string path

        except subprocess.CalledProcessError as e:
            logger.error(f"Puppeteer script failed with exit code {e.returncode}")
            # Log both stdout and stderr for a complete picture
            logger.error(f"Puppeteer stderr:\n{e.stderr}")
            logger.error(f"Puppeteer stdout:\n{e.stdout}")
            return None
        except FileNotFoundError as e: # If node or the script itself is not found
            logger.error(f"File not found error during Puppeteer execution: {e}")
            return None
        except Exception as e:
            # Add traceback for unexpected errors
            logger.error(f"Error capturing screenshot: {str(e)}", exc_info=True)
            return None

    def replace_game_image(self, game_id, screenshot_path):
        """Replaces a game's image via the API."""
        logger.info(f"Replacing image file for game ID: {game_id}")
        try:
            if not self.token:
                raise Exception("Not authenticated")
            headers = {'Authorization': self.token}

            screenshot_path_obj = Path(screenshot_path) # Use Path for file operations
            if not screenshot_path_obj.exists():
                # Use FileNotFoundError for clarity
                raise FileNotFoundError(f"Screenshot file not found: {screenshot_path_obj}")

            mime_type = "image/webp"  # Assuming Puppeteer saves as .webp
            if mime_type not in ALLOWED_MIME_TYPES:
                # Keep this check, although it might be redundant
                raise ValueError(f"Unsupported mime type: {mime_type}")

            # Use 'with open' to ensure the file is closed
            with open(screenshot_path_obj, 'rb') as image_file:
                # Use the filename from the Path object for correct multipart submission
                files = {'image': (screenshot_path_obj.name, image_file, mime_type)}
                response = requests.patch(
                    f"{API_BASE_URL}/collections/games/records/{game_id}",
                    headers=headers,
                    files=files
                )
            # Log status and a preview of the response body
            logger.debug(f"API response status for image replace: {response.status_code}")
            # Limit the length for the log
            response_text = response.text[:500]
            logger.debug(f"API response body preview: {response_text}...")
            # Check for HTTP 4xx/5xx errors
            response.raise_for_status()

            logger.info(f"Successfully replaced image file for game ID: {game_id}")
            return True
        # Explicitly catch FileNotFoundError
        except FileNotFoundError as e:
             logger.error(f"Failed to replace image for game ID {game_id}: {e}")
             return False
        # Handle requests errors
        except requests.exceptions.RequestException as e:
             logger.error(f"API error replacing image for game ID {game_id}: {e}")
             if e.response is not None:
                  logger.error(f"API Error details: Status={e.response.status_code}, Body={e.response.text[:500]}...")
             return False
        # Handle other exceptions
        except Exception as e:
            logger.error(f"Unexpected error replacing image for game ID {game_id}: {str(e)}", exc_info=True)
            return False

    def _generate_base64_placeholder(self, image_path, game_id="N/A"):
        """Helper function to generate a Base64 placeholder."""
        img = None
        image_path_obj = Path(image_path)
        if not image_path_obj.exists():
             logger.error(f"[{game_id}] Image file not found for Base64 generation: {image_path_obj}")
             return None
        try:
            logger.info(f"[{game_id}] Generating Base64 placeholder from {image_path_obj.name}...")
            img = Image.open(image_path_obj)
            # Convert to RGB if necessary (e.g., for GIFs with a palette or 'P' mode)
            if img.mode in ('P', 'RGBA', 'LA'):
                 logger.debug(f"[{game_id}] Converting image mode from {img.mode} to RGB for Base64 generation.")
                 img = img.convert('RGB')
            elif img.mode != 'RGB':
                 logger.warning(f"[{game_id}] Image mode is {img.mode}. Attempting Base64 generation, but might fail if target format requires RGB.")

            img.thumbnail((PLACEHOLDER_TARGET_WIDTH, PLACEHOLDER_TARGET_HEIGHT), PLACEHOLDER_RESAMPLE_METHOD)
            buffer = BytesIO()
            # Save to buffer with the specified parameters
            img.save(buffer, format=PLACEHOLDER_FORMAT, quality=PLACEHOLDER_QUALITY, lossless=PLACEHOLDER_LOSSLESS)
            buffer.seek(0)
            # Encode to Base64
            encoded_string = base64.b64encode(buffer.getvalue()).decode('utf-8')
            # Format the data URI
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
            # Ensure the Pillow image object is closed
            if img and hasattr(img, 'close'):
                try: img.close()
                except Exception as close_err: logger.warning(f"[{game_id}] Failed to close PIL image object: {close_err}")

    def _update_game_base64(self, game_id, base64_string):
        """Helper function to update only the image_base64 field."""
        logger.info(f"Updating Base64 placeholder for game ID: {game_id}")
        if not base64_string:
            logger.warning(f"[{game_id}] Attempted to update Base64 with an empty string. Aborting.")
            return False
        try:
            if not self.token:
                raise Exception("Not authenticated for Base64 update")
            # Headers for the JSON request
            headers = {'Authorization': self.token, 'Content-Type': 'application/json'}
            # Request payload
            payload = {'image_base64': base64_string}

            response = requests.patch(
                f"{API_BASE_URL}/collections/games/records/{game_id}",
                headers=headers,
                json=payload # Send data as JSON
            )
            logger.debug(f"API response status for Base64 update: {response.status_code}")
            response_text = response.text[:500]
            logger.debug(f"API response body preview: {response_text}...")
            response.raise_for_status()

            logger.info(f"Successfully updated Base64 placeholder for game ID: {game_id}")
            return True
        # Handle requests errors
        except requests.exceptions.RequestException as e:
             logger.error(f"API error updating Base64 for game ID {game_id}: {e}")
             if e.response is not None:
                  logger.error(f"API Error details: Status={e.response.status_code}, Body={e.response.text[:500]}...")
             return False
        # Handle other exceptions
        except Exception as e:
            logger.error(f"Unexpected error updating Base64 for game ID {game_id}: {str(e)}", exc_info=True)
            return False

    def process_game(self, game_title):
        """Main game processing logic."""
        # Find the game
        game = self.find_game_by_title(game_title)
        if not game:
            logger.error(f"Game '{game_title}' not found on server")
            return False

        game_id = game['id']
        iframe_url = game.get('iframe_url', '')

        # Check if a URL exists for screenshot capture (use .get for safety)
        if not iframe_url or game.get('img_or_link') != 'link':
            # Add details to the log for clarity
            current_type = game.get('img_or_link', 'N/A')
            logger.error(f"Game '{game_title}' (ID: {game_id}) cannot be processed: img_or_link='{current_type}' (expected 'link'), iframe_url='{iframe_url}'")
            return False

        # Capture a new screenshot
        screenshot_path = self.capture_screenshot(iframe_url)
        if not screenshot_path:
            logger.error(f"Failed to capture screenshot for '{game_title}' (ID: {game_id})")
            return False

        # Replace the image (the main file)
        success = self.replace_game_image(game_id, screenshot_path)

        # Generate and update the Base64 placeholder
        if success:
            logger.info(f"[{game_id}] Main image file updated. Attempting to generate and update Base64 placeholder...")
            # Generate Base64 from the new screenshot
            base64_string = self._generate_base64_placeholder(screenshot_path, game_id)
            if base64_string:
                # If generation was successful, update it on the server
                base64_update_success = self._update_game_base64(game_id, base64_string)
                if not base64_update_success:
                    # Log the Base64 update error, but don't change the overall `success` status
                    logger.error(f"[{game_id}] Failed to update the Base64 placeholder on the server, although the main image was updated.")
            else:
                # Log the Base64 generation error
                logger.warning(f"[{game_id}] Failed to generate Base64 placeholder from the new screenshot. Base64 field was not updated.")
        else:
            logger.error(f"[{game_id}] Failed to update the main image file. Base64 generation and update will be skipped.")

        if success:
            # File deletion is commented out to keep screenshots locally
            # try:
            #     os.remove(screenshot_path)
            #     logger.info(f"Cleaned up screenshot file: {screenshot_path}")
            # except Exception as e:
            #     logger.warning(f"Failed to remove screenshot file: {e}")
            logger.info(f"Screenshot retained at: {screenshot_path}")
            # Return True if the main operation (file replacement) succeeded
            return True
        else:
            # Return False if the main operation failed
            return False

def main():
    # Use argparse for more flexible argument handling
    parser = argparse.ArgumentParser(description='Replace game image and generate/update its Base64 placeholder on cyoa.cafe.')
    parser.add_argument('game_title', help='The title of the game to update.')
    # Future flags can be easily added here, e.g.:
    # parser.add_argument('--skip-base64', action='store_true', help='Only replace the main image, skip Base64.')
    args = parser.parse_args()

    game_title = args.game_title
    logger.info(f"Starting image and Base64 update process for game: '{game_title}'")

    replacer = GameImageReplacer()

    # Login
    if not replacer.login():
        logger.critical("Authentication failed. Please check EMAIL and PASSWORD in your .env file.")
        sys.exit(1)

    # Load the game cache (do this once)
    if not replacer.load_all_games():
        logger.critical("Failed to load the list of games from the server.")
        sys.exit(1)

    # Process the specific game
    success = replacer.process_game(game_title)

    # Print the final result to the console
    if success:
        # The main operation (file replacement) was successful
        logger.info(f"Successfully processed '{game_title}'. Main image updated. Check logs for Base64 status.")
        print(f"Main image for '{game_title}' updated successfully. See logs for Base64 details.")
    else:
        # The main operation failed
        logger.error(f"Failed to update the main image for '{game_title}'. Check logs/replace_game_image.log for details.")
        print(f"Error updating image for '{game_title}'. Check logs.")
        sys.exit(1)

if __name__ == "__main__":
    # Ensure the logs directory exists before starting
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    main()