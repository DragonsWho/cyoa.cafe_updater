# summarize.py
import os
import asyncio
import sys
import json
import subprocess
import pandas as pd
import logging
from fuzzywuzzy import fuzz
from urllib.parse import urlparse, unquote
import requests
import base64
import mimetypes
from dotenv import load_dotenv

# --- Configuration, paths, and logger setup ---
load_dotenv()
# OLD: OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
# NEW: Nano GPT API Key
NANO_GPT_API_KEY = os.getenv("NANO_GPT_API_KEY")

# OLD: OPENROUTER_MODEL = "moonshotai/deepseek/deepseek-chat-v3-0324"
# NEW: Nano GPT Model (use a model supported by Nano GPT, e.g., chatgpt-4o-latest)
# Make sure to set NANO_GPT_MODEL in your .env file or it defaults to chatgpt-4o-latest
NANO_GPT_MODEL = os.getenv("NANO_GPT_MODEL", "chatgpt-4o-latest")

# OLD: OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
# NEW: Nano GPT API URL
NANO_GPT_API_URL = "https://nano-gpt.com/api/v1/chat/completions"

# These were specific to OpenRouter's headers and are no longer needed for Nano GPT
# YOUR_SITE_URL = os.getenv("YOUR_SITE_URL", "http://localhost")
# YOUR_APP_NAME = os.getenv("YOUR_APP_NAME", "CYOA_Summarizer")

PROMPTS_DIR = "prompts"
SENT_SEARCH_PROMPT_PATH = os.path.join(PROMPTS_DIR, "Grok_for_sent_search.md")
CATALOG_PROMPT_PATH = os.path.join(PROMPTS_DIR, "Grok_description_for_catalog.md")
CSV_PATH = "games.csv"
LOGS_DIR = "logs"
os.makedirs(LOGS_DIR, exist_ok=True)
log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s')
log_handler_file = logging.FileHandler(os.path.join(LOGS_DIR, "summarize.log"))
log_handler_file.setFormatter(log_formatter)
log_handler_stream = logging.StreamHandler(sys.stdout)
log_handler_stream.setFormatter(log_formatter)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if not logger.handlers:
    logger.addHandler(log_handler_file)
    logger.addHandler(log_handler_stream)
logger.propagate = False

# --- Logging Helper Functions ---
def mask_auth_header(headers):
    """Masks the Authorization token in headers for safe logging."""
    masked_headers = headers.copy()
    token = masked_headers.get("Authorization")
    if token:
        masked_headers["Authorization"] = f"{token[:10]}...{token[-4:]}"
    return masked_headers

def shorten_base64(data):
    """Shortens a Base64 data URI for concise logging."""
    if isinstance(data, str) and data.startswith("data:image"):
        prefix = data[:data.find("base64,")+7]
        content = data[len(prefix):]
        if len(content) > 100:
            return f"{prefix}{content[:20]}...[truncated]...{content[-20:]}"
    return data

