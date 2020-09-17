#!/usr/bin/env python3
# -*- coding: utf-8 -*-

__author__ = 'ipetrash'


import datetime as DT
import time
from typing import List, Optional, Union, Callable, Tuple, Dict
import traceback

# pip install peewee
from peewee import (
    Model, TextField, ForeignKeyField, DateTimeField, DateField, IntegerField, fn, JOIN, ModelSelect
)
from playhouse.sqliteq import SqliteQueueDatabase

import telegram

from third_party import bash_im
from third_party.bash_im import shorten
from config import DIR, IGNORED_LAST_QUOTES


DB_DIR_NAME = DIR / 'database'
DB_FILE_NAME = str(DB_DIR_NAME / 'database.sqlite')

DB_DIR_NAME.mkdir(parents=True, exist_ok=True)

BACKUP_DIR_NAME = DIR / 'backup'


DB_DIR_NAME_ERROR = DIR / 'database_error'
DB_FILE_NAME_ERROR = str(DB_DIR_NAME_ERROR / 'database_error.sqlite')

DB_DIR_NAME_ERROR.mkdir(parents=True, exist_ok=True)


# This working with multithreading
# SOURCE: http://docs.peewee-orm.com/en/latest/peewee/playhouse.html#sqliteq
db = SqliteQueueDatabase(
    DB_FILE_NAME,
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
        query = Request.get_all_quote_id_by_user(self.id)
        if not with_comics:
            return query.count()

        return Quote.get_all_with_comics(
            where=Quote.id.in_(query)
        ).count()

    def get_years_of_quotes(self) -> Dict[int, bool]:
        years = {x: False for x in Quote.get_years()}
        if self.settings:
            for x in self.settings.get_years_of_quotes():
                years[x] = True

        return years

    def set_years_of_quotes(self, data: Dict[int, bool]):
        years = [year for year, is_selected in data.items() if is_selected]
        if not years and not self.settings:
            return

        if not self.settings:
            self.settings = Settings.create()
            self.save(only=[User.settings])

        self.settings.set_years_of_quotes(years)


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


class Quote(BaseModel):
    url = TextField(unique=True)
    text = TextField()
    date = DateField()
    rating = IntegerField()
    modification_date = DateField(default=DT.date.today)

    @property
    def date_str(self) -> str:
        return self.date.strftime('%d.%m.%Y')

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

        for url in quote.comics_url:
            comics_db = Comics.get_or_none(Comics.url == url)
            if not comics_db:
                Comics.create(
                    url=url,
                    quote=quote_db
                )

        return quote_db

    @classmethod
    def get_random(cls, limit=20) -> List['Quote']:
        return list(cls.select().order_by(fn.Random()).limit(limit))

    @classmethod
    def get_user_unique_random(
            cls,
            user_id: Union[int, User],
            years: List[int] = None,
            limit=20,
            ignored_last_quotes=IGNORED_LAST_QUOTES
    ) -> List['Quote']:
        # Last {ignored_last_quotes} returned quote's
        sub_query = Request.get_all_quote_id_by_user(user_id, ignored_last_quotes)

        where = cls.id.not_in(sub_query)
        if years:
            fn_year = fn.strftime('%Y', cls.date).cast('INTEGER')
            where = where & fn_year.in_(years)

        query = (
            cls.select()
            .where(where)
            .order_by(fn.Random())
            .limit(limit)
        )
        return list(query)

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

    def __str__(self):
        return self.__class__.__name__ + \
               f'(id={self.id}, url={self.url!r}, text={shorten(self.text)!r}, ' \
               f'date={self.date}, rating={self.rating}, comics_number={len(self.get_comics())})'


class Comics(BaseModel):
    url = TextField(unique=True)
    quote = ForeignKeyField(Quote, backref='comics')

    def get_comics_id(self) -> int:
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

    @classmethod
    def get_all_quote_id_by_user(cls, user_id: Union[int, User], ignored_last_quotes=-1) -> ModelSelect:
        query = (
            Request
            .select(Request.quote_id)
            .where(
                (Request.quote_id.is_null(False)) & (Request.user_id == user_id)
            )
            .order_by(Request.id.desc())
        )
        if ignored_last_quotes > 0:
            query = query.limit(ignored_last_quotes)

        return query


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

            if update.message:
                message_id = update.message.message_id

        if isinstance(func, Callable):
            func = func.__name__

        Error.create(
            func_name=func,
            exception_class=e.__class__.__name__,
            error_text=str(e),
            stack_trace=traceback.format_exc(),
            user_id=user_id,
            chat_id=chat_id,
            message_id=message_id,
        )


db.connect()
db.create_tables([User, Chat, Quote, Comics, Request, Settings])

db_error.connect()
db_error.create_tables([Error])


if __name__ == '__main__':
    from config import ADMIN_USERNAME
    admin = User.get(User.username == ADMIN_USERNAME[1:])
    print('Admin:', admin)
    # print(*Quote.get_user_unique_random(admin, limit=5), sep='\n')
    # print(*Quote.get_user_unique_random(admin, years=[2004], limit=5), sep='\n')
    # print(admin.get_years_of_quotes())
    # admin.set_years_of_quotes({k: True for k in [2004, 2007, 2010]})
    # print(admin.get_years_of_quotes())
    print()

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
    for quote in Quote.get_user_unique_random(first_user, limit=limit):
        print(f'    {quote}')

    print()

    print('Quote.get_user_unique_random performance stats:')
    for limit in [100, 300, 500, 1000, 1500, 2000, 3000, 5000, 9999]:
        t = time.perf_counter()
        Quote.get_user_unique_random(first_user, limit=limit)
        print(f'    limit={limit:<4} elapsed {time.perf_counter() - t:.2f} secs')

    print()

    print('Request last:', Request.select().order_by(Request.id.desc()).first())
    print('Total requests of first user:', User.select().first().requests.select().count())
    print()

    # Quotes with comics
    print('Total quotes having comics of first user:', first_user.get_total_quotes(with_comics=True))
    print('Total quotes having comics:', Quote.get_all_with_comics().count())
    print()

    print('Random quote:', Quote.get_random(limit=1)[0])
    print()

    sub_query = Request.get_all_quote_id_by_user(first_user)
    items = [x.quote_id for x in sub_query]
    quote_id = 429385
    print(
        f'Quote #{quote_id} found in', [i for i, x in enumerate(items) if x == quote_id]
    )
    print()

    print('Last error:', Error.select().order_by(Error.id.desc()).first())
