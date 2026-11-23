import logging
import os

import uvicorn

from .config import build_masker, load
from .proxy import create_app


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings = load(os.environ.get("LLM_MASK_CONFIG"))
    app = create_app(build_masker(settings), settings.upstream, settings.mode, settings.unmasked_models)
    uvicorn.run(app, host=settings.host, port=settings.port, access_log=False, log_level="warning")


if __name__ == "__main__":
    main()
