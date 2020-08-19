#!/usr/bin/env python3
# -*- coding: utf-8 -*-

__author__ = 'ipetrash'


import html
import os
import time
from threading import Thread
from typing import Union

# pip install python-telegram-bot
from telegram import (
    ReplyKeyboardMarkup, Update, InputMediaPhoto, InlineKeyboardButton, InlineKeyboardMarkup, ChatAction
)
from telegram.ext import Updater, MessageHandler, CommandHandler, Filters, CallbackContext, CallbackQueryHandler
from telegram.ext.dispatcher import run_async

from third_party.bash_im import Quote
from config import TOKEN, ERROR_TEXT, TEXT_HELP, TEXT_BUTTON_MORE, DIR_COMICS
from common import get_logger, log_func, download_more_quotes
import db
from db_utils import process_request, do_backup


log = get_logger(__file__)


REPLY_KEYBOARD_MARKUP = ReplyKeyboardMarkup(
    [[TEXT_BUTTON_MORE]], resize_keyboard=True
)


def get_random_quote(update: Update, context: CallbackContext) -> db.Quote:
    user_id = update.effective_user.id

    if 'quotes' not in context.user_data:
        context.user_data['quotes'] = []

    quotes = context.user_data['quotes']
    log.debug('get_random_quote (quotes: %s)', len(quotes))

    # Если пустой, запрос и заполняем список новыми цитатами
    if not quotes:
        log.debug('Quotes is empty, filling from database.')
        quotes += db.Quote.get_user_unique_random(user_id)
        log.debug('New quotes: %s.', len(quotes))

    return quotes.pop()


def get_html_message(quote: Union[Quote, db.Quote]) -> str:
    text = html.escape(quote.text)
    footer = f"""<a href="{quote.url}">{quote.date_str} | #{quote.id}</a>"""
    return f'{text}\n\n{footer}'


@run_async
@process_request(log)
@log_func(log)
def on_start(update: Update, context: CallbackContext):
    update.message.reply_text(
        f'Все готово!\n' + TEXT_HELP,
        reply_markup=REPLY_KEYBOARD_MARKUP
    )


@run_async
@process_request(log)
@log_func(log)
def on_request(update: Update, context: CallbackContext):
    quote = get_random_quote(update, context)

    log.debug('Quote text (%s)', quote.url)

    if quote.has_comics():
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

    return quote


@run_async
@process_request(log)
@log_func(log)
def on_help(update: Update, context: CallbackContext):
    update.message.reply_text(
        TEXT_HELP, reply_markup=REPLY_KEYBOARD_MARKUP
    )


@run_async
@process_request(log)
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

    db.Error.create_from(on_error, context.error, update)

    if update and update.message:
        update.message.reply_text(ERROR_TEXT)


def main():
    cpu_count = os.cpu_count()
    workers = cpu_count
    log.debug('System: CPU_COUNT=%s, WORKERS=%s', cpu_count, workers)

    log.debug('Start')

    # Create the EventHandler and pass it your bot's token.
    updater = Updater(
        TOKEN,
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

    # Handle all errors
    dp.add_error_handler(on_error)

    # Start the Bot
    updater.start_polling()

    # Run the bot until the you presses Ctrl-C or the process receives SIGINT,
    # SIGTERM or SIGABRT. This should be used most of the time, since
    # start_polling() is non-blocking and will stop the bot gracefully.
    updater.idle()

    log.debug('Finish')


if __name__ == '__main__':
    thread_download = Thread(target=download_more_quotes, args=[log, DIR_COMICS])
    thread_download.start()

    thread_backup = Thread(target=do_backup, args=[log])
    thread_backup.start()

    while True:
        try:
            main()
        except Exception as e:
            log.exception('')

            db.Error.create_from(main, e)

            timeout = 15
            log.info(f'Restarting the bot after {timeout} seconds')
            time.sleep(timeout)
