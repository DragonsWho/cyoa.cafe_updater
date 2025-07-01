# components/traffic_analyzer.py

import json
import time
import logging
import requests
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class TrafficAnalyzer:
    """Analyze network traffic to find and process game data files"""
    
    def __init__(self):
        self.driver = self._init_driver()
        
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

    def _json_to_md(self, data):
        """Convert JSON data to Markdown format with flexible structure handling"""
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

    def _capture_network_traffic(self, url):
        """Capture network traffic to find JSON files"""
        try:
            self.driver.get(url)
            time.sleep(5)
            
            logs = self.driver.get_log('performance')
            json_urls = set()
            
            for log in logs:
                try:
                    message = json.loads(log['message'])
                    params = message['message']['params']
                    request = params['request']
                    
                    if 'url' in request and request['url'].endswith('.json'):
                        json_urls.add(request['url'])
                except (KeyError, json.JSONDecodeError):
                    continue
            
            return list(json_urls)
        except Exception as e:
            logger.error(f"Error capturing network traffic: {str(e)}")
            return []

    def process_url(self, url):
        """Process single URL by analyzing network traffic"""
        try:
            json_urls = self._capture_network_traffic(url)
            
            if not json_urls:
                logger.warning(f"No JSON files found for {url}")
                return None
            
            for json_url in json_urls:
                try:
                    response = requests.get(json_url)
                    if response.status_code == 200:
                        data = response.json()
                        break
                except Exception as e:
                    logger.warning(f"Failed to process JSON from {json_url}: {str(e)}")
                    continue
            else:
                logger.warning(f"No valid data found in JSON files for {url}")
                return None
            
            md_content = self._json_to_md(data)
            project_name = url.split('/')[-2]
            game_title = project_name.replace('_', ' ')
            full_md_content = f"Game URL: {url}\n\nPossible title: {game_title}\n\n{md_content}"
            
            logger.info(f"Successfully extracted content for {url}")
            return full_md_content  # Возвращаем содержимое, а не путь к файлу
            
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

def analyze_traffic(url):
    """Convenience function for standalone usage"""
    analyzer = TrafficAnalyzer()
    try:
        return analyzer.process_url(url)
    finally:
        analyzer.close()

if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print("Usage: python traffic_analyzer.py <url>")
        sys.exit(1)
        
    url = sys.argv[1]
    result = analyze_traffic(url)
    if result:
        print(f"Successfully created: {result}")
    else:
        print("Failed to process URL")
