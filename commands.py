#!/usr/bin/env python3
# -*- coding: utf-8 -*-

__author__ = 'ipetrash'


import enum
import logging
import re
from typing import Optional, Dict

# pip install python-telegram-bot
from telegram import (
    Update, InputMediaPhoto, InlineKeyboardButton, InlineKeyboardMarkup, ChatAction, ParseMode
)
from telegram.ext import Updater, MessageHandler, CommandHandler, Filters, CallbackContext, CallbackQueryHandler
from telegram.ext.dispatcher import run_async

import db
from config import ERROR_TEXT, DIR_COMICS, CHECKBOX, CHECKBOX_EMPTY, RADIOBUTTON, RADIOBUTTON_EMPTY, LIMIT_UNIQUE_QUOTES
from common import (
    log, log_func, REPLY_KEYBOARD_MARKUP, FILTER_BY_ADMIN, fill_commands_for_help,
    update_quote, reply_help, reply_error, reply_quote, reply_info,
    BUTTON_HELP_COMMON, BUTTON_HELP_ADMIN, START_TIME, get_elapsed_time,
    get_deep_linking
)
from db_utils import process_request, get_user_message_repr, catch_error
from parsers import bash_im


PATTERN_QUOTE_STATS = re.compile(r'(?i)^quote[ _]stats$|^статистика[ _]цитат$')
PATTERN_QUERY_QUOTE_STATS = 'quote_stats'

PATTERN_QUERY_COMICS_STATS = 'comics_stats'
PATTERN_COMICS_STATS = re.compile(f'^{PATTERN_QUERY_COMICS_STATS}$')


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


def is_equal_inline_keyboards(keyboard_1: InlineKeyboardMarkup, keyboard_2: InlineKeyboardMarkup) -> bool:
    keyboard_1 = keyboard_1.to_dict()['inline_keyboard']
    keyboard_2 = keyboard_2.to_dict()['inline_keyboard']
    return keyboard_1 == keyboard_2


class SettingState(enum.Enum):
    YEAR = " ⁃ Фильтрация получения цитат по годам"
    LIMIT = " ⁃ Количество получаемых уникальных цитат"
    MAIN = enum.auto()

    def get_callback_data(self) -> str:
        return str(self).replace('.', '_')

    def get_pattern_with_params(self) -> re.Pattern:
        return re.compile('^' + self.get_callback_data() + '_(.+)$')

    def get_pattern_full(self) -> re.Pattern:
        return re.compile(
            '^' + self.get_callback_data() + '$|' + self.get_pattern_with_params().pattern
        )


INLINE_KEYBOARD_BUTTON_BACK = InlineKeyboardButton(
    "<назад>", callback_data=SettingState.MAIN.get_callback_data()
)


def get_random_quote(update: Update, context: CallbackContext) -> Optional[db.Quote]:
    user = db.User.get_from(update.effective_user)

    if 'quotes' not in context.user_data:
        context.user_data['quotes'] = []

    quotes = context.user_data['quotes']
    log.debug(f'get_random_quote (quotes: {len(quotes)})')

    # Заполняем список новыми цитатами, если он пустой
    if not quotes:
        log.debug('Quotes is empty, filling from database.')

        years_of_quotes = user.get_years_of_quotes()
        update_cache(user, years_of_quotes, log, update, context)

    if quotes:
        return quotes.pop()

    return


def get_context_value(context: CallbackContext) -> Optional[str]:
    value = None
    try:
        # Значение вытаскиваем из регулярки
        if context.match:
            value = context.match.group(1)
        else:
            # Значение из значений команды
            value = ' '.join(context.args)
    except:
        pass

    return value


def get_quote_id(context: CallbackContext) -> Optional[int]:
    try:
        value = get_context_value(context)
        return int(value)
    except:
        pass


def get_local_quote(update: Update, context: CallbackContext):
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
def on_start(update: Update, context: CallbackContext):
    # При открытии цитаты через ссылку (deep linking)
    if context.args:
        # https://t.me/<bot>?start=<start_argument>
        get_local_quote(update, context)

    else:
        reply_help(update, context)


@mega_process
def on_help(update: Update, context: CallbackContext):
    """
    Получение помощи по командам:
     - /help
     - help или помощь
    """

    reply_help(update, context)


