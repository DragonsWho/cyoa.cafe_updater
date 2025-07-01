import subprocess
import sys
import datetime
import os
import time
import logging
import traceback
import asyncio
import concurrent.futures
import random
import json
from components.traffic_analyzer import TrafficAnalyzer
from components.js_json_extractor import extract_js_json
from components.crawler import crawl_url, json_to_md
from components.game_checker import GameChecker
from components.project_downloader import crawl_and_download, create_session
from urllib.parse import urlparse
import base64
from io import BytesIO
from PIL import Image

def setup_logging():
    os.makedirs("logs", exist_ok=True)
    date_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[
            logging.FileHandler(f"logs/process_{date_str}.log"),
            logging.StreamHandler(sys.stdout)
        ]
    )

    logging.info("Process started")

    return logging.getLogger()

def run_script(script_name, args=None):
    if not os.path.exists(script_name):
        logger.error(f"Script file not found: {script_name}")
        return False, "", f"File not found: {script_name}"

    try:
        if script_name.endswith('.js'):
            command = ['node', script_name]
        else:
            command = [sys.executable, script_name]

        if args:
            command.extend(args.split())

        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        output_lines = []
        error_lines = []

        def process_output(stream, prefix, output_list):
            for line in stream:
                line = line.strip()
                if line:
                    output_list.append(line)

        process_output(process.stdout, "OUTPUT", output_lines)
        process_output(process.stderr, "ERROR", error_lines)

        process.wait()

        output = "\n".join(output_lines)
        error = "\n".join(error_lines)

        if process.returncode != 0:
            logger.error(f"Script returned non-zero exit code: {process.returncode}")
            return False, output, error

        return True, output, error

    except subprocess.TimeoutExpired:
        return False, "", "Timeout expired"
    except Exception as e:
        logger.error(f"Error running script: {script_name}")
        return False, "", str(e)

async def run_script_async(script_name, args=None, max_retries=3, retry_delay=5):
    attempt = 0
    last_error = ""

    while attempt < max_retries:
        attempt += 1

        try:
            with concurrent.futures.ThreadPoolExecutor() as pool:
                success, output, error = await asyncio.get_event_loop().run_in_executor(
                    pool, run_script, script_name, args
                )

                if success:
                    return success, output, error

                last_error = error

                if attempt < max_retries:
                    jitter = random.uniform(0.7, 1.3)
                    delay = retry_delay * jitter
                    await asyncio.sleep(delay)

        except Exception as e:
            last_error = str(e)

            if attempt < max_retries:
                jitter = random.uniform(0.7, 1.3)
                delay = retry_delay * jitter
                await asyncio.sleep(delay)

    logger.error(f"Script {script_name} failed after {max_retries} attempts. Last error: {last_error}")
    return False, "", last_error

def check_prerequisites():
    prerequisites_met = True

    for directory in ["markdown", "summaries", "screenshots"]:
        if not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)

    if not os.path.exists("links.txt"):
        logger.error("links.txt file not found!")
        prerequisites_met = False
    else:
        with open("links.txt", "r") as f:
            urls = [line.strip() for line in f if line.strip()]
            if not urls:
                logger.error("links.txt file is empty!")
                prerequisites_met = False

    try:
        result = subprocess.run(["node", "--version"], 
                               stdout=subprocess.PIPE, 
                               stderr=subprocess.PIPE, 
                               text=True)
        if result.returncode != 0:
            logger.error("Node.js not found! Required for JavaScript scripts.")
            prerequisites_met = False
    except:
        logger.error("Error checking Node.js. Make sure it's installed.")
        prerequisites_met = False

    return prerequisites_met

def normalize_url(url):
    url = url.rstrip('/')
    if url.endswith('/index.html'):
        url = url[:-len('/index.html')]
    return f"{url}/project.json"

