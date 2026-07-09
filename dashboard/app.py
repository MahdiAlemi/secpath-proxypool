#!/usr/bin/env python3
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dashboard import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5003, debug=False)
