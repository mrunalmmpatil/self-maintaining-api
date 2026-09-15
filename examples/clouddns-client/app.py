import json
import sys

from zones import zone_summary

if __name__ == "__main__":
    print(json.dumps(zone_summary(sys.argv[1])))
