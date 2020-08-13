#!/usr/bin/env python3
# -*- coding: utf-8 -*-

__author__ = 'ipetrash'


import html
import os
import time
from typing import List
from pathlib import Path

# pip install python-telegram-bot
from telegram import (
    ReplyKeyboardMarkup, Update, InputMediaPhoto, InlineKeyboardButton, InlineKeyboardMarkup, ChatAction
)
from telegram.ext import Updater, MessageHandler, CommandHandler, Filters, CallbackContext, CallbackQueryHandler
from telegram.ext.dispatcher import run_async

from bash_im import Quote, get_random_quotes_list
import config
from common import get_logger, log_func


log = get_logger(__file__)


# Хранилище цитат башорга, из которого будут браться цитаты, и посылаться в телеграм.
# Когда этот список будет пустым, оно будет заполнено с сайта.
QUOTES_LIST: List[Quote] = []

TEXT_BUTTON_MORE = 'Хочу цитату!'
TEXT_HELP = f'Для получения цитаты отправьте любое сообщение, ' \
            f'или нажмите на кнопку "{TEXT_BUTTON_MORE}", ' \
            f'или отправьте команду /more'

REPLY_KEYBOARD_MARKUP = ReplyKeyboardMarkup(
    [[TEXT_BUTTON_MORE]], resize_keyboard=True
)

DIR_COMICS = Path(__file__).resolve().parent / 'comics'
DIR_COMICS.mkdir(parents=True, exist_ok=True)


def get_random_quote() -> Quote:
    log.debug('get_random_quote (QUOTES_LIST: %s)', len(QUOTES_LIST))

    # Если пустой, запрос и заполняем список новыми цитатами
    if not QUOTES_LIST:
        log.debug('QUOTES_LIST is empty, do new request.')
        QUOTES_LIST.extend(get_random_quotes_list(log))

        log.debug('New quotes: %s.', len(QUOTES_LIST))

    return QUOTES_LIST.pop()


def get_html_message(quote: Quote) -> str:
    text = html.escape(quote.text)
    footer = f"""<a href="{quote.url}">{quote.date_str} | #{quote.id}</a>"""
    return f'{text}\n\n{footer}'


@run_async
@log_func(log)
def on_start(update: Update, context: CallbackContext):
    update.message.reply_text(
        f'Все готово!\n' + TEXT_HELP,
        reply_markup=REPLY_KEYBOARD_MARKUP
    )


@run_async
@log_func(log)
def on_request(update: Update, context: CallbackContext):
    quote = get_random_quote()
    if config.LOG_QUOTE_TEXT:
        log.debug('Quote text (%s):\n%s', quote.url, quote.text)
    else:
        log.debug('Quote text (%s)', quote.url)

    if not quote:
        log.warning("Don't receive quote...")
        update.message.reply_text(config.ERROR_TEXT)
        return

    if quote.comics_url:
        keyboard = [[InlineKeyboardButton("Комикс", callback_data=str(quote.id))]]
        reply_markup = InlineKeyboardMarkup(keyboard)
    else:
        # Недостаточно при запуске отправить ReplyKeyboardMarkup, чтобы она всегда оставалась.
        # Удаление сообщения, которое принесло клавиатуру, уберет ее.
        # Поэтому при любой возможности, добавляем клавиатуру
        reply_markup = REPLY_KEYBOARD_MARKUP

    # Отправка цитаты и отключение link preview -- чтобы по ссылке не генерировалась превью
    update.message.reply_html(
        get_html_message(quote),
        disable_web_page_preview=True,
        reply_markup=reply_markup
    )

    quote.download_comics(DIR_COMICS)


@run_async
@log_func(log)
def on_help(update: Update, context: CallbackContext):
    update.message.reply_text(
        TEXT_HELP, reply_markup=REPLY_KEYBOARD_MARKUP
    )


@run_async
@log_func(log)
def on_callback_query(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()

    context.bot.send_chat_action(
        chat_id=query.message.chat_id, action=ChatAction.UPLOAD_PHOTO
    )

    quote_id = query.data
    files = list(DIR_COMICS.glob(f'quote{quote_id}_*.png'))
    max_parts = 10

    for i in range(0, len(files), max_parts):
        media = [
            InputMediaPhoto(f.open('rb')) for f in files[i: i+max_parts]
        ]

        query.message.reply_media_group(
            media=media,
            reply_to_message_id=query.message.message_id
        )


def on_error(update: Update, context: CallbackContext):
    log.exception('Error: %s\nUpdate: %s', context.error, update)
    if update and update.message:
        update.message.reply_text(config.ERROR_TEXT)


def main():
    cpu_count = os.cpu_count()
    workers = cpu_count
    log.debug('System: CPU_COUNT=%s, WORKERS=%s', cpu_count, workers)

    log.debug('Start')

    # Create the EventHandler and pass it your bot's token.
    updater = Updater(
        config.TOKEN,
        workers=workers,
        use_context=True
    )

    # Get the dispatcher to register handlers
    dp = updater.dispatcher

    dp.add_handler(CommandHandler('start', on_start))
    dp.add_handler(CommandHandler('more', on_request))
    dp.add_handler(CommandHandler('help', on_help))
    dp.add_handler(MessageHandler(Filters.text, on_request))
    dp.add_handler(CallbackQueryHandler(on_callback_query))

    # log all errors
    dp.add_error_handler(on_error)

    # Start the Bot
    updater.start_polling()

    # Run the bot until the you presses Ctrl-C or the process receives SIGINT,
    # SIGTERM or SIGABRT. This should be used most of the time, since
    # start_polling() is non-blocking and will stop the bot gracefully.
    updater.idle()

    log.debug('Finish')


if __name__ == '__main__':
    while True:
        try:
            main()
        except:
            log.exception('')

            timeout = 15
            log.info(f'Restarting the bot after {timeout} seconds')
            time.sleep(timeout)
