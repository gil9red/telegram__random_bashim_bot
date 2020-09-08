#!/usr/bin/env python3
# -*- coding: utf-8 -*-

__author__ = 'ipetrash'


import os
import time
from threading import Thread
from typing import Optional

# pip install python-telegram-bot
from telegram import (
    Update, InputMediaPhoto, InlineKeyboardButton, InlineKeyboardMarkup, ChatAction
)
from telegram.ext import Updater, MessageHandler, CommandHandler, Filters, CallbackContext, CallbackQueryHandler
from telegram.ext.dispatcher import run_async

import db
from config import TOKEN, ERROR_TEXT, DIR_COMICS
from common import (
    log, log_func, download_random_quotes, download_main_page_quotes,
    REPLY_KEYBOARD_MARKUP, FILTER_BY_ADMIN, update_quote,
    reply_help, reply_error, reply_quote, reply_info
)
from db_utils import process_request, get_user_message_repr, catch_error, do_backup
from third_party import bash_im


def composed(*decs):
    def deco(f):
        for dec in reversed(decs):
            f = dec(f)
        return f
    return deco


def mega_process(func):
    return composed(
        run_async,
        catch_error(log),
        process_request(log),
        log_func(log),
    )(func)


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


def get_quote_id(context: CallbackContext) -> Optional[int]:
    quote_id = None
    try:
        if context.match:
            quote_id = int(context.match.group(1))
        else:
            quote_id = int(context.args[0])
    except:
        pass

    return quote_id


@mega_process
def on_start(update: Update, context: CallbackContext):
    reply_help(update, context)


@mega_process
def on_help(update: Update, context: CallbackContext):
    reply_help(update, context)


@mega_process
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

    reply_quote(quote, update, context, reply_markup)

    return quote


@mega_process
def on_get_used_quote_in_requests(update: Update, context: CallbackContext):
    quote_id = get_quote_id(context)
    if not quote_id:
        reply_error('Номер цитаты не указан', update, context)
        return

    user_id = update.effective_user.id

    sub_query = db.Request.get_all_quote_id_by_user(user_id)
    items = [i for i, x in enumerate(sub_query) if x.quote_id == quote_id]
    text = f'Цитата #{quote_id} найдена в {items}'

    reply_info(text, update, context)


@mega_process
def on_get_user_stats(update: Update, context: CallbackContext):
    user = db.User.get_from(update.effective_user)

    first_request = user.requests.first()
    last_request = user.requests.order_by(db.Request.id.desc()).first()
    elapsed_days = (last_request.date_time - first_request.date_time).days

    quote_count = user.get_total_quotes()
    quote_with_comics_count = user.get_total_quotes(with_comics=True)

    text = f'''\
<b>Статистика.</b>

Получено цитат <b>{quote_count}</b>, с комиксами <b>{quote_with_comics_count}</b>
Всего запросов боту: {user.requests.count()}
Разница между первым и последним запросом: {elapsed_days} дней
    '''

    update.effective_message.reply_html(text)


@mega_process
def on_get_admin_stats(update: Update, context: CallbackContext):
    quote_count = db.Quote.select().count()
    quote_with_comics_count = db.Quote.get_all_with_comics().count()

    text = f'''\
<b>Статистика админа.</b>

Пользователей: {db.User.select().count()}
Цитат <b>{quote_count}</b>, с комиксами <b>{quote_with_comics_count}</b>
Запросов: {db.Request.select().count()}
    '''

    update.effective_message.reply_html(text)


@mega_process
def on_get_quote_stats(update: Update, context: CallbackContext):
    quote_count = db.Quote.select().count()
    quote_with_comics_count = db.Quote.get_all_with_comics().count()

    text_year_by_counts = "\n".join(
        f'    <b>{year}</b>: {count}'
        for year, count in db.Quote.get_year_by_counts()
    )

    text = f'''\
<b>Статистика по цитатам.</b>

Всего <b>{quote_count}</b>, с комиксами <b>{quote_with_comics_count}</b>:
{text_year_by_counts}
    '''

    update.effective_message.reply_html(text)


@mega_process
def on_get_users(update: Update, context: CallbackContext):
    try:
        if context.match and context.match.groups():
            limit = int(context.match.group(1))
        else:
            limit = int(context.args[0])
    except:
        limit = 10

    items = [
        get_user_message_repr(user)
        for user in db.User.select().order_by(db.User.last_activity.desc()).limit(limit)
    ]
    text = 'Users:\n' + ('\n' + '_' * 20 + '\n').join(items)

    update.effective_message.reply_text(text)


