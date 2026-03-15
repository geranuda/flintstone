"""Entry point for running Flintstone: python -m flintstone"""

import uvicorn

from .config import settings


def main():
    uvicorn.run(
        "flintstone.app:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )


if __name__ == "__main__":
    main()
