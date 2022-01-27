#!/usr/bin/env python3
# -*- coding: utf-8 -*-

__author__ = 'ipetrash'


import datetime as DT
import functools
import html
import inspect
import json
import logging
import math
import sys

from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Union, List, Optional

import telegram.error
from telegram import (
    Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton, Bot, Message, CallbackQuery
)
from telegram.ext import MessageHandler, CommandHandler, CallbackContext, Filters
from telegram.ext.filters import MergedFilter

# pip install python-telegram-bot-pagination
from telegram_bot_pagination import InlineKeyboardPaginator

from bot import db
from config import (
    HELP_TEXT, ADMIN_USERNAME, TEXT_BUTTON_MORE, MAX_MESSAGE_LENGTH, DIR, DIR_COMICS, DIR_LOG, COMMANDS_PER_PAGE
)
from bot.regexp_patterns import PATTERN_HELP_COMMON, PATTERN_HELP_ADMIN, fill_string_pattern
from third_party import bash_im


BOT: Bot = None

REPLY_KEYBOARD_MARKUP = ReplyKeyboardMarkup.from_button(
    TEXT_BUTTON_MORE, resize_keyboard=True
)

FILTER_BY_ADMIN = Filters.user(username=ADMIN_USERNAME)


COMMON_COMMANDS: List[str] = []
ADMIN_COMMANDS: List[str] = []

START_TIME = DT.datetime.now()


def split_list(items: List, columns: int = 5) -> List[List]:
    result = []

    for i in range(0, len(items), columns):
        result.append(
            [key for key in items[i: i + columns]]
        )

    return result


def get_logger(
        name: str,
        file: Union[str, Path] = 'log.txt',
        encoding='utf-8',
        log_stdout=True,
        log_file=True
) -> 'logging.Logger':
    log = logging.getLogger(name)
    log.setLevel(logging.DEBUG)

    formatter = logging.Formatter('[%(asctime)s] %(filename)s:%(lineno)d %(levelname)-8s %(message)s')

    if log_file:
        fh = RotatingFileHandler(file, maxBytes=10000000, backupCount=5, encoding=encoding)
        fh.setFormatter(formatter)
        log.addHandler(fh)

    if log_stdout:
        sh = logging.StreamHandler(stream=sys.stdout)
        sh.setFormatter(formatter)
        log.addHandler(sh)

    return log


def has_admin_filter(filter_handler) -> bool:
    if filter_handler is FILTER_BY_ADMIN:
        return True

    if isinstance(filter_handler, MergedFilter):
        return any([
            has_admin_filter(filter_handler.base_filter),
            has_admin_filter(filter_handler.and_filter),
            has_admin_filter(filter_handler.or_filter),
        ])

    return False


def get_deep_linking(argument, update: Update) -> str:
    bot_name = BOT.name.lstrip('@')
    from_message_id = update.effective_message.message_id
    return f'[{argument}](https://t.me/{bot_name}?start={argument}_{from_message_id})'


def get_plural_days(n: int) -> str:
    days = ['день', 'дня', 'дней']

    if n % 10 == 1 and n % 100 != 11:
        p = 0
    elif 2 <= n % 10 <= 4 and (n % 100 < 10 or n % 100 >= 20):
        p = 1
    else:
        p = 2

    return days[p]


def get_elapsed_time(date_time: DT.datetime) -> str:
    delta = DT.datetime.now() - date_time
    day = get_plural_days(delta.days)
    diff = str(delta).replace('days', day).replace('day', day)
    return diff.split('.')[0]


def fill_commands_for_help(dispatcher):
    for commands in dispatcher.handlers.values():
        for command in commands:
            if not isinstance(command, (CommandHandler, MessageHandler)):
                continue

            help_command = inspect.getdoc(command.callback)
            if not help_command:
                continue

            if has_admin_filter(command.filters):
                if help_command not in ADMIN_COMMANDS:
                    ADMIN_COMMANDS.append(help_command)
            else:
                if help_command not in COMMON_COMMANDS:
                    COMMON_COMMANDS.append(help_command)


def is_equal_inline_keyboards(
        keyboard_1: Union[InlineKeyboardMarkup, str],
        keyboard_2: InlineKeyboardMarkup
) -> bool:
    if isinstance(keyboard_1, InlineKeyboardMarkup):
        keyboard_1_inline_keyboard = keyboard_1.to_dict()['inline_keyboard']
    elif isinstance(keyboard_1, str):
        keyboard_1_inline_keyboard = json.loads(keyboard_1)['inline_keyboard']
    else:
        raise Exception(f'Unsupported format (keyboard_1={type(keyboard_1)})!')

    keyboard_2_inline_keyboard = keyboard_2.to_dict()['inline_keyboard']
    return keyboard_1_inline_keyboard == keyboard_2_inline_keyboard


