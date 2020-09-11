#!/usr/bin/env python3
# -*- coding: utf-8 -*-

__author__ = 'ipetrash'


import datetime as DT
import functools
import html
import logging
import time
import sys
from pathlib import Path
from random import randint
from typing import Union
from threading import RLock

from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import CallbackContext, Filters

# pip install schedule
import schedule

import db
from config import HELP_TEXT, ADMIN_USERNAME, TEXT_BUTTON_MORE, DIR_COMICS
from third_party import bash_im


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


REPLY_KEYBOARD_MARKUP = ReplyKeyboardMarkup(
    [[TEXT_BUTTON_MORE]], resize_keyboard=True
)

FILTER_BY_ADMIN = Filters.user(username=ADMIN_USERNAME)


log = get_logger(Path(__file__).resolve().parent.name)

# Для препятствия одновременной работы в download_random_quotes и download_new_quotes
lock = RLock()


def log_func(log: logging.Logger):
    def actual_decorator(func):
        @functools.wraps(func)
        def wrapper(update: Update, context: CallbackContext):
            if update:
                chat_id = user_id = first_name = last_name = username = language_code = None

                if update.effective_chat:
                    chat_id = update.effective_chat.id

                if update.effective_user:
                    user_id = update.effective_user.id
                    first_name = update.effective_user.first_name
                    last_name = update.effective_user.last_name
                    username = update.effective_user.username
                    language_code = update.effective_user.language_code

                try:
                    message = update.effective_message.text
                except:
                    message = ''

                try:
                    query_data = update.callback_query.data
                except:
                    query_data = ''

                msg = f'[chat_id={chat_id}, user_id={user_id}, ' \
                      f'first_name={first_name!r}, last_name={last_name!r}, ' \
                      f'username={username!r}, language_code={language_code}, ' \
                      f'message={message!r}, query_data={query_data!r}]'
                msg = func.__name__ + msg

                log.debug(msg)

            return func(update, context)

        return wrapper
    return actual_decorator


def download_random_quotes(log: logging.Logger, dir_comics):
    i = 0

    while True:
        try:
            with lock:
                count = db.Quote.select().count()
                log.debug(f'{download_random_quotes.__name__}. Now quotes: {count}')
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
                    log.debug(f'{download_main_page_quotes.__name__}. Now quotes: {count}')
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


def update_quote(quote_id: int, update: Update = None, context: CallbackContext = None):
    need_reply = update and context

    quote_bashim = bash_im.Quote.parse_from(quote_id)
    if not quote_bashim:
        text = f'Цитаты #{quote_id} на сайте нет'
        log.info(text)
        need_reply and reply_error(text, update, context)
        return

    quote_db: db.Quote = db.Quote.get_or_none(quote_id)
    if not quote_db:
        log.info(f'Цитаты #{quote_id} в базе нет, будет создание цитаты')

        # При отсутствии, цитата будет добавлена в базу
        db.Quote.get_from(quote_bashim)

        # Сразу же пробуем скачать комиксы
        quote_bashim.download_comics(DIR_COMICS)

        text = f'Цитата #{quote_id} добавлена в базу'
        log.info(text)
        need_reply and reply_info(text, update, context)

    else:
        # TODO: Поддержать проверку и добавление новых комиксов
        modified_list = []

        if quote_db.text != quote_bashim.text:
            quote_db.text = quote_bashim.text
            modified_list.append('текст')

        if modified_list:
            quote_db.modification_date = DT.date.today()
            quote_db.save()

            text = f'Цитата #{quote_id} обновлена ({", ".join(modified_list)})'
            log.info(text)
            need_reply and reply_info(text, update, context)

        else:
            text = f'Нет изменений в цитате #{quote_id}'
            log.info(text)
            need_reply and reply_info(text, update, context)


def get_html_message(quote: Union[bash_im.Quote, db.Quote]) -> str:
    text = html.escape(quote.text)
    footer = f"""<a href="{quote.url}">{quote.date_str} | #{quote.id}</a>"""
    return f'{text}\n\n{footer}'


# TODO: генерировать список команд из обработчика
#       описание команды можно сделать в функции как docstring
def reply_help(update: Update, context: CallbackContext):
    username = update.effective_user.username
    is_admin = username == ADMIN_USERNAME[1:]

    text = HELP_TEXT + '\n'

    text += """
Получение помощи по командам:
 - /help
 - help или помощь

Получение статистики текущего пользователя:
 - /stats
 - stats или статистика

Получение цитаты из базы:
 - /get_quote <номер цитаты>
 - get quote <номер цитаты>
 
Получение цитаты из сайта:
 - /get_external_quote <номер цитаты>
 - get external quote <номер цитаты>
    """

    if is_admin:
        text += r"""
Получение статистики админа:
 - /admin_stats
 - admin[ _]stats или статистика[ _]админа

Получение статистики по цитатам:
 - /quote_stats
 - quote[ _]stats или статистика[ _]цитат

Получение порядка вызова указанной цитаты у текущего пользователя:
 - /get_used_quote
 - get[ _]used[ _]quote (\d+) или (\d+)

Получение пользователей:
 - /get_users
 - get[ _]users (\d+)
 
Обновление цитаты в базе с сайта:
 - /update_quote
 - update[ _]quote (\d+)
    """

    update.effective_message.reply_text(
        text,
        reply_markup=REPLY_KEYBOARD_MARKUP
    )


def reply_error(text: str, update: Update, context: CallbackContext):
    update.effective_message.reply_text(
        '⚠ ' + text
    )


def reply_info(text: str, update: Update, context: CallbackContext):
    update.effective_message.reply_text(
        'ℹ️ ' + text
    )


def reply_quote(
        quote: Union[bash_im.Quote, db.Quote],
        update: Update,
        context: CallbackContext,
        reply_markup: ReplyKeyboardMarkup = None
):
    # Отправка цитаты и отключение link preview -- чтобы по ссылке не генерировалась превью
    update.effective_message.reply_html(
        get_html_message(quote),
        disable_web_page_preview=True,
        reply_markup=reply_markup
    )
