"""Company name to stock symbol, matched against a list we already hold. Pure.

A name either matches exactly one listed company (after spelling differences
are removed), several, or none. Several is never resolved here: two share
classes of the same company, or two companies with the same name, is the
user's call.
"""

import json
from collections.abc import Iterable

from app.connectors.models import Company, LookupResult, Status
from app.connectors.normalize import company_key

CompanyIndex = dict[str, list[Company]]


def build_index(companies: Iterable[Company]) -> CompanyIndex:
    index: CompanyIndex = {}
    for company in companies:
        key = company_key(company.title)
        if not key:
            continue
        listed = index.setdefault(key, [])
        if all(existing.ticker != company.ticker for existing in listed):
            listed.append(company)
    for listed in index.values():
        listed.sort(key=lambda company: company.ticker)
    return index


def match_company(name: str, index: CompanyIndex) -> LookupResult:
    found = index.get(company_key(name), [])
    if not found:
        return LookupResult(Status.NOT_FOUND)
    if len(found) == 1:
        return LookupResult(Status.FOUND, value1=found[0].ticker, value2=found[0].title)
    return LookupResult(Status.AMBIGUOUS, value2=encode_candidates(found))


def encode_candidates(companies: list[Company]) -> str:
    return json.dumps([[company.ticker, company.title] for company in companies])


def decode_candidates(text: str | None) -> list[Company]:
    if not text:
        return []
    try:
        return [Company(str(ticker), str(title)) for ticker, title in json.loads(text)]
    except (ValueError, TypeError):
        return []