@mega_process
def on_get_quote(update: Update, context: CallbackContext):
    quote_id = get_quote_id(context)
    if not quote_id:
        reply_error('Номер цитаты не указан', update, context)
        return

    quote = db.Quote.get_or_none(quote_id)

    if not quote:
        reply_error(f'Цитаты #{quote_id} нет в базе', update, context)
        return

    reply_quote(quote, update, context)


@mega_process
def on_get_external_quote(update: Update, context: CallbackContext):
    quote_id = get_quote_id(context)
    if not quote_id:
        reply_error('Номер цитаты не указан', update, context)
        return

    quote = bash_im.Quote.parse_from(quote_id)
    if not quote:
        reply_error(f'Цитаты #{quote_id} на сайте нет', update, context)
        return

    reply_quote(quote, update, context)


@mega_process
def on_update_quote(update: Update, context: CallbackContext):
    quote_id = get_quote_id(context)
    if not quote_id:
        reply_error('Номер цитаты не указан', update, context)
        return

    update_quote(quote_id, update, context)


@mega_process
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


@catch_error(log)
def on_error(update: Update, context: CallbackContext):
    log.exception('Error: %s\nUpdate: %s', context.error, update)

    db.Error.create_from(on_error, context.error, update)

    if update:
        reply_error(ERROR_TEXT, update, context)


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

    dp.add_handler(CommandHandler('help', on_help))
    dp.add_handler(
        MessageHandler(
            Filters.regex(r'(?i)^help$|^помощь$'),
            on_help
        )
    )

    dp.add_handler(CommandHandler('more', on_request))

    # Возвращение статистики текущего пользователя
    dp.add_handler(CommandHandler('stats', on_get_user_stats))
    dp.add_handler(
        MessageHandler(
            Filters.regex(r'(?i)^stats$|^статистика$'),
            on_get_user_stats
        )
    )

    # Возвращение статистики админа
    dp.add_handler(CommandHandler('admin_stats', on_get_admin_stats, FILTER_BY_ADMIN))
    dp.add_handler(
        MessageHandler(
            FILTER_BY_ADMIN & Filters.regex(r'(?i)^admin[ _]stats$|^статистика[ _]админа$'),
            on_get_admin_stats
        )
    )

    # Возвращение статистики цитат
    dp.add_handler(CommandHandler('quote_stats', on_get_quote_stats, FILTER_BY_ADMIN))
    dp.add_handler(
        MessageHandler(
            FILTER_BY_ADMIN & Filters.regex(r'(?i)^quote[ _]stats$|^статистика[ _]цитат$'),
            on_get_quote_stats
        )
    )

    # Возвращение порядка вызова указанной цитаты у текущего пользователя, сортировка от конца
    dp.add_handler(CommandHandler('get_used_quote', on_get_used_quote_in_requests, FILTER_BY_ADMIN))
    dp.add_handler(
        MessageHandler(
            FILTER_BY_ADMIN & Filters.regex(r'(?i)^get[ _]used[ _]quote (\d+)$'),
            on_get_used_quote_in_requests
        )
    )
    dp.add_handler(
        MessageHandler(
            FILTER_BY_ADMIN & Filters.regex(r'^(\d+)$'),
            on_get_used_quote_in_requests
        )
    )

    dp.add_handler(CommandHandler('get_users', on_get_users, FILTER_BY_ADMIN))
    dp.add_handler(
        MessageHandler(
            FILTER_BY_ADMIN & (Filters.regex(r'(?i)^get[ _]users (\d+)$') | Filters.regex(r'(?i)^get users$')),
            on_get_users
        )
    )

    dp.add_handler(CommandHandler('get_quote', on_get_quote))
    dp.add_handler(
        MessageHandler(
            Filters.regex(r'(?i)^get[ _]quote (\d+)$'),
            on_get_quote
        )
    )

    dp.add_handler(CommandHandler('get_external_quote', on_get_external_quote))
    dp.add_handler(
        MessageHandler(
            Filters.regex(r'(?i)^get[ _]external[ _]quote (\d+)$'),
            on_get_external_quote
        )
    )

    dp.add_handler(CommandHandler('update_quote', on_update_quote, FILTER_BY_ADMIN))
    dp.add_handler(
        MessageHandler(
            FILTER_BY_ADMIN & Filters.regex(r'(?i)^update[ _]quote (\d+)$'),
            on_update_quote
        )
    )

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
    thread_download_main_page_quotes = Thread(target=download_main_page_quotes, args=[log, DIR_COMICS])
    thread_download_main_page_quotes.start()

    thread_download_random_quotes = Thread(target=download_random_quotes, args=[log, DIR_COMICS])
    thread_download_random_quotes.start()

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
