"""Event server main"""

from pathlib import Path
import argparse
import asyncio
import contextlib
import logging.config
import sys

import appdirs

from hat import aio
from hat import json

from hat.mariner import common
from hat.mariner.server.server import create_server


mlog: logging.Logger = logging.getLogger('hat.mariner.server.main')
"""Module logger"""

user_conf_dir: Path = Path(appdirs.user_config_dir('hat'))
"""User configuration directory path"""


def create_argument_parser() -> argparse.ArgumentParser:
    """Create argument parser"""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--conf', metavar='PATH', type=Path, default=None,
        help="configuration defined by hat-mariner://server.yaml "
             "(default $XDG_CONFIG_HOME/hat/mariner.{yaml|yml|toml|json})")
    return parser


def main():
    """Event Server"""
    parser = create_argument_parser()
    args = parser.parse_args()
    conf = json.read_conf(args.conf, user_conf_dir / 'mariner')
    sync_main(conf)


def sync_main(conf: json.Data):
    """Sync main entry point"""
    aio.init_asyncio()

    validator = json.DefaultSchemaValidator(common.json_schema_repo)
    validator.validate('hat-mariner://server.yaml', conf)

    log_conf = conf.get('log')
    if log_conf:
        logging.config.dictConfig(log_conf)

    with contextlib.suppress(asyncio.CancelledError):
        aio.run_asyncio(async_main(conf))


async def async_main(conf: json.Data):
    """Async main entry point"""
    srv = await create_server(conf)

    try:
        await srv.wait_closing()

    finally:
        await aio.uncancellable(srv.async_close())


if __name__ == '__main__':
    sys.argv[0] = 'hat-mariner-server'
    sys.exit(main())