def update_cache(
        user: db.User,
        years_of_quotes: Dict[int, bool],
        log: logging.Logger,
        update: Update,
        context: CallbackContext
):
    years = [year for year, is_selected in years_of_quotes.items() if is_selected]
    log.debug(f'Start [{update_cache.__name__}], selected years: {years}')

    if 'quotes' not in context.user_data:
        context.user_data['quotes'] = []

    quotes = context.user_data['quotes']

    if years:
        log.debug(f'Quotes from year(s): {", ".join(map(str, years))}.')

    quotes += user.get_user_unique_random(years)

    log.debug(f'Finish [{update_cache.__name__}]. Quotes: {len(quotes)}')


@mega_process
def on_settings(update: Update, context: CallbackContext):
    """
    Вызов настроек:
     - /settings
     - settings или настройки
    """

    query = update.callback_query

    # Если функция вызвана из CallbackQueryHandler
    if query:
        query.answer()

    message = update.effective_message

    reply_markup = InlineKeyboardMarkup.from_column([
        InlineKeyboardButton(SettingState.YEAR.value, callback_data=SettingState.YEAR.get_callback_data()),
        InlineKeyboardButton(SettingState.LIMIT.value, callback_data=SettingState.LIMIT.get_callback_data()),
    ])

    text = 'Выбор настроек:'

    # Если функция вызвана из CallbackQueryHandler
    if query:
        message.edit_text(text, reply_markup=reply_markup)
    else:
        message.reply_text(text, reply_markup=reply_markup)


def _on_reply_year(log: logging.Logger, update: Update, context: CallbackContext):
    query = update.callback_query

    settings = SettingState.YEAR

    user = db.User.get_from(update.effective_user)
    years_of_quotes = user.get_years_of_quotes()

    pattern = settings.get_pattern_with_params()
    m = pattern.search(query.data)
    if m:
        year = int(m.group(1))
        if year not in years_of_quotes:
            return

        years_of_quotes[year] = not years_of_quotes[year]
        log.debug(f'    {year} = {years_of_quotes[year]}')

        # Нужно обновить кэш цитат в соответствии с выбранными годами
        log.debug('Clear cache quotes')

        if 'quotes' not in context.user_data:
            context.user_data['quotes'] = []

        quotes = context.user_data['quotes']
        quotes.clear()

        update_cache(user, years_of_quotes, log, update, context)

    keys = list(years_of_quotes)
    data = settings.get_callback_data()
    columns = 4
    buttons = []
    for i in range(0, len(keys), columns):
        row = []
        for key in keys[i: i + columns]:
            is_selected = years_of_quotes[key]

            year_str = str(key)
            row.append(
                InlineKeyboardButton(
                    (CHECKBOX if is_selected else CHECKBOX_EMPTY) + ' ' + year_str,
                    callback_data=data + '_' + year_str
                )
            )

        buttons.append(row)

    buttons.append([INLINE_KEYBOARD_BUTTON_BACK])

    reply_markup = InlineKeyboardMarkup(buttons)

    # Fix error: "telegram.error.BadRequest: Message is not modified"
    if is_equal_inline_keyboards(reply_markup, query.message.reply_markup):
        return

    # Обновление базы данных должно быть в соответствии с тем, что видит пользователь
    user.set_years_of_quotes(years_of_quotes)

    text = 'Выбор года:'
    query.edit_message_text(text, reply_markup=reply_markup)


def _on_reply_limit(log: logging.Logger, update: Update, context: CallbackContext):
    query = update.callback_query

    settings = SettingState.LIMIT
    user = db.User.get_from(update.effective_user)

    # Если значение было передано
    pattern = settings.get_pattern_with_params()
    m = pattern.search(query.data)
    if m:
        data_limit = int(m.group(1))
        if data_limit not in LIMIT_UNIQUE_QUOTES:
            return

        log.debug(f'    limit_unique_quotes = {data_limit}')

        user.set_limit_unique_quotes(data_limit)

    limit = user.get_limit_unique_quotes()
    data = settings.get_callback_data()
    columns = 3
    buttons = []
    for i in range(0, len(LIMIT_UNIQUE_QUOTES), columns):
        row = []
        for x in LIMIT_UNIQUE_QUOTES[i: i + columns]:
            limit_str = str(x)
            is_selected = limit_str == str(limit)

            row.append(
                InlineKeyboardButton(
                    (RADIOBUTTON if is_selected else RADIOBUTTON_EMPTY) + ' ' + limit_str,
                    callback_data=data + '_' + limit_str
                )
            )

        buttons.append(row)

    buttons.append([INLINE_KEYBOARD_BUTTON_BACK])

    reply_markup = InlineKeyboardMarkup(buttons)

    # Fix error: "telegram.error.BadRequest: Message is not modified"
    if is_equal_inline_keyboards(reply_markup, query.message.reply_markup):
        return

    text = 'Количество уникальных цитат:'
    query.edit_message_text(text, reply_markup=reply_markup)


