#!/usr/bin/env python3
# -*- coding: utf-8 -*-

__author__ = 'ipetrash'


import datetime as DT
import re
import time
import traceback
from typing import List, Optional, Union, Callable, Tuple, Dict, Type, Iterable

# pip install peewee
from peewee import (
    Model, TextField, ForeignKeyField, DateTimeField, DateField, IntegerField, fn, JOIN, ModelSelect, Field
)
from playhouse.sqliteq import SqliteQueueDatabase

import telegram

from third_party import bash_im
from third_party.bash_im import shorten, DATE_FORMAT_QUOTE
from config import ERRORS_PER_PAGE, DB_FILE_NAME, DB_FILE_NAME_ERROR, ITEMS_PER_PAGE, QUOTES_LIMIT
from common import get_date_time_str, get_date_str, replace_bad_symbols


def get_clear_name(full_name: str) -> str:
    full_name = re.sub(r'\s{2,}', ' ', full_name)
    return full_name.strip()


# This working with multithreading
# SOURCE: http://docs.peewee-orm.com/en/latest/peewee/playhouse.html#sqliteq
db = SqliteQueueDatabase(
    DB_FILE_NAME,
    pragmas={
        'foreign_keys': 1,
        'journal_mode': 'wal',    # WAL-mode
        'cache_size': -1024 * 64  # 64MB page-cache
    },
    use_gevent=False,     # Use the standard library "threading" module.
    autostart=True,
    queue_max_size=64,    # Max. # of pending writes that can accumulate.
    results_timeout=5.0,  # Max. time to wait for query to be executed.
    regexp_function=True
)


db_error = SqliteQueueDatabase(
    DB_FILE_NAME_ERROR,
    pragmas={
        'foreign_keys': 1,
        'journal_mode': 'wal',    # WAL-mode
        'cache_size': -1024 * 64  # 64MB page-cache
    },
    use_gevent=False,    # Use the standard library "threading" module.
    autostart=True,
    queue_max_size=64,   # Max. # of pending writes that can accumulate.
    results_timeout=5.0  # Max. time to wait for query to be executed.
)


class BaseModel(Model):
    class Meta:
        database = db

    @classmethod
    def get_first(cls) -> Type['BaseModel']:
        return cls.select().first()

    @classmethod
    def get_last(cls) -> Type['BaseModel']:
        return cls.select().order_by(cls.id.desc()).first()

    @classmethod
    def paginating(
            cls,
            page: int = 1,
            items_per_page: int = ITEMS_PER_PAGE,
            order_by: Field = None,
            filters: Iterable = None,
    ) -> List[Type['BaseModel']]:
        query = cls.select()

        if filters:
            query = query.filter(*filters)

        if order_by:
            query = query.order_by(order_by)

        query = query.paginate(page, items_per_page)
        return list(query)

    @classmethod
    def get_inherited_models(cls) -> List[Type['BaseModel']]:
        return sorted(cls.__subclasses__(), key=lambda x: x.__name__)

    @classmethod
    def print_count_of_tables(cls):
        items = []
        for sub_cls in cls.get_inherited_models():
            name = sub_cls.__name__
            count = sub_cls.select().count()
            items.append(f'{name}: {count}')

        print(', '.join(items))

    def __str__(self):
        fields = []
        for k, field in self._meta.fields.items():
            v = getattr(self, k)

            if isinstance(field, TextField):
                if v:
                    v = repr(shorten(v))

            elif isinstance(field, ForeignKeyField):
                k = f'{k}_id'
                if v:
                    v = v.id

            fields.append(f'{k}={v}')

        return self.__class__.__name__ + '(' + ', '.join(fields) + ')'


class Settings(BaseModel):
    years_of_quotes = TextField(default='')
    filter_quote_by_max_length_text = IntegerField(null=True)

    def get_years_of_quotes(self) -> List[int]:
        if not self.years_of_quotes:
            return []

        return list(map(int, self.years_of_quotes.split(',')))

    def set_years_of_quotes(self, items: List[int]):
        text = ','.join(map(str, sorted(items)))
        if text == self.years_of_quotes:
            return

        self.years_of_quotes = text
        self.save()

    def get_filter_quote_by_max_length_text(self) -> Optional[int]:
        return self.filter_quote_by_max_length_text

    def set_filter_quote_by_max_length_text(self, limit: Optional[int]):
        self.filter_quote_by_max_length_text = limit
        self.save()


