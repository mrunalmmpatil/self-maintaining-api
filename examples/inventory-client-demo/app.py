import json
import sys

from pricing import quote

if __name__ == "__main__":
    print(json.dumps(quote(int(sys.argv[1]), int(sys.argv[2]))))
