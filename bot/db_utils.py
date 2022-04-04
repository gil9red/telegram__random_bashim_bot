#!/usr/bin/env python3
# -*- coding: utf-8 -*-

__author__ = 'ipetrash'


import datetime as DT
import functools
import html
import logging
import shutil
import time
from pathlib import Path

# pip install python-telegram-bot
from typing import Union

from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import CallbackContext

# pip install schedule
import schedule

from bot import db
from config import BACKUP_DIR_NAME, DB_DIR_NAME, DIR_COMICS, ERROR_TEXT
from common import reply_error, reply_info, get_date_time_str
from bot.db import User, Chat, Quote, Request, Error
from third_party import bash_im
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
    last_activity: {get_date_time_str(user.last_activity)}
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


def update_quote(
        quote_id: int,
        update: Update = None,
        context: CallbackContext = None,
        log: logging.Logger = None,
):
    need_reply = update and context

    quote_bashim = bash_im.Quote.parse_from(quote_id)
    if not quote_bashim:
        text = f'Цитаты #{quote_id} на сайте нет'
        log and log.info(text)
        need_reply and reply_error(text, update, context)
        return

    quote_db: db.Quote = db.Quote.get_or_none(quote_id)
    if not quote_db:
        log and log.info(f'Цитаты #{quote_id} в базе нет, будет создание цитаты')

        # При отсутствии, цитата будет добавлена в базу
        db.Quote.get_from(quote_bashim)

        # Сразу же пробуем скачать комиксы
        quote_bashim.download_comics(DIR_COMICS)

        text = f'Цитата #{quote_id} добавлена в базу'
        log and log.info(text)
        need_reply and reply_info(text, update, context)

    else:
        modified_list = []

        if quote_db.text != quote_bashim.text:
            quote_db.text = quote_bashim.text
            modified_list.append('текст')

        # Пробуем скачать комиксы
        quote_bashim.download_comics(DIR_COMICS)

        if modified_list:
            quote_db.modification_date = DT.date.today()
            quote_db.save()

            text = f'Цитата #{quote_id} обновлена ({", ".join(modified_list)})'
            log and log.info(text)
            need_reply and reply_info(text, update, context)

        else:
            text = f'Нет изменений в цитате #{quote_id}'
            log and log.info(text)
            need_reply and reply_info(text, update, context)


def get_html_message(quote_obj: Union[bash_im.Quote, db.Quote]) -> str:
    text = html.escape(quote_obj.text)
    footer = f"""<a href="{quote_obj.url}">{quote_obj.date_str} | #{quote_obj.id}</a>"""
    return f'{text}\n\n{footer}'


def reply_quote(
        quote_obj: Union[bash_im.Quote, db.Quote],
        update: Update,
        context: CallbackContext,
        reply_markup: ReplyKeyboardMarkup = None,
        **kwargs
):
    # Отправка цитаты и отключение link preview -- чтобы по ссылке не генерировалась превью
    update.effective_message.reply_html(
        get_html_message(quote_obj),
        disable_web_page_preview=True,
        reply_markup=reply_markup,
        **kwargs
    )
