import json
import subprocess
import sys

checks = []
for book_id, quantity, title, unit, total in [
    (1, 2, 'Practical Python', '20.00', '40.00'),
    (2, 1, 'Small Systems', '12.99', '12.99'),
]:
    p = subprocess.run([sys.executable, '/source/app.py', str(book_id), str(quantity)],
        capture_output=True, text=True, timeout=10)
    try:
        value = json.loads(p.stdout)
        passed = p.returncode == 0 and value == dict(title=title, unit_price=unit, total=total, membership_price='5.00')
    except ValueError:
        passed = False
    checks.append(passed)
    print(json.dumps({'book_id': book_id, 'passed': passed, 'stdout': p.stdout[:4000], 'stderr': p.stderr[:4000]}))
# Component evidence for S7: the repaired wrapper reaches required-country validation.
# This is not a passing application check and does not supply a country.
sys.path.insert(0, '/source')
from client import get_book
from urllib.error import HTTPError
try:
    get_book(1)
except HTTPError as exc:
    print(json.dumps({'component': 'endpoint_reaches_country_validation',
        'passed': exc.code == 422 and 'country' in exc.read().decode()}))
except Exception:
    print(json.dumps({'component': 'endpoint_reaches_country_validation', 'passed': False}))
else:
    print(json.dumps({'component': 'endpoint_reaches_country_validation', 'passed': False}))
sys.exit(0 if all(checks) else 1)