@mega_process
def on_settings_year(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()

    _on_reply_year(log, update, context)


@mega_process
def on_settings_limit(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()

    _on_reply_limit(log, update, context)


@mega_process
def on_request(update: Update, context: CallbackContext):
    quote = get_random_quote(update, context)
    if not quote:
        text = 'Закончились уникальные цитаты'

        user = db.User.get_from(update.effective_user)
        if any(user.get_years_of_quotes().values()):
            text += '. Попробуйте в настройках убрать фильтрацию цитат по годам.'

        reply_info(text, update, context)
        return

    log.debug('Quote text (%s)', quote.url)

    if quote.has_comics():
        reply_markup = InlineKeyboardMarkup.from_button(
            InlineKeyboardButton("Комикс", callback_data=str(quote.id))
        )
    else:
        # Недостаточно при запуске отправить ReplyKeyboardMarkup, чтобы она всегда оставалась.
        # Удаление сообщения, которое принесло клавиатуру, уберет ее.
        # Поэтому при любой возможности, добавляем клавиатуру
        reply_markup = REPLY_KEYBOARD_MARKUP

    reply_quote(quote, update, context, reply_markup)

    return quote


@mega_process
def on_get_used_quote_in_requests(update: Update, context: CallbackContext):
    r"""
    Получение порядка вызова указанной цитаты у текущего пользователя:
     - /get_used_quote
     - get[ _]used[ _]quote (\d+) или (\d+)
    """

    quote_id = get_quote_id(context)
    if not quote_id:
        reply_error('Номер цитаты не указан', update, context)
        return

    user_id = update.effective_user.id

    sub_query = db.Request.get_all_quote_id_by_user(user_id)
    items = [i for i, x in enumerate(sub_query) if x.quote_id == quote_id]
    if items:
        text = f'Цитата #{quote_id} найдена в {items}'
    else:
        text = f'Цитата #{quote_id} не найдена'

    reply_info(text, update, context)


@mega_process
def on_get_user_stats(update: Update, context: CallbackContext):
    """
    Получение статистики текущего пользователя:
     - /stats
     - stats или статистика
    """

    user = db.User.get_from(update.effective_user)

    first_request = user.requests.first()
    last_request = user.requests.order_by(db.Request.id.desc()).first()
    elapsed_days = (last_request.date_time - first_request.date_time).days

    quote_count = user.get_total_quotes()
    quote_with_comics_count = user.get_total_quotes(with_comics=True)

    text = f'''\
<b>Статистика.</b>

Получено цитат <b>{quote_count}</b>, с комиксами <b>{quote_with_comics_count}</b>
Всего запросов боту: <b>{user.requests.count()}</b>
Разница между первым и последним запросом: <b>{elapsed_days}</b> дней
    '''

    update.effective_message.reply_html(text)


@mega_process
def on_get_admin_stats(update: Update, context: CallbackContext):
    """
    Получение статистики админа:
     - /admin_stats
     - admin[ _]stats или статистика[ _]админа
    """

    quote_count = db.Quote.select().count()
    quote_with_comics_count = db.Quote.get_all_with_comics().count()

    text = f'''\
<b>Статистика админа.</b>

Пользователей: <b>{db.User.select().count()}</b>
Цитат <b>{quote_count}</b>, с комиксами <b>{quote_with_comics_count}</b>
Запросов: <b>{db.Request.select().count()}</b>

С первого запроса прошло: <b>{get_elapsed_time(db.Request.get_first_date_time())}</b>
Бот запущен уже: <b>{get_elapsed_time(START_TIME)}</b>
    '''

    update.effective_message.reply_html(text)


@mega_process
def on_get_quote_stats(update: Update, context: CallbackContext):
    """
    Получение статистики по цитатам:
     - /quote_stats
     - quote[ _]stats или статистика[ _]цитат
    """

    message = update.effective_message

    query = update.callback_query
    if query:
        query.answer()

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

    reply_markup = InlineKeyboardMarkup.from_button(
        InlineKeyboardButton('➡️ Комиксы', callback_data=PATTERN_QUERY_COMICS_STATS)
    )

    is_new = not message.edit_date
    if is_new:
        message.reply_html(
            text,
            reply_markup=reply_markup
        )
    else:
        message.edit_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
        )


@mega_process
def on_get_comics_stats(update: Update, context: CallbackContext):
    message = update.effective_message

    query = update.callback_query
    query.answer()

    quote_query = db.Quote.get_all_with_comics()
    quote_count = quote_query.count()

    year_by_number = {k: 0 for k in db.Quote.get_years()}
    for quote in quote_query.select(db.Quote.date):
        year = quote.date.year
        year_by_number[year] += 1

    text_year_by_counts = "\n".join(
        f'    <b>{year}</b>: {count}'
        for year, count in year_by_number.items()
    )

    text = f'''\
<b>Статистика по комиксам.</b>

Всего <b>{quote_count}</b>:
{text_year_by_counts}
    '''

    reply_markup = InlineKeyboardMarkup.from_button(
        InlineKeyboardButton('⬅️ Назад', callback_data=PATTERN_QUERY_QUOTE_STATS)
    )

    message.edit_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup,
    )


