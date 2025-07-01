# components/api_authors.py

import os
from dotenv import load_dotenv
import requests

load_dotenv()

class AuthorLister:
    def __init__(self):
        self.base_url = 'https://cyoa.cafe/api'
        self.email = os.getenv('EMAIL')
        self.password = os.getenv('PASSWORD')
        self.token = None
        
    def login(self):
        """Authenticate with the API"""
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
    
    def get_all_authors(self):
        """Get all existing authors and return as a comma-separated list"""
        try:
            if not self.token:
                raise Exception("Not authenticated")
                
            headers = {
                'Authorization': self.token
            }
            
            # Get all authors (with pagination)
            all_authors = []
            page = 1
            per_page = 200
            
            while True:
                response = requests.get(
                    f'{self.base_url}/collections/authors/records',
                    headers=headers,
                    params={'page': page, 'perPage': per_page}
                )
                response.raise_for_status()
                
                data = response.json()
                authors_chunk = data.get('items', [])
                all_authors.extend(authors_chunk)
                
                # Check if there are more pages
                if len(authors_chunk) < per_page:
                    break
                    
                page += 1
            
            # Extract author names
            author_names = [author['name'] for author in all_authors]
            
            # Sort alphabetically
            author_names.sort()
            
            # Return comma-separated list
            return ", ".join(author_names)
            
        except Exception:
            return ""

def main():
    lister = AuthorLister()
    
    # Authenticate
    if lister.login():
        # Get and print authors
        authors_list = lister.get_all_authors()
        print(authors_list)

if __name__ == "__main__":
    main()