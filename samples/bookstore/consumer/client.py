import json
import os
from urllib.request import urlopen


def get_book(book_id):
    base = os.environ.get('BOOKSTORE_URL', 'http://mock:8080')
    with urlopen(f'{base}/books/{book_id}', timeout=5) as response:
        return json.load(response)


def book_details(book_id):
    book = get_book(book_id)
    return {'title': book['title'], 'price': book['price']}
