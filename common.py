#!/usr/bin/env python3
# -*- coding: utf-8 -*-

__author__ = 'ipetrash'


import functools
import logging
import time
import sys
from pathlib import Path
from random import randint

from bash_im import get_random_quotes_list
import db


def get_logger(file_name: str, dir_name='logs'):
    dir_name = Path(dir_name).resolve()
    dir_name.mkdir(parents=True, exist_ok=True)

    file_name = str(dir_name / Path(file_name).resolve().name) + '.log'

    log = logging.getLogger(__name__)
    log.setLevel(logging.DEBUG)

    formatter = logging.Formatter('[%(asctime)s] %(filename)s[LINE:%(lineno)d] %(levelname)-8s %(message)s')

    fh = logging.FileHandler(file_name, encoding='utf-8')
    fh.setLevel(logging.DEBUG)

    ch = logging.StreamHandler(stream=sys.stdout)
    ch.setLevel(logging.DEBUG)

    fh.setFormatter(formatter)
    ch.setFormatter(formatter)

    log.addHandler(fh)
    log.addHandler(ch)

    return log


def log_func(logger: logging.Logger):
    def actual_decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            msg = ''
            if args and args[0]:
                update = args[0]

                chat_id = user_id = first_name = last_name = username = language_code = None

                if update.effective_chat:
                    chat_id = update.effective_chat.id

                if update.effective_user:
                    user_id = update.effective_user.id
                    first_name = update.effective_user.first_name
                    last_name = update.effective_user.last_name
                    username = update.effective_user.username
                    language_code = update.effective_user.language_code

                msg = f'[chat_id={chat_id}, user_id={user_id}, ' \
                      f'first_name={first_name!r}, last_name={last_name!r}, ' \
                      f'username={username!r}, language_code={language_code}]'

            logger.debug(f'Start {func.__name__}{msg}')
            t = time.perf_counter_ns()
            result = func(*args, **kwargs)
            logger.debug(f'Finish {func.__name__}. Elapsed {(time.perf_counter_ns() - t) // 1_000_000} ms')

            return result

        return wrapper
    return actual_decorator


def download_more_quotes(log, dir_comics):
    i = 0

    while True:
        try:
            count = db.Quote.select().count()
            log.debug('download_more_quotes, quotes: %s', count)
            t = time.perf_counter_ns()

            for quote in get_random_quotes_list(log):
                db.Quote.get_from(quote)

                # Сразу же пробуем скачать комиксы
                quote.download_comics(dir_comics)

            elapsed_ms = (time.perf_counter_ns() - t) // 1_000_000
            log.debug('Added new quotes: %s, elapsed %s ms', db.Quote.select().count() - count, elapsed_ms)

        except:
            log.exception('')

        finally:
            # 3 - 15 minutes
            minutes = randint(3, 15)
            log.debug('Mini sleep: %s minutes', minutes)

            time.sleep(minutes * 60)

            i += 1
            if i == 20:
                i = 0

                # 3 - 6 hours
                minutes = randint(3 * 60, 6 * 60)
                log.debug('Deep sleep: %s minutes', minutes)

                time.sleep(minutes * 60)
