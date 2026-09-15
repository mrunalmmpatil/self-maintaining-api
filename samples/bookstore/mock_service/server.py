"""Versioned real HTTP fixture. No third-party runtime dependencies."""
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

SCENARIO = os.environ.get('SCENARIO', 'endpoint-rename')
VERSION = os.environ.get('API_VERSION', 'new')
BOOKS = {1: ('Practical Python', 2000), 2: ('Small Systems', 1299), 3: ('Open Handbook', 0)}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == '/health':
            return self.reply(200, {'ready': True})
        prefix = '/catalog/books/' if VERSION == 'new' and SCENARIO in ('endpoint-rename', 'mixed') else '/books/'
        if not parsed.path.startswith(prefix):
            return self.reply(404, {'error': 'route not found'})
        if VERSION == 'new' and SCENARIO in ('required-input', 'mixed') and not parse_qs(parsed.query).get('country'):
            return self.reply(422, {'error': 'country is required'})
        try:
            book_id = int(parsed.path[len(prefix):])
            title, cents = BOOKS[book_id]
        except (KeyError, ValueError):
            return self.reply(404, {'error': 'book not found'})
        result = {'id': book_id, 'title': title, 'price': cents / 100}
        if VERSION == 'new':
            if SCENARIO == 'response-field-rename':
                result['name'] = result.pop('title')
            if SCENARIO in ('nested-price', 'wrapper-price'):
                result.pop('price')
                result['pricing'] = {'amount_cents': cents, 'currency': 'USD'}
            if SCENARIO == 'optional-field':
                result['subtitle'] = 'A practical guide'
        self.reply(200, result)

    def reply(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


if __name__ == '__main__':
    HTTPServer(('0.0.0.0', 8080), Handler).serve_forever()
