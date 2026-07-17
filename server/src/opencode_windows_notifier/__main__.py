from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Sequence

import uvicorn
from pydantic import ValidationError

from .app import create_app
from .config import ConfigState, default_config_path, load_server_config
from .notifier import WindowsNotifier


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Receive OpenCode events from WSL and notify Windows")
    parser.add_argument("--config", type=Path, default=default_config_path())
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    try:
        config = load_server_config(args.config)
        state = ConfigState(args.config, config)
        notifier = WindowsNotifier()
        app = create_app(state, notifier)
    except ValidationError as error:
        first_error = error.errors(include_input=False)[0]
        location = ".".join(str(part) for part in first_error["loc"])
        logging.error("Invalid configuration at %s: %s: %s", args.config, location, first_error["msg"])
        return 2
    except (OSError, ValueError) as error:
        logging.error("Cannot start from configuration %s: %s", args.config, error)
        return 2

    logging.info("Listening on http://%s:%s", config.listen_host, config.listen_port)
    if config.listen_host == "0.0.0.0":
        logging.warning("Restrict port %s to the WSL network with Windows Firewall", config.listen_port)
    uvicorn.run(app, host=config.listen_host, port=config.listen_port, workers=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
