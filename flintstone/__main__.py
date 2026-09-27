"""Entry point: ``python -m flintstone`` (runs the server) or ``python -m flintstone push ...``."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
