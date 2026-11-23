#!/usr/bin/env python3
"""stdio fixture. All data belongs to the test HOME."""
import json
import os
from pathlib import Path
import sys
import time

root = Path.home()
if sys.argv[1:3] == ["exec", "resume"]:
    with (root / "sent").open("a") as out:
        print(json.dumps([os.getcwd(), *sys.argv[1:]]), file=out)
    while (root / "hold").exists():
        time.sleep(0.02)
    print("PRIVATE-OUTPUT", file=sys.stderr)
    sys.exit(int((root / "exit").read_text()) if (root / "exit").exists() else 0)

assert sys.argv[1:] == ["app-server", "--stdio"]
ready = False
reads = 0
for line in sys.stdin:
    msg = json.loads(line)
    method = msg["method"]
    params = msg["params"]
    opts = json.loads((root / "scenario").read_text())
    if method == "initialize":
        result = {}
    elif method == "initialized":
        ready = True
        continue
    else:
        assert ready
        if method == "account/read":
            result = {"account": {"type": opts.get("account", "chatgpt")}}
        elif method == "thread/read":
            assert params["includeTurns"] is False
            result = {"thread": {"cwd": str(root / "project"), "id": params["threadId"]}}
        elif method == "thread/turns/list":
            assert params == dict(threadId=opts["sid"], limit=1, itemsView="notLoaded",
                                  sortDirection="desc")
            turns = opts["turns"]
            result = {"data": turns[min(reads, len(turns)-1):min(reads, len(turns)-1)+1]}
            reads += 1
        elif method == "account/rateLimits/read":
            if opts.get("error"):
                print(json.dumps(dict(id=msg["id"], error=opts["error"])), flush=True)
                continue
            result = opts["limits"]
        else:
            raise AssertionError(method)
    print(json.dumps(dict(id=msg["id"] + 100, result="wrong response")))
    print(json.dumps(dict(method="notice", params={})))
    print(json.dumps(dict(id=msg["id"], result=result)), flush=True)
