#!/usr/bin/env python3
# -*- coding: utf-8 -*-

__author__ = 'ipetrash'


import datetime as DT
import functools
import logging
import time
from pathlib import Path
import shutil

# pip install python-telegram-bot
from telegram import Update
from telegram.ext import CallbackContext

# pip install schedule
import schedule

from config import ERROR_TEXT
from db import DB_DIR_NAME, User, Chat, Quote, Request, Error


def process_request(func):
    @functools.wraps(func)
    def wrapper(update: Update, context: CallbackContext):
        user_db = chat_db = quote_db = None
        if update:
            user = update.effective_user
            chat = update.effective_chat

            user_db = User.get_from(user)
            if user_db:
                user_db.actualize(user)

            chat_db = Chat.get_from(chat)
            if chat_db:
                chat_db.actualize(chat)

        t = time.perf_counter_ns()

        result = func(update, context)

        elapsed_ms = (time.perf_counter_ns() - t) // 1_000_000

        if isinstance(result, Quote):
            quote_db = result

        Request.create(
            func_name=func.__name__,
            elapsed_ms=elapsed_ms,
            user=user_db,
            chat=chat_db,
            quote=quote_db
        )

        return result
    return wrapper


def catch_error(logger: logging.Logger):
    def actual_decorator(func):
        @functools.wraps(func)
        def wrapper(update: Update, context: CallbackContext):
            try:
                return func(update, context)
            except Exception as e:
                logger.exception('Error: %s\nUpdate: %s', context.error, update)

                Error.create_from(func, e, update)

                if update:
                    update.effective_message.reply_text(ERROR_TEXT)

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
    '''.rstrip()


def db_create_backup(logger: logging.Logger, backup_dir='backup', date_fmt='%d%m%y'):
    backup_path = Path(backup_dir)
    backup_path.mkdir(parents=True, exist_ok=True)

    zip_name = DT.datetime.today().strftime(date_fmt)
    zip_name = backup_path / zip_name

    logger.debug(f'Doing create backup in: {zip_name}')

    shutil.make_archive(
        zip_name,
        'zip',
        DB_DIR_NAME
    )


def do_backup(logger: logging.Logger):
    # Каждую неделю, в пятницу, в 02:00
    schedule\
        .every().week\
        .friday.at("02:00")\
        .do(
            lambda: db_create_backup(logger)
        )

    while True:
        schedule.run_pending()
        time.sleep(60)
