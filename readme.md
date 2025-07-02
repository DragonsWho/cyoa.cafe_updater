# CYOA.CAFE Updater

This is a comprehensive automation tool designed to find, process, and upload web-based games (CYOAs) to the [cyoa.cafe](https://cyoa.cafe) platform. It automates the entire pipeline, from downloading game assets to generating AI-powered descriptions and handling the final upload.

## Features

-   **Automated Processing**: Scans a list of URLs from `links.txt` for new games.
-   **Duplicate Prevention**: Checks against the `cyoa.cafe` API to avoid processing games that are already in the catalog.
-   **Full Asset Download**: Downloads the entire game project, including HTML, CSS, JavaScript, and all media assets.
-   **Intelligent Data Extraction**: Uses multiple strategies to find and parse game data, primarily looking for `project.json`.
-   **AI-Powered Content Generation**:
    -   Uses **Google Gemini Pro Vision** to analyze screenshots and generate detailed visual descriptions.
    -   Uses a model via **OpenRouter** (like Gemini Flash) to create summaries and structured JSON data for the catalog.
-   **Automated Upload**: Handles the creation of new author/tag entries and uploads the game data, cover image, and all associated files to the platform.
-   **Extensive Logging**: Keeps detailed logs for each step of the process for easy debugging.

## Project Structure

```
/
├── components/                 # Helper modules for specific tasks
│   ├── api_authors.py
│   ├── api_tags.py
│   ├── crawler.py
│   ├── game_checker.py
│   ├── js_json_extractor.py
│   ├── project_downloader.py
│   └── traffic_analyzer.py
├── prompts/                    # AI prompt templates
│   ├── Grok_description_for_catalog.md
│   └── Grok_for_sent_search.md
├── .env                        # Local environment variables (API keys, credentials)
├── .env.example                # Example environment file
├── controller.py               # The main orchestrator script
├── GameUploader.py             # Handles the final upload to the API
├── get_screenshot_puppy.js     # Node.js script to take screenshots
├── image_replacer.py           # Helper script to manually update a game's image
├── links.txt                   # Input file with game URLs
├── package.json                # Node.js dependencies
├── prepare_and_upload.py       # Prepares generated files for the uploader
├── requirements.txt            # Python dependencies
├── summarize.py                # The "brain" that calls AI APIs
└── vision_query.py             # Analyzes screenshots with Gemini Vision
```

## Installation

Follow these steps to set up the project environment.

### Prerequisites

-   **Python 3.8+**
-   **Node.js 18+** (with npm)
-   **Git**

### Step 1: Clone the Repository

Clone this project to your local machine.

```bash
git clone <your-repository-url>
cd <repository-folder>
```

### Step 2: Set Up Python Virtual Environment

It is highly recommended to use a virtual environment to manage Python dependencies.

**On macOS / Linux:**

```bash
python3 -m venv venv
source venv/bin/activate
```

**On Windows:**

```bash
python -m venv venv
.\venv\Scripts\activate
```

### Step 3: Install Python Dependencies

Install all required Python libraries using the `requirements.txt` file.

```bash
pip install -r requirements.txt
```

### Step 4: Install Node.js Dependencies

Install the required Node.js libraries for the screenshot utility.

```bash
npm install
```

### Step 5: Configure Environment Variables

This project requires API keys and credentials to function.

1.  Create a file named `.env` in the root of the project. You can do this by copying the example file:
    ```bash
    cp .env.example .env
    ```
2.  Open the `.env` file and fill in the required values:

    ```env
    # Credentials for the cyoa.cafe API
    EMAIL="your_login_email@example.com"
    PASSWORD="your_api_password"

    # API key for OpenRouter (for text generation/summarization)
    OPENROUTER_API_KEY="sk-or-v1-..."

    # API key for Google Gemini (for vision/screenshot analysis)
    GEMINI_API_KEY="AIzaSy..."

    # Optional: Used in API request headers
    YOUR_SITE_URL="http://your-site-url.com"
    YOUR_APP_NAME="CYOA_Updater"
    ```

## Usage

### 1. Prepare Input

Add the URLs of the games you want to process to the **`links.txt`** file. Each URL should be on a new line.

```
https://example.com/game1/
https://another-game.neocities.org/
```

### 2. Run the Main Controller

Execute the main controller script from your terminal. Make sure your Python virtual environment is activated.

```bash
python controller.py
```

The script will start processing the URLs from `links.txt` and log its progress to the console and to the `logs/` directory.

### Command-line Arguments

-   `--force-screenshots`: Re-generates screenshots for all games, even if they already exist.
-   `--test`: Runs the `prepare_and_upload.py` script in a "test mode", which prepares files in the `New_Games` directory but does not perform the final upload or cleanup. This is useful for debugging the preparation step.

## Helper Scripts

### `image_replacer.py`

This script is a utility for manually updating the cover image of an **existing** game in the catalog. It's useful when the original automated screenshot was suboptimal (e.g., captured a loading screen, a cookie banner, or didn't show the game's best content).

**How to use it:**

1.  Activate your virtual environment (`source venv/bin/activate`).
2.  Run the script from your terminal, providing the exact game title as an argument. Use quotes if the title contains spaces.
    ```bash
    python image_replacer.py "Name Of The Game To Update"
    ```
3.  A browser window will open, navigating to the game's URL. You will see a floating menu with "STOP" and "CONTINUE" buttons.
4.  You can now manually interact with the page: scroll, click buttons to reveal content, close pop-ups, etc. Prepare the page to show the best possible view for the cover image.
5.  When you are satisfied with the view, click the green **CONTINUE** button.
6.  The script will then take the screenshot, upload it to `cyoa.cafe`, and update both the main image and its small Base64 placeholder.

## How It Works (Workflow)

1.  **Initialization**: The `controller.py` script starts, sets up logging, and checks for prerequisites.
2.  **URL Processing Loop**: For each URL in `links.txt`:
    -   It checks if the game already exists in the `cyoa.cafe` catalog using `game_checker.py`.
    -   If it's a new game, it downloads all its assets into `downloaded_games/` using `project_downloader.py`.
3.  **Data Extraction**: It attempts to find the game's content. It first tries `crawler.py` to parse a `project.json` file. If that fails, it uses fallback methods like `js_json_extractor.py` and `traffic_analyzer.py`. The extracted text is saved to a Markdown file in the `markdown/` directory.
4.  **Visual Analysis**:
    -   `get_screenshot_puppy.js` is called to take a screenshot and save it to `screenshots/`.
    -   `vision_query.py` sends this screenshot to the Gemini Vision API to get a detailed text description.
5.  **AI Summarization**:
    -   `summarize.py` combines the extracted game text, the visual description, and data from helper scripts (`api_authors.py`, `api_tags.py`) into a detailed prompt.
    -   It calls the OpenRouter API to generate a summary (`summaries/`) and a structured JSON file for the catalog (`catalog_json/`).
6.  **Preparation & Upload**:
    -   `prepare_and_upload.py` takes the generated JSON, cleans it, and embeds the Base64 version of the screenshot.
    -   It then calls `GameUploader.py`.
    -   `GameUploader.py` communicates with the `cyoa.cafe` API, creates new authors/tags if needed, and uploads the game data and images.
7.  **Cleanup & Reporting**: After a successful upload, processed files are archived, and a final report is printed to the console and `log.txt`.

## Usage

### Basic Processing

1. Add the link in links.txt - it's better to add one game at a time

2. Type
```bash 
python controller.py
```
3. Check the tags manually on the Moderator Panel


### Screenshot Replacement

```bash
python image_replacer.py "Cyoa title from catalog"
```


## License

This project is licensed under the MIT License. See the `LICENSE` file for details.