@mega_process
def on_get_users(update: Update, context: CallbackContext):
    r"""
    Получение пользователей:
     - /get_users
     - get[ _]users (\d+)
    """

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
    """
    Получение цитаты из базы:
     - /get_quote <номер цитаты>
     - get quote <номер цитаты>
    """

    get_local_quote(update, context)


@mega_process
def on_get_external_quote(update: Update, context: CallbackContext):
    """
    Получение цитаты из сайта:
     - /get_external_quote <номер цитаты>
     - get external quote <номер цитаты>
    """

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
    r"""
    Обновление цитаты в базе с сайта:
     - /update_quote (\d+)
     - update[ _]quote (\d+)
    """

    quote_id = get_quote_id(context)
    if not quote_id:
        reply_error('Номер цитаты не указан', update, context)
        return

    update_quote(quote_id, update, context)


@mega_process
def on_find_my(update: Update, context: CallbackContext):
    r"""
    Поиск цитат среди уже полученных:
     - /find_my
     - find[_ ]my (.+)
    """

    user = db.User.get_from(update.effective_user)

    value = get_context_value(context)
    items = user.find(value)

    if items:
        text = ', '.join(get_deep_linking(quote_id) for quote_id in items)
    else:
        text = 'Не найдено!'

    reply_info(
        text,
        update, context,
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True,
    )


@mega_process
def on_quote_comics(update: Update, context: CallbackContext):
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


def setup(updater: Updater):
    dp = updater.dispatcher

    dp.add_handler(CommandHandler('start', on_start))

    dp.add_handler(CommandHandler('help', on_help))
    dp.add_handler(
        MessageHandler(
            Filters.regex(r'(?i)^help$|^помощь$'),
            on_help
        )
    )
    dp.add_handler(
        CallbackQueryHandler(
            on_help, pattern=f"^{BUTTON_HELP_COMMON.callback_data}|{BUTTON_HELP_ADMIN.callback_data}$"
        )
    )

    dp.add_handler(CommandHandler('more', on_request))

    dp.add_handler(CommandHandler('settings', on_settings))
    dp.add_handler(
        MessageHandler(
            Filters.regex(r'(?i)^settings$|^настройк[иа]$'),
            on_settings
        )
    )
    dp.add_handler(CallbackQueryHandler(on_settings, pattern=SettingState.MAIN.get_pattern_full()))
    dp.add_handler(CallbackQueryHandler(on_settings_year, pattern=SettingState.YEAR.get_pattern_full()))
    dp.add_handler(CallbackQueryHandler(on_settings_limit, pattern=SettingState.LIMIT.get_pattern_full()))

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
            FILTER_BY_ADMIN & Filters.regex(PATTERN_QUOTE_STATS),
            on_get_quote_stats
        )
    )
    dp.add_handler(CallbackQueryHandler(on_get_quote_stats, pattern=PATTERN_QUOTE_STATS))
    dp.add_handler(CallbackQueryHandler(on_get_comics_stats, pattern=PATTERN_COMICS_STATS))

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

    dp.add_handler(CommandHandler('find_my', on_find_my, FILTER_BY_ADMIN))
    dp.add_handler(
        MessageHandler(
            FILTER_BY_ADMIN & Filters.regex(r'(?i)^find[ _]my (.+)$'),
            on_find_my
        )
    )

    dp.add_handler(MessageHandler(Filters.text, on_request))
    dp.add_handler(CallbackQueryHandler(on_quote_comics, pattern=r'^\d+$'))

    fill_commands_for_help(dp)

    dp.add_error_handler(on_error)
