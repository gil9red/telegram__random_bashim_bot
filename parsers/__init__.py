#!/usr/bin/env python3
# -*- coding: utf-8 -*-

__author__ = 'ipetrash'


import logging
import time

from random import randint
from threading import RLock

# pip install schedule
import schedule

import db
from config import DIR
from parsers import bash_im


NEXT_CHECKED_PAGE = DIR / '_NEXT_CHECKED_PAGE.txt'


def save_next_checked_page(page: int):
    NEXT_CHECKED_PAGE.write_text(str(page))


def read_next_checked_page() -> int:
    try:
        return int(NEXT_CHECKED_PAGE.read_text())
    except:
        return bash_im.get_total_pages()


# Для препятствия одновременной работы в download_random_quotes и download_new_quotes
lock = RLock()


def download_random_quotes(log: logging.Logger, dir_comics):
    i = 0

    while True:
        try:
            with lock:
                count = db.Quote.select().count()
                log.debug(f'{download_random_quotes.__name__}. Quotes: {count}')
                t = time.perf_counter_ns()

                for quote in bash_im.get_random_quotes(log):
                    # При отсутствии, цитата будет добавлена в базу
                    db.Quote.get_from(quote)

                    # Сразу же пробуем скачать комиксы
                    quote.download_comics(dir_comics)

                elapsed_ms = (time.perf_counter_ns() - t) // 1_000_000
                log.debug(
                    'Added new quotes (random): %s, elapsed %s ms',
                    db.Quote.select().count() - count, elapsed_ms
                )

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


def download_main_page_quotes(log: logging.Logger, dir_comics):
    def run():
        while True:
            try:
                with lock:
                    count = db.Quote.select().count()
                    log.debug(f'{download_main_page_quotes.__name__}. Quotes: {count}')
                    t = time.perf_counter_ns()

                    for quote in bash_im.get_main_page_quotes(log):
                        # При отсутствии, цитата будет добавлена в базу
                        db.Quote.get_from(quote)

                        # Сразу же пробуем скачать комиксы
                        quote.download_comics(dir_comics)

                    elapsed_ms = (time.perf_counter_ns() - t) // 1_000_000
                    log.debug(
                        'Added new quotes (main page): %s, elapsed %s ms',
                        db.Quote.select().count() - count, elapsed_ms
                    )

                break

            except Exception:
                log.exception('')

                log.info("I'll try again in 1 minute ...")
                time.sleep(60)

    # Каждый день в 22:00
    schedule.every().day.at("22:00").do(run)

    while True:
        schedule.run_pending()
        time.sleep(60)


def download_seq_page_quotes(log: logging.Logger, dir_comics):
    while True:
        i = 0
        page = read_next_checked_page()

        while page > 0:
            try:
                with lock:
                    count = db.Quote.select().count()
                    log.debug(f'{download_seq_page_quotes.__name__}. Quotes: {count}')
                    t = time.perf_counter_ns()

                    for quote in bash_im.get_page_quotes(page, log):
                        # При отсутствии, цитата будет добавлена в базу
                        db.Quote.get_from(quote)

                        # Сразу же пробуем скачать комиксы
                        quote.download_comics(dir_comics)

                    elapsed_ms = (time.perf_counter_ns() - t) // 1_000_000
                    log.debug(
                        'Added new quotes (page %s): %s, elapsed %s ms',
                        page, db.Quote.select().count() - count, elapsed_ms
                    )

                page -= 1
                save_next_checked_page(page)

            except Exception:
                log.exception('')

                log.info("I'll try again in 1 minute ...")
                time.sleep(60)

            finally:
                # 3 - 15 minutes
                minutes = randint(3, 15)
                log.debug('Mini sleep: %s minutes', minutes)

                time.sleep(minutes * 60)

                i += 1
                if i == 10:
                    i = 0

                    # 3 - 6 hours
                    minutes = randint(3 * 60, 6 * 60)
                    log.debug('Deep sleep: %s minutes', minutes)

                    time.sleep(minutes * 60)
