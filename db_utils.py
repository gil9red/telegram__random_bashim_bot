#!/usr/bin/env python3
# -*- coding: utf-8 -*-

__author__ = 'ipetrash'


import datetime as DT
import functools
import logging
import time
import shutil
from pathlib import Path

# pip install python-telegram-bot
from telegram import Update
from telegram.ext import CallbackContext

# pip install schedule
import schedule

from config import ERROR_TEXT
from common import reply_error
from db import DB_DIR_NAME, BACKUP_DIR_NAME, User, Chat, Quote, Request, Error


def process_request(log: logging.Logger):
    def actual_decorator(func):
        @functools.wraps(func)
        def wrapper(update: Update, context: CallbackContext):
            func_name = func.__name__
            user_db = chat_db = None

            if update:
                user = update.effective_user
                chat = update.effective_chat

                user_db = User.get_from(user)
                if user_db:
                    user_db.actualize(user)

                chat_db = Chat.get_from(chat)
                if chat_db:
                    chat_db.actualize(chat)

            try:
                message = update.effective_message.text
            except:
                message = None

            try:
                query_data = update.callback_query.data
            except:
                query_data = None

            t = time.perf_counter_ns()
            result = func(update, context)
            elapsed_ms = (time.perf_counter_ns() - t) // 1_000_000

            log.debug(f'[{func.__name__}] Elapsed {elapsed_ms} ms')

            # Поддержка List[Quote] (для on_get_quotes). Это для учёта цитат среди
            # просмотренных ранее при получении группы цитат из результата поиска
            # через встроенные кнопки
            quote_dbs = []

            # Если вернулся список цитат
            if isinstance(result, list):
                for x in result:
                    if isinstance(x, Quote):
                        quote_dbs.append(x)

            elif isinstance(result, Quote):
                quote_dbs.append(result)
            else:
                # Request нужно в любом случае создать
                quote_dbs.append(None)

            for quote_db in quote_dbs:
                Request.create(
                    func_name=func_name,
                    elapsed_ms=elapsed_ms,
                    user=user_db,
                    chat=chat_db,
                    quote=quote_db,
                    message=message,
                    query_data=query_data,
                )

            return result

        return wrapper
    return actual_decorator


def catch_error(log: logging.Logger):
    def actual_decorator(func):
        @functools.wraps(func)
        def wrapper(update: Update, context: CallbackContext):
            try:
                return func(update, context)
            except Exception as e:
                log.exception('Error: %s\nUpdate: %s', context.error, update)

                Error.create_from(func, e, update)

                if update:
                    reply_error(ERROR_TEXT, update, context)

        return wrapper
    return actual_decorator


def get_user_message_repr(user: User) -> str:
    return f'''
    id: {user.id}
    first_name: {user.first_name}
    last_name: {user.last_name}
    username: {user.username}
    language_code: {user.language_code}
    last_activity: {user.last_activity}
    quotes: {user.get_total_quotes()}
    with comics: {user.get_total_quotes(with_comics=True)}
    '''.rstrip()


def db_create_backup(log: logging.Logger, backup_dir=BACKUP_DIR_NAME, date_fmt='%Y-%m-%d'):
    backup_path = Path(backup_dir)
    backup_path.mkdir(parents=True, exist_ok=True)

    zip_name = DT.datetime.today().strftime(date_fmt)
    zip_name = backup_path / zip_name

    log.debug(f'Doing create backup in: {zip_name}')

    shutil.make_archive(
        zip_name,
        'zip',
        DB_DIR_NAME
    )


def do_backup(log: logging.Logger):
    # Каждую неделю, в субботу, в 02:00 ночи
    scheduler = schedule.Scheduler()
    scheduler.every().week.saturday.at("02:00").do(db_create_backup, log)

    while True:
        scheduler.run_pending()
        time.sleep(60)
