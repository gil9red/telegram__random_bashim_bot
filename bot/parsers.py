#!/usr/bin/env python3
# -*- coding: utf-8 -*-

__author__ = 'ipetrash'


import inspect
import logging
import time

from random import randint
from threading import RLock

# pip install schedule
import schedule

from bot import db
from config import DIR
from third_party import bash_im
from third_party.notifications import send_telegram_notification_error


NEXT_CHECKED_PAGE = DIR / '_NEXT_CHECKED_PAGE.txt'


def save_next_checked_page(page: int):
    NEXT_CHECKED_PAGE.write_text(str(page))


def read_next_checked_page() -> int:
    try:
        return int(NEXT_CHECKED_PAGE.read_text())
    except:
        return bash_im.get_total_pages()


def caller_name() -> str:
    """Return the calling function's name."""
    return inspect.currentframe().f_back.f_code.co_name


# Для препятствия одновременной работы в download_random_quotes и download_new_quotes
lock = RLock()


def download_random_quotes(log: logging.Logger, dir_comics):
    prefix = f'[{caller_name()}]'
    i = 0

    while True:
        try:
            with lock:
                count = db.Quote.select().count()
                log.debug(f'{prefix} Quotes: {count}')
                t = time.perf_counter_ns()

                for quote in bash_im.get_random_quotes(log):
                    # При отсутствии, цитата будет добавлена в базу
                    db.Quote.get_from(quote)

                    # Сразу же пробуем скачать комиксы
                    quote.download_comics(dir_comics)

                elapsed_ms = (time.perf_counter_ns() - t) // 1_000_000
                log.debug(
                    f'{prefix} Added new quotes (random): %s, elapsed %s ms',
                    db.Quote.select().count() - count, elapsed_ms
                )

        except:
            log.exception(f'{prefix} Error:')

        finally:
            # 3 - 15 minutes
            minutes = randint(3, 15)
            log.debug(f'{prefix} Mini sleep: %s minutes', minutes)

            time.sleep(minutes * 60)

            i += 1
            if i == 20:
                i = 0

                # 3 - 6 hours
                minutes = randint(3 * 60, 6 * 60)
                log.debug(f'{prefix} Deep sleep: %s minutes', minutes)

                time.sleep(minutes * 60)


def download_main_page_quotes(log: logging.Logger, dir_comics):
    prefix = f'[{caller_name()}]'

    def run():
        while True:
            try:
                with lock:
                    count = db.Quote.select().count()
                    log.debug(f'{prefix} Quotes: {count}')
                    t = time.perf_counter_ns()

                    for quote in bash_im.get_main_page_quotes(log):
                        # При отсутствии, цитата будет добавлена в базу
                        db.Quote.get_from(quote)

                        # Сразу же пробуем скачать комиксы
                        quote.download_comics(dir_comics)

                    elapsed_ms = (time.perf_counter_ns() - t) // 1_000_000
                    log.debug(
                        f'{prefix} Added new quotes (main page): %s, elapsed %s ms',
                        db.Quote.select().count() - count, elapsed_ms
                    )

                break

            except Exception:
                log.exception(f'{prefix} Error:')

                log.info(f"{prefix} I'll try again in 1 minute ...")
                time.sleep(60)

    # Каждый день в 22:00
    scheduler = schedule.Scheduler()
    scheduler.every().day.at("22:00").do(run)

    while True:
        scheduler.run_pending()
        time.sleep(60)


def download_seq_page_quotes(log: logging.Logger, dir_comics):
    prefix = f'[{caller_name()}]'

    i = 0
    while True:
        try:
            page = read_next_checked_page()

            # Если дошли до последней страницы, начинаем заново
            if page < 1:
                log.debug(f'{prefix} Starting over again')
                page = bash_im.get_total_pages()

            with lock:
                count = db.Quote.select().count()
                log.debug(f'{prefix} Quotes: {count}')
                t = time.perf_counter_ns()

                for quote in bash_im.get_page_quotes(page, log):
                    # При отсутствии, цитата будет добавлена в базу
                    db.Quote.get_from(quote)

                    # Сразу же попробуем скачать комиксы
                    quote.download_comics(dir_comics)

                elapsed_ms = (time.perf_counter_ns() - t) // 1_000_000
                log.debug(
                    f'{prefix} Added new quotes (page %s): %s, elapsed %s ms',
                    page, db.Quote.select().count() - count, elapsed_ms
                )

            page -= 1
            save_next_checked_page(page)

        except Exception:
            log.exception(f'{prefix} Error:')

            log.info(f"{prefix} I'll try again in 1 minute ...")
            time.sleep(60)

        finally:
            # 3 - 15 minutes
            minutes = randint(3, 15)
            log.debug(f'{prefix} Mini sleep: %s minutes', minutes)

            time.sleep(minutes * 60)

            i += 1
            if i >= 10:
                i = 0

                # 3 - 6 hours
                minutes = randint(3 * 60, 6 * 60)
                log.debug(f'{prefix} Deep sleep: %s minutes', minutes)

                time.sleep(minutes * 60)


def run_parser_health_check(log: logging.Logger):
    prefix = f'[{caller_name()}]'

    def run():
        try:
            bash_im.parser_health_check(raise_error=True)
        except Exception as e:
            log.exception(f'{prefix} Error:')
            send_telegram_notification_error(log.name, str(e))
            db.Error.create_from(func=run_parser_health_check, e=e)

    # Каждый день в 12:00
    scheduler = schedule.Scheduler()
    scheduler.every().day.at("12:00").do(run)

    while True:
        scheduler.run_pending()
        time.sleep(60)