# SOURCE: https://core.telegram.org/bots/api#user
class User(BaseModel):
    first_name = TextField()
    last_name = TextField(null=True)
    username = TextField(null=True)
    language_code = TextField(null=True)
    last_activity = DateTimeField(default=DT.datetime.now)
    settings = ForeignKeyField(Settings, null=True)

    def actualize(self, user: Optional[telegram.User]):
        self.first_name = user.first_name
        self.last_name = user.last_name
        self.username = user.username
        self.language_code = user.language_code
        self.last_activity = DT.datetime.now()

        self.save()

    @classmethod
    def get_from(cls, user: Optional[telegram.User]) -> Optional['User']:
        if not user:
            return

        user_db = cls.get_or_none(cls.id == user.id)
        if not user_db:
            user_db = cls.create(
                id=user.id,
                first_name=user.first_name,
                last_name=user.last_name,
                username=user.username,
                language_code=user.language_code
            )
        return user_db

    def get_total_quotes(self, with_comics=False) -> int:
        query = Request.get_all_quote_id_by_user(self.id).distinct()
        if not with_comics:
            return query.count()

        return Quote.get_all_with_comics(
            where=Quote.id.in_(query)
        ).count()

    def get_user_unique_random(
            self,
            years: List[int] = None,
            limit=QUOTES_LIMIT,
            filter_quote_by_max_length_text: int = None,
    ) -> List['Quote']:
        return Quote.get_user_unique_random(
            self,
            years=years,
            limit=limit,
            filter_quote_by_max_length_text=filter_quote_by_max_length_text,
        )

    def get_years_of_quotes(self) -> Dict[int, bool]:
        years = {year: False for year in Quote.get_years()}
        for year in self.get_list_years_of_quotes():
            years[year] = True

        return years

    def get_list_years_of_quotes(self) -> List[int]:
        return self.settings.get_years_of_quotes() if self.settings else []

    def set_years_of_quotes(self, data: Dict[int, bool]):
        years = [year for year, is_selected in data.items() if is_selected]
        if not years and not self.settings:
            return

        if not self.settings:
            self.settings = Settings.create()
            self.save(only=[User.settings])

        self.settings.set_years_of_quotes(years)

    def get_filter_quote_by_max_length_text(self) -> Optional[int]:
        if self.settings:
            return self.settings.get_filter_quote_by_max_length_text()

    def set_filter_quote_by_max_length_text(self, limit: int):
        if not self.settings:
            self.settings = Settings.create()
            self.save(only=[User.settings])

        self.settings.set_filter_quote_by_max_length_text(limit)

    def find_quote_ids(self, regex: str, case_insensitive=True) -> List[int]:
        user_quotes = Quote.id.in_(
            Request.get_all_quote_id_by_user(self).distinct()
        )
        return Quote.find(
            regex, case_insensitive,
            where=user_quotes,
        )

    @classmethod
    def get_by_page(
            cls,
            page: int = 1,
            items_per_page: int = ITEMS_PER_PAGE,
            order_by: Field = None,
    ) -> List['User']:
        if not order_by:
            order_by = cls.last_activity.desc()

        return cls.paginating(
            page=page,
            items_per_page=items_per_page,
            order_by=order_by
        )

    def get_short_title(self) -> str:
        full_name = self.first_name.strip()
        if self.last_name:
            full_name += ' ' + self.last_name.strip()

        # NOTE: Была проблема с арабскими буквами в имени из-за чего разворачивало весь текст справа на лево
        full_name = replace_bad_symbols(full_name)
        full_name = get_clear_name(full_name)
        full_name = shorten(full_name)

        if self.username:
            full_name += ' @' + self.username

        full_name = full_name.strip()

        last_activity = get_date_time_str(self.last_activity)

        return f'{full_name!r}, last_activity: {last_activity}, quotes: {self.get_total_quotes()}'


