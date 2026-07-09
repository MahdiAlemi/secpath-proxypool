#!/usr/bin/env python3
"""
Proxy Importer - Entry point for importing proxies from URLs or files
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from proxy_importer.utils.importer import main

if __name__ == "__main__":
    main()
