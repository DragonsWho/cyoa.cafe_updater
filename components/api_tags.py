# components/api_tags.py

import os
import json
from dotenv import load_dotenv
import requests

load_dotenv()

class TagCategoriesLister:
    def __init__(self):
        self.base_url = 'https://cyoa.cafe/api'
        self.email = os.getenv('EMAIL')
        self.password = os.getenv('PASSWORD')
        self.token = None
        self.existing_tags = {}

    def login(self):
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
            return True
        except Exception:
            return False

    def get_all_tags(self):
        try:
            if not self.token:
                return False

            headers = {
                'Authorization': self.token
            }
            
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
            
            for tag in all_tags:
                self.existing_tags[tag['id']] = {
                    'name': tag['name']
                }
            
            return True
        except Exception:
            return False

    def get_tag_categories(self):
        try:
            if not self.token:
                return None

            if not self.existing_tags:
                self.get_all_tags()
                
            headers = {
                'Authorization': self.token
            }
            
            response = requests.get(
                f'{self.base_url}/collections/tag_categories/records',
                headers=headers,
                params={'perPage': 100}
            )
            response.raise_for_status()
            
            categories_data = response.json().get('items', [])
            
            export_data = []
            
            for category in categories_data:
                cat_data = {
                    'category_name': category['name'],
                    'tags': []
                }
                
                tag_ids = category.get('tags', [])
                for tag_id in tag_ids:
                    if tag_id in self.existing_tags:
                        cat_data['tags'].append(self.existing_tags[tag_id]['name'])
                
                export_data.append(cat_data)
            
            categorized_tag_ids = set()
            for category in categories_data:
                categorized_tag_ids.update(category.get('tags', []))
            
            uncategorized_tags = []
            for tag_id, tag_info in self.existing_tags.items():
                if tag_id not in categorized_tag_ids:
                    uncategorized_tags.append(tag_info['name'])
            
            if uncategorized_tags:
                export_data.append({
                    'category_name': 'Uncategorized',
                    'tags': uncategorized_tags
                })
            
            return export_data
        except Exception:
            return None

def main():
    lister = TagCategoriesLister()
    
    if lister.login():
        categories = lister.get_tag_categories()
        if categories:
            print(json.dumps(categories, ensure_ascii=False))

if __name__ == "__main__":
    main()