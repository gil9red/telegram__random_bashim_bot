#!/usr/bin/env python3
# -*- coding: utf-8 -*-

__author__ = 'ipetrash'


import datetime as DT
import functools
import logging
import shutil
import time
from pathlib import Path

# pip install python-telegram-bot
from telegram import Update
from telegram.ext import CallbackContext

# pip install schedule
import schedule

from config import BACKUP_DIR_NAME, DB_DIR_NAME, DIR_COMICS, ERROR_TEXT
from common import reply_error
from bot.db import User, Chat, Quote, Request, Error
from third_party.notifications import send_telegram_notification_error


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

            log.debug(f'[{func_name}] Elapsed {elapsed_ms} ms')

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
    return f'''\
    id: {user.id}
    first_name: {user.first_name}
    last_name: {user.last_name}
    username: {user.username}
    language_code: {user.language_code}
    last_activity: {user.last_activity:%d/%m/%Y %H:%M:%S}
    quotes: {user.get_total_quotes()}
    with comics: {user.get_total_quotes(with_comics=True)}
    '''.rstrip()


def db_create_backup(
        log: logging.Logger,
        backup_dir=BACKUP_DIR_NAME,
        date_fmt='%Y-%m-%d'
):
    backup_path = Path(backup_dir)

    backup_path_db = backup_path / DB_DIR_NAME.name
    backup_path_db.mkdir(parents=True, exist_ok=True)

    backup_path_comics = backup_path / DIR_COMICS.name
    backup_path_comics.mkdir(parents=True, exist_ok=True)

    zip_name = DT.datetime.today().strftime(date_fmt)
    zip_name = backup_path_db / zip_name

    attempts = 5
    for i in range(attempts):
        try:
            log.info(f'Создание бэкапа базы данных в: {zip_name}')
            shutil.make_archive(zip_name, 'zip', DB_DIR_NAME)

            log.info(f'Создание бэкапа комиксов в: {backup_path_comics}')
            for f in DIR_COMICS.glob('*'):
                if not f.is_file():
                    continue

                backup_comics_file = backup_path_comics / f.name
                if backup_comics_file.exists():
                    continue

                log.info(f'Сохранение {backup_comics_file.name}')
                shutil.copyfile(f, backup_comics_file)

            # Всё хорошо завершилось, выходим из функции
            return

        except Exception:
            log.exception(f"Ошибка (попытка {i+1}):")
            time.sleep(30)

    # Если дошли сюда, значит не получилось сохранить бэкап
    send_telegram_notification_error(log.name, "Ошибка при создании бэкапа")


def do_backup(log: logging.Logger):
    # Каждую неделю, в субботу, в 02:00 ночи
    scheduler = schedule.Scheduler()
    scheduler.every().week.saturday.at("02:00").do(db_create_backup, log)

    while True:
        scheduler.run_pending()
        time.sleep(60)