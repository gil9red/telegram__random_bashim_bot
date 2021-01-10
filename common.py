#!/usr/bin/env python3
# -*- coding: utf-8 -*-

__author__ = 'ipetrash'


import datetime as DT
import functools
import html
import logging
import sys
from pathlib import Path
from typing import Union, Optional, List

from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton, Bot, ParseMode
from telegram.ext import MessageHandler, CommandHandler, CallbackContext, Filters
from telegram.ext.filters import MergedFilter

import db
from config import HELP_TEXT, ADMIN_USERNAME, TEXT_BUTTON_MORE, DIR_COMICS, MAX_MESSAGE_LENGTH
from parsers import bash_im


def split_list(items: List, columns: int = 5) -> List[List]:
    result = []

    for i in range(0, len(items), columns):
        result.append(
            [key for key in items[i: i + columns]]
        )

    return result


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


def get_doc(obj) -> Optional[str]:
    if not obj or not obj.__doc__:
        return

    items = []
    for line in obj.__doc__.splitlines():
        if line.startswith('    '):
            line = line[4:]

        items.append(line)

    return '\n'.join(items).strip()


def get_deep_linking(argument, update: Update) -> str:
    bot_name = BOT.name.lstrip('@')
    from_message_id = update.effective_message.message_id
    return f'[{argument}](https://t.me/{bot_name}?start={argument}_{from_message_id})'


BOT: Bot = None

REPLY_KEYBOARD_MARKUP = ReplyKeyboardMarkup(
    [[TEXT_BUTTON_MORE]], resize_keyboard=True
)

FILTER_BY_ADMIN = Filters.user(username=ADMIN_USERNAME)

BUTTON_HELP_COMMON = InlineKeyboardButton('⬅️ Общие команды', callback_data='help_common')
BUTTON_HELP_ADMIN = InlineKeyboardButton('➡️ Команды админа', callback_data='help_admin')

COMMON_COMMANDS = []
ADMIN_COMMANDS = []

START_TIME = DT.datetime.now()

log = get_logger(Path(__file__).resolve().parent.name)


def get_elapsed_time(date_time: DT.datetime) -> str:
    diff = str(DT.datetime.now() - date_time)
    return diff.split('.')[0]


def fill_commands_for_help(dispatcher):
    for commands in dispatcher.handlers.values():
        for command in commands:
            if not isinstance(command, (CommandHandler, MessageHandler)):
                continue

            help_command = get_doc(command.callback)
            if not help_command:
                continue

            if has_admin_filter(command.filters):
                if help_command not in ADMIN_COMMANDS:
                    ADMIN_COMMANDS.append(help_command)
            else:
                if help_command not in COMMON_COMMANDS:
                    COMMON_COMMANDS.append(help_command)


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


def reply_help(update: Update, context: CallbackContext):
    query = update.callback_query
    message = update.effective_message
    query_data = None

    # Если функция вызвана из CallbackQueryHandler
    if query:
        query.answer()
        query_data = query.data

    username = update.effective_user.username
    is_admin = username == ADMIN_USERNAME[1:]

    show_common_help = True
    if query_data:
        show_common_help = query_data.endswith('common')

    text_common = HELP_TEXT + '\n\n' + '\n\n'.join(COMMON_COMMANDS)
    text_admin = '\n\n'.join(ADMIN_COMMANDS)

    if is_admin:
        text = text_common if show_common_help else text_admin
        next_button = BUTTON_HELP_ADMIN if show_common_help else BUTTON_HELP_COMMON
        reply_markup = InlineKeyboardMarkup.from_button(next_button)
    else:
        text = text_common
        reply_markup = REPLY_KEYBOARD_MARKUP

    if query:
        message.edit_text(text, reply_markup=reply_markup)
    else:
        message.reply_text(text, reply_markup=reply_markup)


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
        quote: Union[bash_im.Quote, db.Quote],
        update: Update,
        context: CallbackContext,
        reply_markup: ReplyKeyboardMarkup = None,
        **kwargs
):
    # Отправка цитаты и отключение link preview -- чтобы по ссылке не генерировалась превью
    update.effective_message.reply_html(
        get_html_message(quote),
        disable_web_page_preview=True,
        reply_markup=reply_markup,
        **kwargs
    )