# SOURCE: https://core.telegram.org/bots/api#chat
class Chat(BaseModel):
    type = TextField()
    title = TextField(null=True)
    username = TextField(null=True)
    first_name = TextField(null=True)
    last_name = TextField(null=True)
    description = TextField(null=True)
    last_activity = DateTimeField(default=DT.datetime.now)

    def actualize(self, chat: Optional[telegram.Chat]):
        self.type = chat.type
        self.title = chat.title
        self.username = chat.username
        self.first_name = chat.first_name
        self.last_name = chat.last_name
        self.description = chat.description
        self.last_activity = DT.datetime.now()

        self.save()

    @classmethod
    def get_from(cls, chat: Optional[telegram.Chat]) -> Optional['Chat']:
        if not chat:
            return

        chat_db = cls.get_or_none(cls.id == chat.id)
        if not chat_db:
            chat_db = cls.create(
                id=chat.id,
                type=chat.type,
                title=chat.title,
                username=chat.username,
                first_name=chat.first_name,
                last_name=chat.last_name,
                description=chat.description
            )
        return chat_db

    @classmethod
    def get_by_page(
            cls,
            page: int = 1,
            items_per_page: int = ITEMS_PER_PAGE,
            order_by: Field = None,
            filters: Iterable = None,
    ) -> List['Chat']:
        if not order_by:
            order_by = cls.last_activity.desc()

        return cls.paginating(
            page=page,
            items_per_page=items_per_page,
            order_by=order_by,
            filters=filters,
        )

    def get_short_title_for_group(self) -> str:
        # NOTE: Была проблема с арабскими буквами в имени из-за чего разворачивало весь текст справа на лево
        title = self.title.strip() if self.title else ''
        title = replace_bad_symbols(title)
        title = get_clear_name(title)
        title = shorten(title)

        if self.username:
            title += f' @{self.username}'

        title = title.strip()
        if not title:
            title = f'#{self.id}'

        last_activity = get_date_time_str(self.last_activity)

        query_all_requests = Request.select().where(Request.chat == self)
        requests = query_all_requests.count()

        return f'{title!r}, type: {self.type}, last_activity: {last_activity}, requests: {requests}'


class Quote(BaseModel):
    url = TextField(unique=True)
    text = TextField()
    date = DateField()
    rating = IntegerField()
    modification_date = DateField(default=DT.date.today)

    @property
    def date_str(self) -> str:
        return self.date.strftime(DATE_FORMAT_QUOTE)

    def has_comics(self) -> bool:
        return bool(self.get_comics())

    def get_comics(self) -> List['Comics']:
        return list(self.comics)

    def get_comics_urls(self) -> List[str]:
        return [comics.url for comics in self.comics]

    def get_comics_file_names(self) -> List[str]:
        return [comics.file_name for comics in self.comics]

    def get_proxy(self) -> bash_im.Quote:
        return bash_im.Quote(
            self.url, self.text, self.date, self.rating, self.get_comics_urls()
        )

    @classmethod
    def get_from(cls, quote: bash_im.Quote) -> 'Quote':
        quote_db = cls.get_or_none(quote.id)
        if not quote_db:
            quote_db = cls.create(
                id=quote.id,
                url=quote.url,
                text=quote.text,
                date=quote.date,
                rating=quote.rating
            )

        for url in quote.comics_urls:
            comics_db = Comics.get_or_none(Comics.url == url)
            if not comics_db:
                Comics.create(
                    url=url,
                    quote=quote_db
                )

        return quote_db

    @classmethod
    def get_random(cls, limit=QUOTES_LIMIT) -> List['Quote']:
        return list(cls.select().order_by(fn.Random()).limit(limit))

    @classmethod
    def get_user_unique_random(
            cls,
            user_id: Union[int, User],
            years: List[int] = None,
            limit=QUOTES_LIMIT,
            filter_quote_by_max_length_text: int = None,
    ) -> List['Quote']:
        sub_query = Request.get_all_quote_id_by_user(user_id).distinct()

        where = cls.id.not_in(sub_query)
        if years:
            fn_year = fn.strftime('%Y', cls.date).cast('INTEGER')
            where = where & fn_year.in_(years)

        if filter_quote_by_max_length_text:
            where = where & (fn.LENGTH(cls.text) <= filter_quote_by_max_length_text)

        query = (
            cls.select()
            .where(where)
            .order_by(fn.Random())
            .limit(limit)
        )
        return list(query)

    @classmethod
    def get_number_of_unique_quotes(
            cls,
            user_id: Union[int, User],
            years: List[int] = None,
    ) -> int:
        sub_query = Request.get_all_quote_id_by_user(user_id).distinct()

        where = cls.id.not_in(sub_query)
        if years:
            fn_year = fn.strftime('%Y', cls.date).cast('INTEGER')
            where = where & fn_year.in_(years)

        query = cls.select().where(where)
        return query.count()

    @classmethod
    def get_all_with_comics(cls, where: ModelSelect = None) -> ModelSelect:
        query = cls.select()
        if where:
            query = query.where(where)

        return query\
            .join(Comics, JOIN.LEFT_OUTER)\
            .group_by(cls)\
            .having(fn.COUNT(Comics.id) > 0)

    @classmethod
    def get_year_by_counts(cls) -> List[Tuple[int, int]]:
        fn_year = fn.strftime('%Y', cls.date).cast('INTEGER')
        query = (
            cls
            .select(
                fn_year.alias('year'),
                fn.count(cls.id).alias('count')
            )
            .group_by(fn_year)
            .order_by(fn_year)
        )

        return [(row.year, row.count) for row in query]

    @classmethod
    def get_years(cls) -> List[int]:
        fn_year = fn.strftime('%Y', cls.date).cast('INTEGER')
        query = (
            cls
            .select(
                fn_year.alias('year')
            )
            .distinct()
            .order_by(fn_year)
        )
        return [row.year for row in query]

    @classmethod
    def find(cls, regex: str, case_insensitive=True, where: ModelSelect = None) -> List[int]:
        if case_insensitive:
            regex = f'(?i){regex}'

        expr = cls.text.regexp(regex)
        if where:
            expr &= where

        return [
            quote.id
            for quote in cls
                .select(cls.id)
                .where(expr)
        ]

    @classmethod
    def paginating_by_date(
            cls,
            page: int = 1,
            items_per_page: int = ITEMS_PER_PAGE,
            date: DT.date = None,
    ) -> List['Quote']:
        assert date, "Parameter 'date' must be defined!"

        return cls.paginating(
            page=page,
            items_per_page=items_per_page,
            order_by=cls.id.asc(),
            filters=[cls.date == date]
        )

    @classmethod
    def get_nearest_dates(
            cls,
            date: DT.date = None
    ) -> Tuple[Optional[DT.date], Optional[DT.date]]:
        query_nearest_before = cls.select(cls.date).where(cls.date < date).order_by(cls.date.desc()).limit(1).first()
        query_nearest_after = cls.select(cls.date).where(cls.date > date).order_by(cls.date.asc()).limit(1).first()
        return (
            query_nearest_before.date if query_nearest_before else None,
            query_nearest_after.date if query_nearest_after else None,
        )

    def __str__(self):
        return self.__class__.__name__ + \
               f'(id={self.id}, url={self.url!r}, text={shorten(self.text)!r}, ' \
               f'date={self.date}, rating={self.rating}, comics_number={len(self.get_comics())})'