def log_payload(payload):
    """Prepares and formats a JSON payload for logging, shortening any Base64 data."""
    try:
        payload_copy = json.loads(json.dumps(payload))
        messages = payload_copy.get("messages", [])
        for msg in messages:
            content = msg.get("content")
            if isinstance(content, list):
                for item in content:
                    if item.get("type") == "image_url" and "image_url" in item and "url" in item["image_url"]:
                        item["image_url"]["url"] = shorten_base64(item["image_url"]["url"])
        return json.dumps(payload_copy, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error preparing payload for logging: {e}")
        return str(payload)

# --- Helper Functions ---
def load_prompt(prompt_path):
    """Loads a text file from the given path."""
    logger.info(f"Loading prompt from {prompt_path}")
    if not os.path.exists(prompt_path):
        raise FileNotFoundError(f"Prompt file not found: {prompt_path}")
    f = None
    try:
        f = open(prompt_path, 'r', encoding='utf-8')
        content = f.read()
        return content
    except Exception as e:
        logger.error(f"Failed to read prompt file {prompt_path}: {e}", exc_info=True)
        raise
    finally:
        if f:
            f.close()

def load_game_text(md_path):
    """Loads a game's markdown text from the given path."""
    logger.info(f"Loading game text from {md_path}")
    if not os.path.exists(md_path):
       raise FileNotFoundError(f"Game text file not found: {md_path}")
    f = None
    try:
       f = open(md_path, 'r', encoding='utf-8')
       content = f.read()
       return content
    except Exception as e:
       logger.error(f"Failed to read game text file {md_path}: {e}", exc_info=True)
       raise
    finally:
        if f:
            f.close()

def get_authors_list():
    """Fetches a list of authors by running an external API script."""
    logger.info("Fetching authors list")
    script_name = "components/api_authors.py"
    try:
        result = subprocess.run([sys.executable, script_name], capture_output=True, text=True, check=True, encoding='utf-8')
        authors = result.stdout.strip()
        logger.info(f"Successfully fetched authors list ({len(authors.splitlines())} lines).")
        return authors
    except FileNotFoundError:
         logger.error(f"Error running {script_name}: Python executable or script not found at expected relative path.")
         return ""
    except subprocess.CalledProcessError as e:
        logger.error(f"Error getting authors list. Script {script_name} failed ({e.returncode}). Stderr: {e.stderr.strip()}")
        return ""
    except Exception as e:
        logger.error(f"Unexpected error getting authors list from {script_name}: {str(e)}", exc_info=True)
        return ""

def get_tag_categories():
    """Fetches a list of tag categories by running an external API script."""
    logger.info("Fetching tag categories")
    script_name = "components/api_tags.py"
    try:
        result = subprocess.run([sys.executable, script_name], capture_output=True, text=True, check=True, encoding='utf-8')
        tags = result.stdout.strip()
        logger.info(f"Successfully fetched tag categories ({len(tags.splitlines())} lines).")
        return tags
    except FileNotFoundError:
         logger.error(f"Error running {script_name}: Python executable or script not found at expected relative path.")
         return ""
    except subprocess.CalledProcessError as e:
        logger.error(f"Error getting tag categories. Script {script_name} failed ({e.returncode}). Stderr: {e.stderr.strip()}")
        return ""
    except Exception as e:
        logger.error(f"Unexpected error getting tag categories from {script_name}: {str(e)}", exc_info=True)
        return ""

async def run_vision_query(webp_path, max_retries=3):
    """Runs an external asynchronous script to get a visual description of an image."""
    logger.info(f"Running vision query (external script) for {webp_path}")
    script_name = "vision_query.py"
    logger.debug(f"Attempting to run script: {script_name} with arg: {webp_path}")
    try:
        try:
            import controller
        except ImportError:
            sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
            import controller
        success, output, error = await controller.run_script_async(script_name, webp_path, max_retries=max_retries)
        if success and output and not output.startswith("Visual analysis error:"):
            logger.info(f"Vision query successful. Output length: {len(output)}")
            return output.strip()
        else:
            logger.warning(f"Vision query script returned error/empty or failed: {output or error}")
            return None
    except Exception as e:
        logger.error(f"Error running vision query script '{script_name}': {str(e)}", exc_info=True)
        return None

def get_csv_hint(project_name):
    """Searches a CSV file for entries matching the project name to provide a hint."""
    logger.info(f"Getting CSV hint for {project_name} using path: {CSV_PATH}")
    if not os.path.exists(CSV_PATH):
        logger.warning(f"CSV file not found: {CSV_PATH}")
        return "\n\n=== CSV Hint ===\nCSV file not found."
    try:
        df = pd.read_csv(CSV_PATH, encoding='utf-8')
        # ... (rest of the function is unchanged)
        required_columns = ['Title', 'Author', 'Type', 'Static', 'Interactive']
        if not all(col in df.columns for col in required_columns):
            missing = [col for col in required_columns if col not in df.columns]
            logger.warning(f"CSV is missing required columns: {missing}")
            return "\n\n=== CSV Hint ===\nCSV is missing required columns."

        project_name_normalized = unquote(project_name.lower()).replace(" ", "")
        matches = []
        for index, row in df.iterrows():
            csv_title = str(row['Title']) if pd.notna(row['Title']) else ""
            csv_url = str(row['Static']) if pd.notna(row['Static']) else ""
            csv_interactive = str(row['Interactive']) if pd.notna(row['Interactive']) else ""
            csv_title_normalized = csv_title.lower().replace(" ", "")
            url_similarity = 0
            if csv_url and csv_url != "nan":
                try:
                    url_normalized = unquote(csv_url.lower()).replace(" ","")
                    url_path = urlparse(csv_url).path.rstrip('/').split('/')[-1].lower()
                    url_path_normalized = unquote(url_path).replace(" ","")
                    url_similarity = max(fuzz.ratio(project_name_normalized, url_normalized), fuzz.ratio(project_name_normalized, url_path_normalized))
                except Exception as url_err:
                    logger.warning(f"Could not parse URL from CSV row {index}: '{csv_url}'. Error: {url_err}")
            interactive_similarity = 0
            if csv_interactive and csv_interactive != "nan":
                 try:
                     interactive_normalized = unquote(csv_interactive.lower()).replace(" ","")
                     interactive_similarity = fuzz.ratio(project_name_normalized, interactive_normalized)
                 except Exception as inter_err:
                     logger.warning(f"Could not process interactive URL from CSV row {index}: '{csv_interactive}'. Error: {inter_err}")
            title_similarity = fuzz.ratio(project_name_normalized, csv_title_normalized)
            max_similarity = max(title_similarity, url_similarity, interactive_similarity)
            if max_similarity >= 70:
                matches.append((row, max_similarity))

        if not matches:
            logger.info("No matching entries found in CSV for this project name.")
            return "\n\n=== CSV Hint ===\nNo matching entries found in CSV for this project name."

        matches.sort(key=lambda x: x[1], reverse=True)
        hint = "\n\n=== CSV Hint ===\nPossible matches from CSV based on project name:\n"
        for match_row, similarity in matches[:3]:
             hint += f"- Title: {match_row.get('Title', 'N/A')}, Author: {match_row.get('Author', 'N/A')}, Type: {match_row.get('Type', 'N/A')} (Similarity: {similarity}%)\n"
        hint += "\nNote: When specifying the author, try to use one of the existing variants for consistency.\n"
        logger.info(f"Generated CSV hint with {len(matches)} potential matches.")
        return hint
    except Exception as e:
        logger.error(f"Unexpected error processing CSV {CSV_PATH}: {str(e)}", exc_info=True)
        return "\n\n=== CSV Hint ===\nUnexpected error processing CSV."


# OLD: def call_openrouter_api(prompt_text, image_path=None, timeout=180):
def call_nano_gpt_api(prompt_text, image_path=None, timeout=180):
    """Calls the Nano GPT API with a text prompt and an optional image."""
    # OLD: if not OPENROUTER_API_KEY:
    if not NANO_GPT_API_KEY:
        logger.error("Nano GPT API Key (NANO_GPT_API_KEY) not found.")
        return "Error: API Key missing."

    headers = {
        # OLD: "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Authorization": f"Bearer {NANO_GPT_API_KEY}",
        "Content-Type": "application/json",
        # Removed OpenRouter specific headers:
        # "HTTP-Referer": YOUR_SITE_URL,
        # "X-Title": YOUR_APP_NAME,
    }
    messages = [{"role": "user", "content": [{"type": "text", "text": prompt_text}]}]
    if image_path and os.path.exists(image_path):
        f = None
        try:
            logger.info(f"Encoding image {image_path}")
            mime_type, _ = mimetypes.guess_type(image_path)
            if mime_type and mime_type.startswith("image/"):
                with open(image_path, "rb") as f:
                    base64_image = base64.b64encode(f.read()).decode('utf-8')
                    image_data_url = f"data:{mime_type};base64,{base64_image}"
                    messages[0]["content"].append({"type": "image_url", "image_url": {"url": image_data_url}})
                    logger.info(f"Image {image_path} added.")
            else:
                logger.warning(f"Invalid image MIME type for {image_path}. Skipping.")
        except Exception as e:
            logger.error(f"Error processing image {image_path}: {e}", exc_info=True)
    elif image_path:
        logger.warning(f"Image file provided but not found: {image_path}")

    # OLD: payload = {"model": OPENROUTER_MODEL, "messages": messages}
    payload = {"model": NANO_GPT_MODEL, "messages": messages}
    logger.info("--- Sending request ---")
    # OLD: logger.info(f"URL: {OPENROUTER_API_URL}")
    logger.info(f"URL: {NANO_GPT_API_URL}")
    # OLD: logger.info(f"Model: {OPENROUTER_MODEL}")
    logger.info(f"Model: {NANO_GPT_MODEL}")
    logger.info(f"Headers: {mask_auth_header(headers)}")
    logger.info(f"Payload:\n{log_payload(payload)}")

    response_text = None
    try:
        # OLD: response = requests.post(OPENROUTER_API_URL, headers=headers, json=payload, timeout=timeout)
        response = requests.post(NANO_GPT_API_URL, headers=headers, json=payload, timeout=timeout)
        response_text = response.text
        logger.info(f"--- Received response ({response.status_code}) ---")
        logger.info(f"Body:\n{response_text}")
        response.raise_for_status()
        data = response.json()

        # --- NEW: Check for content filter ---
        choice = data.get("choices", [{}])[0]
        finish_reason = choice.get("finish_reason")
        if finish_reason == "content_filter":
            # Removed native_reason as it's OpenRouter specific.
            error_msg = f"API refused to generate content due to content filter."
            logger.error(error_msg)
            return f"Error: FATAL_CONTENT_FILTER: API content filter triggered." # Return a specific fatal error

        if "choices" not in data or not data["choices"]:
             raise ValueError("Invalid response structure: 'choices' missing or empty.")
        message = data["choices"][0].get("message")
        if not message:
            raise ValueError("Invalid response structure: 'message' missing.")
        content = message.get("content")
        if content is None:
            logger.warning("API returned null or empty content.")
            content = ""
        logger.info(f"API Usage: {data.get('usage', 'N/A')}")
        return content.strip()
    except requests.exceptions.RequestException as e:
        logger.error(f"API Request Failed: {e}", exc_info=True)
        return f"Error: API Request Failed. Details: {e}"
    except (json.JSONDecodeError, ValueError, KeyError, IndexError) as e:
         logger.error(f"Failed to parse or extract content from API response: {e}", exc_info=True)
         return f"Error: Failed to process API response. Details: {e}"
    except Exception as e:
        logger.error(f"Unexpected API Call Error: {e}", exc_info=True)
        return f"Error: Unexpected API fail. Details: {e}"


# --- Main Summarization Function ---
async def summarize_md_file(md_file_name, mode="sent_search"):
    """Summarizes a markdown file using an AI model."""
    logger.info(f"Starting summarization for '{md_file_name}' in '{mode}' mode")

    project_name = os.path.splitext(md_file_name)[0]
    md_path = os.path.join("markdown", md_file_name)
    webp_path = os.path.join("screenshots", f"{project_name}.webp")

    # ... (path setup is unchanged)
    if mode == "catalog":
        output_dir = "catalog_json"
        output_path = os.path.join(output_dir, f"{project_name}.json")
        prompt_path = CATALOG_PROMPT_PATH
    else: # sent_search
        output_dir = "summaries"
        output_path = os.path.join(output_dir, f"{project_name}.md")
        prompt_path = SENT_SEARCH_PROMPT_PATH

    logger.info(f"Paths: MD='{md_path}', Screenshot='{webp_path}', Prompt='{prompt_path}', Output='{output_path}'")

    try:
        prompt_template = load_prompt(prompt_path)
        game_text = load_game_text(md_path)
    except Exception as e:
        logger.error(f"Error loading files: {e}", exc_info=True)
        return False

    # ... (vision and additional data parts are unchanged)
    vision_description = ""
    image_path_for_api = None
    if os.path.exists(webp_path):
        image_path_for_api = webp_path
        vision_output = await run_vision_query(webp_path)
        if vision_output:
            vision_description = f"\n\n=== Screenshot Description ===\n{vision_output}\n"
            logger.info("Added vision query text to the prompt.")
        else:
            logger.info("Vision query returned no text, but the image will be sent to the API.")
    else:
        logger.warning(f"Screenshot not found: {webp_path}")

    additional_data = ""
    if mode == "catalog":
        logger.info("Fetching extra data for catalog mode...")
        authors = get_authors_list()
        tags = get_tag_categories()
        csv_hint = get_csv_hint(project_name)
        if authors: additional_data += f"\n\n=== List of Known Authors ===\n{authors}\n"
        if tags: additional_data += f"\n\n=== List of Known Tag Categories ===\n{tags}\n"
        additional_data += csv_hint

    full_prompt = f"{prompt_template}{additional_data}\n\n=== Game Text ===\n{game_text}{vision_description}"
    logger.info(f"Prompt constructed. Beginning: {full_prompt[:500]}...")
    # OLD: response = call_openrouter_api(full_prompt, image_path=image_path_for_api, timeout=180)
    response = call_nano_gpt_api(full_prompt, image_path=image_path_for_api, timeout=180)
    logger.info("Raw response received from API.")

    # --- NEW: Handle fatal content filter error ---
    if response.startswith("Error: FATAL_CONTENT_FILTER"):
        logger.error(f"Cannot proceed with '{md_file_name}': {response}. This is a fatal error for this file, skipping.")
        return True # Return True to prevent retries. The failure is logged.

    if response.startswith("Error:"):
        logger.error(f"API call failed for '{md_file_name}'. Full error: {response}")
        return False # This is a retryable error

    if not response or not response.strip():
        logger.error(f"API returned an empty or whitespace-only response for '{md_file_name}'. This is treated as a failure.")
        return False # This is a retryable error

    try:
        os.makedirs(output_dir, exist_ok=True)
        logger.info(f"Ensured output directory exists: {output_dir}")
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(response)
        logger.info(f"File save SUCCESS. Path: {output_path} (Size: {os.path.getsize(output_path)} bytes)")
    except Exception as e:
        logger.error(f"Unexpected error saving response file {output_path}: {e}", exc_info=True)
        return False

    return True


# --- Main Entry Point ---
async def main():
    logger.info("--- Summarize Script Started ---")
    # OLD: if not OPENROUTER_API_KEY:
    if not NANO_GPT_API_KEY:
        logger.critical("FATAL: NANO_GPT_API_KEY environment variable is not set.")
        sys.exit(1)
    logger.info("API Key found.")

    if len(sys.argv) < 2:
        logger.error("No markdown file name provided.")
        print("Usage: python summarize.py <markdown_file_name> [--mode sent_search|catalog]")
        sys.exit(1)

    md_file_name = sys.argv[1]
    mode = "sent_search"

    if "--mode" in sys.argv:
        try:
            mode_index = sys.argv.index("--mode") + 1
            mode = sys.argv[mode_index]
            if mode not in ["sent_search", "catalog"]:
                 raise ValueError(f"Invalid mode specified: {mode}")
            logger.info(f"Mode explicitly set to: {mode}")
        except Exception as e:
            logger.error(f"Error parsing command line arguments: {e}")
            print("Usage: python summarize.py <file_name> [--mode sent_search|catalog]")
            sys.exit(1)
    else:
        logger.info(f"Mode not specified, using default: {mode}")

    logger.info(f"Processing markdown file name: {md_file_name}")

    try:
        success = await summarize_md_file(md_file_name, mode=mode)
        if not success:
            logger.error(f"Failed to process {md_file_name} in {mode} mode (retryable error).")
            logger.info("--- Summarize Script Finished with Errors ---")
            sys.exit(1)
        else:
            logger.info(f"Successfully processed {md_file_name} in {mode} mode (or skipped due to fatal error).")
            logger.info("--- Summarize Script Finished Successfully ---")
            sys.exit(0)
    except Exception as e:
        logger.critical(f"Unhandled exception in main execution block: {e}", exc_info=True)
        logger.info("--- Summarize Script Finished with Unhandled Exception ---")
        sys.exit(1)


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())