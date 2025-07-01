# components/crawler.py

import requests
import json
import os

def json_to_md(data):
    """Convert JSON data to Markdown format"""
    md_content = []
    
    # Extract main content
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
                    # Skip image links
                    pass
    
    return "\n".join(md_content)

def crawl_url(url):
    """Process single URL: download JSON and convert to Markdown
    
    Args:
        url (str): URL to the project.json file
        
    Returns:
        str: Path to the created markdown file or None if processing failed
    """
    try:
        # Fetch JSON data
        response = requests.get(url)
        data = response.json()
        
        # Convert to Markdown
        md_content = json_to_md(data)
        
        # Generate filename from URL
        project_name = url.split('/')[-2]
        
        # Make sure markdown directory exists
        os.makedirs("markdown", exist_ok=True)
        
        md_filename = f"markdown/{project_name}.md"
        
        # Extract game title from URL
        game_title = url.split('/')[-2].replace('_', ' ')
        
        # Get game URL without 'project.json'
        game_url = '/'.join(url.split('/')[:-1]) + '/'  # Отсекаем последний сегмент и добавляем слеш
        
        # Add game URL and title (marked as possible) to the beginning of markdown content
        md_content = f"Game URL: {game_url}\n\nPossible title: {game_title}\n\n{md_content}"
        
        # Save Markdown
        with open(md_filename, 'w', encoding='utf-8') as f:
            f.write(md_content)
            
        return md_filename
        
    except requests.exceptions.RequestException as e:
        print(f"Network error processing {url}: {str(e)}")
        return None
    except json.JSONDecodeError as e:
        print(f"JSON parsing error for {url}: {str(e)}")
        return None
    except Exception as e:
        print(f"Error processing {url}: {str(e)}")
        return None

def main():
    import sys
    if len(sys.argv) != 2:
        print("Usage: python -m components.crawler <url>")
        sys.exit(1)
        
    url = sys.argv[1]
    result = crawl_url(url)
    
    if result:
        print(f"Successfully processed URL. Output saved to {result}")
    else:
        print(f"Failed to process URL: {url}")
        sys.exit(1)

if __name__ == "__main__":
    main()