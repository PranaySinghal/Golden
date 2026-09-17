"""A small bounded cache for answers, keyed by (what the rows are, which question)."""

from collections import OrderedDict
from collections.abc import Iterator, MutableMapping

from app.questions.models import Answer

# Answers hold a value or a capped list of groups, so thousands of them are
# cheap next to the data itself. This only stops a long session growing forever.
MAX_CACHED_ANSWERS = 5_000

AnswerKey = tuple[str, str]


class LruCache(MutableMapping[AnswerKey, Answer]):
    """Keeps the most recently used answers, dropping the oldest beyond the limit."""

    def __init__(self, max_entries: int = MAX_CACHED_ANSWERS) -> None:
        self._max_entries = max_entries
        self._items: OrderedDict[AnswerKey, Answer] = OrderedDict()

    def __getitem__(self, key: AnswerKey) -> Answer:
        value = self._items[key]
        self._items.move_to_end(key)
        return value

    def __setitem__(self, key: AnswerKey, value: Answer) -> None:
        self._items[key] = value
        self._items.move_to_end(key)
        while len(self._items) > self._max_entries:
            self._items.popitem(last=False)

    def __delitem__(self, key: AnswerKey) -> None:
        del self._items[key]

    def __iter__(self) -> Iterator[AnswerKey]:
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)