class Comics(BaseModel):
    url = TextField(unique=True)
    quote = ForeignKeyField(Quote, backref='comics')

    def get_comics_id(self) -> str:
        return self.url.rstrip('/').split('/')[-1]

    def __str__(self):
        return self.__class__.__name__ + \
               f'(url={self.url!r}, quote_id={self.quote.id}, comics_id={self.get_comics_id()})'


class Request(BaseModel):
    func_name = TextField()
    date_time = DateTimeField(default=DT.datetime.now)
    elapsed_ms = IntegerField()
    user = ForeignKeyField(User, null=True, backref='requests')
    chat = ForeignKeyField(Chat, null=True, backref='requests')
    quote = ForeignKeyField(Quote, null=True, backref='requests')
    message = TextField(null=True)
    query_data = TextField(null=True)

    @classmethod
    def get_all_quote_id_by_user(
            cls,
            user_id: Union[int, User],
            fields: List[Field] = None
    ) -> ModelSelect:
        if not fields:
            fields = [cls.quote_id]

        query = (
            cls
            .select(*fields)
            .where(
                (cls.quote_id.is_null(False)) & (cls.user_id == user_id)
            )
            .order_by(cls.id.desc())
        )
        return query

    @classmethod
    def get_first_date_time(cls) -> DT.datetime:
        return cls.select().order_by(cls.id).first().date_time


