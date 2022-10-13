#!/usr/bin/env python3
# -*- coding: utf-8 -*-

__author__ = 'ipetrash'


import os
import time
from threading import Thread

# pip install python-telegram-bot
from telegram.ext import Updater, Defaults

import common
from bot import commands, db
from config import TOKEN, DIR_COMICS
from common import log, log_backup
from bot.db_utils import do_backup
from bot.parsers import (
    download_random_quotes, download_main_page_quotes, download_seq_page_quotes, run_parser_health_check
)


def main():
    log.debug('Start')

    cpu_count = os.cpu_count()
    workers = cpu_count
    log.debug(f'System: CPU_COUNT={cpu_count}, WORKERS={workers}')

    updater = Updater(
        TOKEN,
        workers=workers,
        defaults=Defaults(run_async=True),
    )
    bot = updater.bot
    log.debug(f'Bot name {bot.first_name!r} ({bot.name})')

    common.BOT = bot

    commands.setup(updater)

    updater.start_polling()
    updater.idle()

    log.debug('Finish')


if __name__ == '__main__':
    # TODO: Вернуть, если https://bash.im станет доступен
    # Thread(target=download_main_page_quotes, args=[log, DIR_COMICS]).start()
    # Thread(target=download_seq_page_quotes, args=[log, DIR_COMICS]).start()
    # Thread(target=download_random_quotes, args=[log, DIR_COMICS]).start()
    # Thread(target=run_parser_health_check, args=[log]).start()
    Thread(target=do_backup, args=[log_backup]).start()

    while True:
        try:
            main()
        except Exception as e:
            log.exception('')

            db.Error.create_from(main, e)

            timeout = 15
            log.info(f'Restarting the bot after {timeout} seconds')
            time.sleep(timeout)
