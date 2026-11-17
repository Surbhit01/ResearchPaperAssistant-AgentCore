"""Send one MCP request to the Gateway as the user whose token is in $TOKEN.

    python3 scripts/call_gateway.py tools/list
    python3 scripts/call_gateway.py tools/call '{"name":"papers___search_arxiv","arguments":{"query":"rag"}}'
    TOKEN=$TOKEN2 python3 scripts/call_gateway.py tools/call '...'      # as the second user
"""
import json
import os
import sys
import urllib.error
import urllib.request

method = sys.argv[1]
params = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
token, url = os.environ.get("TOKEN", ""), os.environ.get("GATEWAY_URL", "")
if len(token) < 100 or not url:
    sys.exit("set GATEWAY_URL and TOKEN first (TOKEN is empty or too short: export TOKEN=$(python3 scripts/get_jwt.py))")

body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
request = urllib.request.Request(url, data=body, headers={
    "Authorization": f"Bearer {token}", "Content-Type": "application/json"})
try:
    with urllib.request.urlopen(request, timeout=60) as response:
        print(json.dumps(json.load(response), indent=2))
except urllib.error.HTTPError as e:
    print(f"HTTP {e.code}: {e.read().decode()}")
    sys.exit(1)