class Error(BaseModel):
    class Meta:
        database = db_error

    date_time = DateTimeField(default=DT.datetime.now)
    func_name = TextField()
    exception_class = TextField()
    error_text = TextField()
    stack_trace = TextField()
    user_id = IntegerField(null=True)
    chat_id = IntegerField(null=True)
    message_id = IntegerField(null=True)

    @classmethod
    def create_from(cls, func: Union[Callable, str], e: Exception, update: telegram.Update = None) -> 'Error':
        user_id = chat_id = message_id = None
        if update:
            if update.effective_user:
                user_id = update.effective_user.id

            if update.effective_chat:
                chat_id = update.effective_chat.id

            if update.effective_message:
                message_id = update.effective_message.message_id

        if isinstance(func, Callable):
            func = func.__name__

        return cls.create(
            func_name=func,
            exception_class=e.__class__.__name__,
            error_text=str(e),
            stack_trace=traceback.format_exc(),
            user_id=user_id,
            chat_id=chat_id,
            message_id=message_id,
        )

    @classmethod
    def get_by_page(
            cls,
            page: int = 1,
            items_per_page: int = ERRORS_PER_PAGE,
            order_by: Field = None,
    ) -> List['User']:
        if not order_by:
            order_by = cls.date_time.desc()

        return cls.paginating(
            page=page,
            items_per_page=items_per_page,
            order_by=order_by
        )

    def get_short_title(self) -> str:
        date_time_str = get_date_time_str(self.date_time)
        return f'[{date_time_str}, {self.func_name}, {self.exception_class}] {self.error_text!r}'


db.connect()
db.create_tables([User, Chat, Quote, Comics, Request, Settings])

db_error.connect()
db_error.create_tables([Error])


if __name__ == '__main__':
    BaseModel.print_count_of_tables()
    print()

    from config import ADMIN_USERNAME
    admin: User = User.get(User.username == ADMIN_USERNAME[1:])
    print('Admin:', admin)
    # print(*Quote.get_user_unique_random(admin, limit=5), sep='\n')
    # print(*Quote.get_user_unique_random(admin, years=[2004], limit=5), sep='\n')
    # print(Quote.get_number_of_unique_quotes(admin))
    # print(admin.get_years_of_quotes())
    # admin.set_years_of_quotes({k: True for k in [2004, 2007, 2010]})
    # print(admin.get_years_of_quotes())
    # print(admin.get_list_years_of_quotes())
    print()

    date = DT.date.fromisoformat('2006-01-08')
    items = Quote.paginating_by_date(date=date)
    print(len(items), items)  # 0 []

    nearest_date_before, nearest_date_after = Quote.get_nearest_dates(date)
    print(nearest_date_before, nearest_date_after)
    # 2006-01-05 2006-01-11
    print()

    assert admin.find_quote_ids('Arux') == admin.find_quote_ids('ARUX')
    assert admin.find_quote_ids('Arux') == admin.find_quote_ids('Arux', case_insensitive=False)

    assert Quote.find('Arux') == Quote.find('ARUX')
    assert Quote.find('Arux') == Quote.find('Arux', case_insensitive=False)

    print('Total users:', User.select().count())
    print('Total chats:', Chat.select().count())

    assert User.get_from(None) is None
    assert Chat.get_from(None) is None

    print()

    first_user = User.select().first()
    print('First user:', first_user)

    first_chat = Chat.select().first()
    print('First chat:', first_chat)
    print()

    print('Total quotes:', Quote.select().count())
    for year, count in Quote.get_year_by_counts():
        print(f'    {year}: {count}')

    print()
    print("Years of quotes:", Quote.get_years())

    print()

    limit = 3
    print(f"User's unique random quotes ({limit}):")
    for quote in Quote.get_user_unique_random(admin, limit=limit):
        print(f'    {quote}')

    print()

    print('Quote.get_user_unique_random performance stats:')
    for limit in [100, 300, 500, 1000, 1500, 2000, 3000, 5000, 9999]:
        t = time.perf_counter()
        Quote.get_user_unique_random(admin, limit=limit)
        print(f'    limit={limit:<4} elapsed {time.perf_counter() - t:.2f} secs')

    print()

    print('Request last:', Request.select().order_by(Request.id.desc()).first())
    print('Total requests of admin:', admin.requests.select().count())
    print()

    # Quotes with comics
    print('Total quotes having comics of admin:', admin.get_total_quotes(with_comics=True))
    print('Total quotes having comics:', Quote.get_all_with_comics().count())
    print()

    print('Random quote:', Quote.get_random(limit=1)[0])
    print()

    sub_query = Request.get_all_quote_id_by_user(admin, fields=[Request.quote_id, Request.date_time])
    quote_id = 102776
    items = [(i, get_date_str(x.date_time)) for i, x in enumerate(sub_query) if x.quote_id == quote_id]
    max_num_len = len(str(max(x[0] for x in items)))
    str_template = '  #{:<%s} {}' % (max_num_len,)
    text = '\n'.join(str_template.format(num, date) for num, date in items)
    print(
        f'Quote #{quote_id} found in:\n{text}'
    )
    print()

    print('Last error:', Error.select().order_by(Error.id.desc()).first())
