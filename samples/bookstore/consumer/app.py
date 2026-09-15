import json
import sys
from decimal import Decimal
from client import book_details


def quote(book_id, quantity):
    if quantity < 0:
        raise ValueError('Quantity must be nonnegative')
    book = book_details(book_id)
    unit_price = Decimal(str(book['price']))
    # An unrelated domain value must not change when API price representation changes.
    membership = {'price': '5.00'}
    return {
        'title': book['title'],
        'unit_price': f'{unit_price:.2f}',
        'total': f'{unit_price * quantity:.2f}',
        'membership_price': membership['price'],
    }


if __name__ == '__main__':
    print(json.dumps(quote(int(sys.argv[1]), int(sys.argv[2]))))
