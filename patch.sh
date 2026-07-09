#!/bin/bash
cd /data/build

# 1. proxy_server/config.py
sed -i 's/parser.add_argument("--rotate",/parser.add_argument("--w_latency", type=float, default=0.4, help="Weight for latency cost")\n    parser.add_argument("--w_fail", type=float, default=0.4, help="Weight for failure cost")\n    parser.add_argument("--rotate",/' proxy_server/config.py

# 2. proxy_server/server/proxy_store.py
sed -i 's/if cf < min_c or cf > max_c:/if has_cost_filter and (cf < min_c or cf > max_c) or (not has_cost_filter and cf < min_c):/' proxy_server/server/proxy_store.py
# Let's fix the first occurrence properly (which was raising the exception when cost is None)
# Actually, the sed above might hit both. Let's do it with python to be exact.
