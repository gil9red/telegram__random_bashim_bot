#!/usr/bin/env python3
# -*- coding: utf-8 -*-

__author__ = 'ipetrash'


import os
import time
from threading import Thread

# pip install python-telegram-bot
from telegram import Update
from telegram.ext import Updater, CallbackContext

import commands
import db
from config import TOKEN, ERROR_TEXT, DIR_COMICS
from common import log, reply_error
from db_utils import catch_error, do_backup
from parsers import download_random_quotes, download_main_page_quotes, download_seq_page_quotes


@catch_error(log)
def on_error(update: Update, context: CallbackContext):
    log.exception('Error: %s\nUpdate: %s', context.error, update)

    db.Error.create_from(on_error, context.error, update)

    if update:
        reply_error(ERROR_TEXT, update, context)


def main():
    cpu_count = os.cpu_count()
    workers = cpu_count
    log.debug('System: CPU_COUNT=%s, WORKERS=%s', cpu_count, workers)

    log.debug('Start')

    # Create the EventHandler and pass it your bot's token.
    updater = Updater(
        TOKEN,
        workers=workers,
        use_context=True
    )

    dp = updater.dispatcher
    commands.setup(dp)

    dp.add_error_handler(on_error)

    updater.start_polling()
    updater.idle()

    log.debug('Finish')


if __name__ == '__main__':
    Thread(target=download_main_page_quotes, args=[log, DIR_COMICS]).start()
    Thread(target=download_seq_page_quotes, args=[log, DIR_COMICS]).start()
    Thread(target=download_random_quotes, args=[log, DIR_COMICS]).start()
    Thread(target=do_backup, args=[log]).start()

    while True:
        try:
            main()
        except Exception as e:
            log.exception('')

            db.Error.create_from(main, e)

            timeout = 15
            log.info(f'Restarting the bot after {timeout} seconds')
            time.sleep(timeout)
