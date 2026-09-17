"""Plain-language labels for generated questions."""

from app.questions.models import DateGrain


def rows() -> str:
    return "How many rows are there?"


def distinct(column: str) -> str:
    return f'How many different "{column}" values are there?'


def average(column: str) -> str:
    return f'What\'s the average "{column}"?'


def total(column: str) -> str:
    return f'What\'s the total "{column}"?'


def rows_by(group: str) -> str:
    return f'How many rows are there for each "{group}"?'


def average_by(column: str, group: str) -> str:
    return f'What\'s the average "{column}" for each "{group}"?'


def rows_over_time(date: str, grain: DateGrain) -> str:
    return f'How many rows are there each {grain.value}, by "{date}"?'


def average_over_time(column: str, date: str, grain: DateGrain) -> str:
    return f'What\'s the average "{column}" each {grain.value}, by "{date}"?'
