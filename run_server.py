#!/usr/bin/env python3
"""Start the FloodGuard web dashboard.

    python run_server.py [port]

Requires only the Python standard library.
"""

import sys
from floodguard.server import create_server

DEFAULT_PORT = 8000


def main():
    port = DEFAULT_PORT
    if len(sys.argv) > 1:
        port = int(sys.argv[1])
    server = create_server(host="127.0.0.1", port=port)
    print("FloodGuard dashboard running at http://127.0.0.1:%d" % port)
    print("Press Ctrl-C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()
