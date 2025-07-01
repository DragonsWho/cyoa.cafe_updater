import json
import re
import logging
import time
import requests
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class JSJsonExtractor:
    """Extract JSON data from JavaScript files"""
    
    def __init__(self):
        self.driver = self._init_driver()
        self.json_pattern = re.compile(r'Store\(\{state:\{app:(.*?)\},getters:', re.DOTALL)
        
    def _init_driver(self):
        """Initialize Chrome WebDriver with performance logging"""
        options = Options()
        options.add_argument('--headless')
        options.add_argument('--disable-gpu')
        options.set_capability('goog:loggingPrefs', {'performance': 'ALL'})
        
        try:
            return webdriver.Chrome(
                service=Service(ChromeDriverManager().install()),
                options=options
            )
        except Exception as e:
            logger.error(f"Failed to initialize WebDriver: {str(e)}")
            raise

    def _extract_json(self, js_content):
        """Extract JSON content between Store({state:{app: and },getters:"""
        try:
            match = self.json_pattern.search(js_content)
            if match:
                json_str = match.group(1).strip()
                if json_str.startswith('{') and json_str.endswith('}'):
                    return json.loads(json_str)
                else:
                    logger.error(f"Extracted content is not a valid JSON object: {json_str[:100]}...")
                    return None
            logger.warning("No JSON found matching the pattern in JS content")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode JSON: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error extracting JSON: {str(e)}")
            return None

    def _json_to_md(self, data):
        """Convert JSON data to Markdown format"""
        md_content = []
        
        if isinstance(data, dict):
            if 'rows' in data:
                for row in data['rows']:
                    if 'titleText' in row:
                        md_content.append(f"## {row.get('title', '')}\n")
                        md_content.append(f"{row['titleText']}\n")
                    
                    if 'objects' in row:
                        for obj in row['objects']:
                            if 'title' in obj:
                                md_content.append(f"### {obj['title']}\n")
                            if 'text' in obj:
                                md_content.append(f"{obj['text']}\n")
            elif 'content' in data:
                md_content.append(f"# {data.get('title', 'Untitled')}\n")
                md_content.append(f"{data['content']}\n")
            elif 'sections' in data:
                for section in data['sections']:
                    md_content.append(f"## {section.get('title', '')}\n")
                    md_content.append(f"{section.get('text', '')}\n")
            else:
                for key, value in data.items():
                    if isinstance(value, str):
                        md_content.append(f"## {key}\n")
                        md_content.append(f"{value}\n")
        
        return "\n".join(md_content)

    def _capture_js_files(self, url):
        """Capture all loaded .js files"""
        try:
            self.driver.get(url)
            time.sleep(5)
            
            logs = self.driver.get_log('performance')
            js_urls = set()
            
            for log in logs:
                try:
                    message = json.loads(log['message'])
                    params = message['message']['params']
                    request = params['request']
                    
                    if 'url' in request and request['url'].endswith('.js'):
                        js_urls.add(request['url'])
                except (KeyError, json.JSONDecodeError):
                    continue
            
            return list(js_urls)
        except Exception as e:
            logger.error(f"Error capturing JS files: {str(e)}")
            return []

    def process_url(self, url):
        """Process single URL by extracting JSON from JS files"""
        try:
            js_urls = self._capture_js_files(url)
            
            if not js_urls:
                logger.warning(f"No JS files found for {url}")
                return None
            
            for js_url in js_urls:
                try:
                    response = requests.get(js_url)
                    if response.status_code == 200:
                        json_data = self._extract_json(response.text)
                        if json_data:
                            break
                except Exception as e:
                    logger.warning(f"Failed to process JS from {js_url}: {str(e)}")
                    continue
            else:
                logger.warning(f"No valid JSON data found in JS files for {url}")
                return None
            
            md_content = self._json_to_md(json_data)
            project_name = url.split('/')[-2]
            game_title = project_name.replace('_', ' ')
            full_md_content = f"Game URL: {url}\n\nPossible title: {game_title}\n\n{md_content}"
            
            logger.info(f"Successfully extracted content for {url}")
            return full_md_content
            
        except Exception as e:
            logger.error(f"Error processing {url}: {str(e)}")
            return None

    def close(self):
        """Clean up resources"""
        try:
            if self.driver:
                self.driver.quit()
        except Exception as e:
            logger.error(f"Error closing WebDriver: {str(e)}")

def extract_js_json(url):
    """Convenience function for standalone usage"""
    extractor = JSJsonExtractor()
    try:
        return extractor.process_url(url)
    finally:
        extractor.close()