def get_page(
        context: CallbackContext,
        default_page: int = 1
) -> int:
    try:
        if context.match and context.match.groups():
            page = int(context.match.group(1))
        else:
            page = int(context.args[0])
    except:
        page = default_page

    return page


def reply_text_or_edit_with_keyboard(
    message: Message,
    query: Optional[CallbackQuery],
    text: str,
    reply_markup: Union[InlineKeyboardMarkup, str],
    quote: bool = False,
    **kwargs,
):
    # Для запросов CallbackQuery нужно менять текущее сообщение
    if query:
        # Fix error: "telegram.error.BadRequest: Message is not modified"
        if text == query.message.text and is_equal_inline_keyboards(reply_markup, query.message.reply_markup):
            return

        try:
            message.edit_text(
                text,
                reply_markup=reply_markup,
                **kwargs,
            )
        except telegram.error.BadRequest as e:
            if 'Message is not modified' in str(e):
                return

            raise e

    else:
        message.reply_text(
            text,
            reply_markup=reply_markup,
            quote=quote,
            **kwargs,
        )


def reply_text_or_edit_with_keyboard_paginator(
        message: Message,
        query: Optional[CallbackQuery],
        text: str,
        page_count: int,
        items_per_page: int,
        current_page: int,
        data_pattern: str,
        before_inline_buttons: List[InlineKeyboardButton] = None,
        after_inline_buttons: List[InlineKeyboardButton] = None,
        quote: bool = False,
        **kwargs,
):
    page_count = math.ceil(page_count / items_per_page)

    paginator = InlineKeyboardPaginator(
        page_count=page_count,
        current_page=current_page,
        data_pattern=data_pattern,
    )
    if before_inline_buttons:
        paginator.add_before(*before_inline_buttons)

    if after_inline_buttons:
        paginator.add_after(*after_inline_buttons)

    reply_markup = paginator.markup

    reply_text_or_edit_with_keyboard(
        message, query,
        text,
        reply_markup,
        quote=quote,
        **kwargs,
    )


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

                    # Содержит текущий текст сообщения, под которым была inline-кнопка
                    # Нет смысла логировать этот текст
                    message = '<hidden>'
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


def reply_help(update: Update, context: CallbackContext):
    query = update.callback_query
    message = update.effective_message

    # Если функция вызвана из CallbackQueryHandler
    if query:
        query.answer()
        query_data = query.data
    else:
        query_data = None

    # По умолчанию, показываем общие команды
    # Если вызвано через CallbackQueryHandler, то проверяем по типу данных
    show_common_help = True
    if query_data:
        show_common_help = bool(PATTERN_HELP_COMMON.search(query_data))

    items_per_page = COMMANDS_PER_PAGE
    page = get_page(context)

    if show_common_help:
        pattern_help = PATTERN_HELP_COMMON
        all_items = COMMON_COMMANDS
        button_help_change_type_page = InlineKeyboardButton(
            '➡️ Команды админа', callback_data=fill_string_pattern(PATTERN_HELP_ADMIN, 1)
        )
    else:
        pattern_help = PATTERN_HELP_ADMIN
        all_items = ADMIN_COMMANDS
        button_help_change_type_page = InlineKeyboardButton(
            '⬅️ Общие команды', callback_data=fill_string_pattern(PATTERN_HELP_COMMON, 1)
        )

    # Элементы текущей страницы
    items = all_items[(page - 1) * items_per_page: page * items_per_page]

    username = update.effective_user.username
    is_admin = username == ADMIN_USERNAME[1:]
    if is_admin:
        after_inline_buttons = [button_help_change_type_page]
    else:
        after_inline_buttons = None

    text = '\n\n'.join(items)
    if show_common_help:
        text = HELP_TEXT + '\n\n' + text

    reply_text_or_edit_with_keyboard_paginator(
        message, query,
        text,
        page_count=len(all_items),
        items_per_page=items_per_page,
        current_page=page,
        data_pattern=fill_string_pattern(pattern_help, '{page}'),
        after_inline_buttons=after_inline_buttons,
    )


def reply_error(text: str, update: Update, context: CallbackContext, **kwargs):
    text = '⚠ ' + text
    if len(text) > MAX_MESSAGE_LENGTH:
        text = text[:MAX_MESSAGE_LENGTH-3] + '...'

    update.effective_message.reply_text(text, **kwargs)


def reply_info(text: str, update: Update, context: CallbackContext, **kwargs):
    text = 'ℹ️ ' + text
    if len(text) > MAX_MESSAGE_LENGTH:
        text = text[:MAX_MESSAGE_LENGTH-3] + '...'

    update.effective_message.reply_text(text, **kwargs)


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


log = get_logger(
    DIR.name,
    DIR_LOG / f'{Path(__file__).resolve().parent.name}.log'
)

log_backup = get_logger(
    f'{DIR.name}_backup',
    DIR_LOG / 'backup.log'
)
