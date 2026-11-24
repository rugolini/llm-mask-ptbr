import logging
import os

import uvicorn

from .config import build_masker, load
from .proxy import create_app


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    settings = load(os.environ.get("LLM_MASK_CONFIG"))
    options = {"secret_tools": settings.secret_tools}
    if settings.notice is not None:
        options["notice"] = settings.notice
    app = create_app(build_masker(settings), settings.upstream, settings.mode, settings.unmasked_models, **options)
    uvicorn.run(app, host=settings.host, port=settings.port, access_log=False, log_level="warning")


if __name__ == "__main__":
    main()