async def create_screenshot(base_url, project_name, screenshot_semaphore, force_screenshots=False, max_retries=3):
    async with screenshot_semaphore:
        webp_path = f"screenshots/{project_name}.webp"
        base64_path = f"screenshots/{project_name}_base64.txt"
        
        if not force_screenshots and os.path.exists(webp_path):
            file_size = os.path.getsize(webp_path)
            if file_size > 0:
                logger.info(f"Using existing screenshot: {webp_path}")
                if os.path.exists(base64_path):
                    logger.info(f"Using existing base64: {base64_path}")
                    return True, "Existing screenshot and base64 used", "" 
            else:
                logger.warning(f"Found empty screenshot file: {webp_path}, regenerating")
        
        logger.info(f"Generating new screenshot for {base_url}")
        success, output, error = await run_script_async("get_screenshoot_puppy.js", base_url, max_retries=max_retries)
        
        if success and os.path.exists(webp_path):
            logger.info(f"Screenshot successfully created: {webp_path}")
            try:
                with Image.open(webp_path) as img:
                    target_width = 100
                    target_height = 133
                    source_aspect = img.width / img.height
                    
                    if source_aspect > target_width / target_height:
                        scale_height = int(target_width / source_aspect)
                        scale_width = target_width
                    else:
                        scale_width = int(target_height * source_aspect)
                        scale_height = target_height
                    
                    resized_img = img.resize((scale_width, scale_height), Image.Resampling.LANCZOS)
                    buffer = BytesIO()
                    resized_img.save(buffer, format="WEBP", quality=40, lossless=False)
                    webp_bytes = buffer.getvalue()
                    base64_string = f"data:image/webp;base64,{base64.b64encode(webp_bytes).decode('utf-8')}"
                    
                    with open(base64_path, 'w', encoding='utf-8') as f:
                        f.write(base64_string)
                    logger.info(f"Base64 version created and saved: {base64_path}")
            except Exception as e:
                logger.error(f"Failed to create base64 version for {webp_path}: {str(e)}")
                return True, output, f"Generated screenshot but failed to create base64: {str(e)}"
            return True, output, ""
        else:
            logger.error(f"Screenshot generation failed for {base_url}: {error}")
            return success, output, error

async def main_async(force_screenshots=False):
    MAX_CONCURRENT_SCREENSHOTS = 5
    MAX_RETRIES = 3

    if not check_prerequisites():
        logger.error("Prerequisites check failed. Please fix the issues above.")
        return

    game_checker = GameChecker()
    if not game_checker.login():
        logger.error("Failed to authenticate with GameChecker. Aborting.")
        return
    game_checker.load_existing_games()

    logger.info("Starting main processing loop")

    failed_urls = []
    visual_analysis_failures = []
    processed_urls = []
    skipped_urls = []
    newly_processed_urls = []
 
    download_session = create_session()
     
    downloaded_games_dir = "downloaded_games"
    os.makedirs(downloaded_games_dir, exist_ok=True)

    try:
        with open('links.txt', 'r') as f:
            urls = [line.strip() for line in f if line.strip()]
        logger.info(f"Loaded {len(urls)} URLs from links.txt")
    except Exception as e:
        logger.error(f"Error reading links.txt: {str(e)}")
        return

    screenshot_semaphore = asyncio.Semaphore(MAX_CONCURRENT_SCREENSHOTS)
    
    for index, url in enumerate(urls, 1):
        logger.info(f"Processing URL {index}/{len(urls)}: {url}")
 
        parsed_url = urlparse(url)
        domain = parsed_url.netloc
        path_parts = parsed_url.path.strip('/').split('/')
        game_name = path_parts[-1] if path_parts else ''
        download_path = os.path.join(downloaded_games_dir, f"{domain}/{game_name}")
 
        logger.info(f"Downloading game to {download_path}")
        completed, downloaded, failed = crawl_and_download(
            url,
            download_path,
            session=download_session,
            max_workers=5
        )
        logger.info(f"Download result: Processed {completed} files, Downloaded {downloaded}, Failed {failed}")
 
        if game_checker.game_exists(url):
            logger.info(f"Skipping URL {url} as it already exists in the catalog")
            skipped_urls.append(url)
            processed_urls.append(url)
            continue

        try:
            project_json_url = normalize_url(url)
            project_name = url.split('/')[-2]
            md_file = f"{project_name}.md"
            md_path = f"markdown/{md_file}"
 
            local_json_path = os.path.join(download_path, "project.json")
            if os.path.exists(local_json_path):
                logger.info(f"Using local project.json from {local_json_path}")
                with open(local_json_path, 'r', encoding='utf-8') as f:
                    json_data = json.load(f)
                md_content = json_to_md(json_data)
                os.makedirs("markdown", exist_ok=True)
                with open(md_path, 'w', encoding='utf-8') as f:
                    game_title = project_name.replace('_', ' ')
                    game_url = url
                    f.write(f"Game URL: {game_url}\n\nPossible title: {game_title}\n\n{md_content}")
            else: 
                logger.warning(f"Local project.json not found at {local_json_path}, falling back to network methods")
                if crawl_url(project_json_url):
                    logger.info(f"Text extracted via crawl_url for {url}")
                else:
                    text_content = None
                    result = extract_js_json(url)
                    if result:
                        text_content = result
                        logger.info(f"Text extracted via extract_js_json for {url}")
                    else:
                        analyzer = TrafficAnalyzer()
                        try:
                            result = analyzer.process_url(url)
                            if result:
                                text_content = result
                                logger.info(f"Text extracted via TrafficAnalyzer for {url}")
                        finally:
                            analyzer.close()

                    if text_content:
                        os.makedirs("markdown", exist_ok=True)
                        with open(md_path, 'w', encoding='utf-8') as f:
                            f.write(text_content)
                    else:
                        logger.error(f"All processing methods failed for URL: {url}")
                        failed_urls.append(url)
                        continue

            processed_urls.append(url)
            newly_processed_urls.append(url)

            base_url = normalize_url(url).replace('/project.json', '/')

            success, output, error = await create_screenshot(base_url, project_name, screenshot_semaphore, force_screenshots, MAX_RETRIES)
            webp_path = f"screenshots/{project_name}.webp"
            if not success:
                logger.error(f"Screenshot processing failed for {base_url}: {error}")
                visual_analysis_failures.append(base_url)
            elif not os.path.exists(webp_path):
                logger.error(f"Screenshot file not found after processing: {webp_path}")
                visual_analysis_failures.append(base_url)

            logger.info(f"Running summarization for {md_file} in sent_search mode")
            success, output, error = await run_script_async(
                "summarize.py", 
                f"{md_file} --mode sent_search", 
                max_retries=MAX_RETRIES
            )
            if not success:
                logger.error(f"Summarization failed for {url}: {error}")

            logger.info("Pausing for 0.5s before next summarization...")
            await asyncio.sleep(0.5)

            logger.info(f"Running summarization for {md_file} in catalog mode")
            success, output, error = await run_script_async(
                "summarize.py", 
                f"{md_file} --mode catalog", 
                max_retries=MAX_RETRIES
            )
            if not success:
                logger.error(f"Catalog summarization failed for {url}: {error}")

        except Exception as e:
            logger.error(f"Unhandled exception processing URL {url}: {str(e)}")
            failed_urls.append(url)
 
    download_session.close()
 
    if newly_processed_urls:
        test_mode = '--test' in sys.argv
        logger.info(f"Running prepare_and_upload.py in {'test' if test_mode else 'live'} mode")
        upload_args = " --test" if test_mode else ""
        success, output, error = await run_script_async(
            "prepare_and_upload.py",
            upload_args,
            max_retries=MAX_RETRIES
        )
        if not success:
            logger.error(f"prepare_and_upload.py failed: {error}")
        else:
            logger.info("prepare_and_upload.py completed successfully")
    else:
        logger.info("No new URLs processed. Skipping prepare_and_upload.py execution.")
 
    logger.info("Generating final report")
    timestamp = datetime.datetime.now().strftime('[%Y-%m-%d %H:%M:%S]')

    report = [
        f"\n{timestamp} Processing summary:",
        f"  Total URLs processed: {len(urls)}",
        f"  Successfully processed: {len(processed_urls)}",
        f"  Newly processed: {len(newly_processed_urls)}",
        f"  Skipped (already in catalog): {len(skipped_urls)}",
        f"  Failed to process: {len(failed_urls)}",
        f"  Visual analysis failures: {len(visual_analysis_failures)}"
    ]

    if failed_urls:
        report.append("  Failed URLs:")
        for url in failed_urls:
            report.append(f"    - {url}")

    if visual_analysis_failures:
        report.append("  Visual analysis failed URLs (VPN required):")
        for url in visual_analysis_failures:
            report.append(f"    - {url}")

    if skipped_urls:
        report.append("  Skipped URLs (already in catalog):")
        for url in skipped_urls:
            report.append(f"    - {url}")

    if newly_processed_urls:
        report.append("  Newly processed URLs:")
        for url in newly_processed_urls:
            report.append(f"    - {url}")

    for line in report:
        logger.info(line)

    with open('log.txt', 'a') as log_file:
        for line in report:
            log_file.write(f"{line}\n")

    print("\n=== Processing Report ===")
    for line in report:
        print(line)

    logger.info("Process completed")

def main():
    force_screenshots = '--force-screenshots' in sys.argv
    asyncio.run(main_async(force_screenshots))

if __name__ == "__main__":
    logger = setup_logging()

    try:
        main()
    except Exception as e:
        logger.critical("Unhandled exception in main process")
        logger.critical(str(e))
        logger.critical(traceback.format_exc())
        print("\nCRITICAL ERROR: Process failed. See logs for details.")