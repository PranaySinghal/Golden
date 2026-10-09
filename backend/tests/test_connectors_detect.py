"""Which columns can be looked up from, decided by their values rather than their names."""

from collections.abc import Callable

from app.connectors.detect import Offer, find_offers
from app.connectors.matching import CompanyIndex, build_index
from tests.conftest import SAMPLE_FILES, SAMPLES_DIR, Dataset
from tests.connector_fakes import COMPANIES

MakeDataset = Callable[..., Dataset]
INDEX = build_index(COMPANIES)


def offers(
    make_dataset: MakeDataset, data: str, companies: CompanyIndex | None = None
) -> list[Offer]:
    ds = make_dataset(data)
    result = ds.apply()
    return find_offers(ds.conn, result.columns, companies)


def column(values: list[str], name: str = "a") -> str:
    return name + "\n" + "".join(f'"{value}"\n' for value in values)


def kinds(found: list[Offer]) -> list[tuple[str, str]]:
    return [(offer.connector, offer.column) for offer in found]


# --- postal codes ---------------------------------------------------------------------------


ADDRESSES = ["90210", "10001", "60601", "94105", "33101", "30301", "77002", "80202", "98101"]


def test_codes_spread_like_addresses_are_postal_codes_whatever_the_column_is_called(
    make_dataset: MakeDataset,
) -> None:
    found = offers(make_dataset, column(ADDRESSES * 2, "a"))

    assert kinds(found) == [("postal_geocode", "a")]
    assert found[0].distinct_values == 9
    # Five digits fits several countries. Which one is the user's to say.
    assert found[0].countries == ("US", "DE", "FR", "ES", "IT", "MX")


def test_repeating_five_digit_numbers_that_arent_addresses_are_left_alone(
    make_dataset: MakeDataset,
) -> None:
    batches = ["20231", "20232", "20233", "20241", "20242"] * 6
    quantities = ["10000", "12500", "15000", "20000", "10000"] * 6
    few = ["90210", "10001", "90210", "60601", "10001"]

    # Too close together to be places, round like amounts, or too few to tell.
    assert offers(make_dataset, column(batches, "a")) == []
    assert offers(make_dataset, column(quantities, "a")) == []
    assert offers(make_dataset, column(few, "a")) == []
    # A name that says so settles what the values can't.
    assert kinds(offers(make_dataset, column(few, "Zip"))) == [("postal_geocode", "Zip")]


def test_five_digit_numbers_that_never_repeat_are_ids_not_postal_codes(
    make_dataset: MakeDataset,
) -> None:
    assert offers(make_dataset, column([str(10000 + n) for n in range(30)], "a")) == []


def test_a_leading_zero_marks_a_code_rather_than_a_number(make_dataset: MakeDataset) -> None:
    found = offers(make_dataset, column(["02134", "10001", "90210", "60601"], "a"))

    assert kinds(found) == [("postal_geocode", "a")]


def test_codes_with_letters_have_a_shape_nothing_else_has(make_dataset: MakeDataset) -> None:
    canadian = offers(make_dataset, column(["K1A 0B1", "M5V 3L9", "H2Y 1C6"], "a"))
    british = offers(make_dataset, column(["SW1A 1AA", "M1 1AE", "EH1 1YZ"], "a"))

    assert canadian[0].countries == ("CA",)
    assert british[0].countries == ("GB",)


def test_four_digits_are_years_far_more_often_than_postal_codes(
    make_dataset: MakeDataset,
) -> None:
    years = ["2019", "2020", "2020", "2021", "2021"]

    assert offers(make_dataset, column(years, "a")) == []
    assert kinds(offers(make_dataset, column(years, "Postcode"))) == [
        ("postal_geocode", "Postcode")
    ]


def test_a_name_alone_is_never_enough(make_dataset: MakeDataset) -> None:
    data = "Zip,Company,Ticker\nnorth,red,one two\nsouth,blue,three four\neast,green,five six\n"

    assert offers(make_dataset, data, INDEX) == []


def test_a_mostly_blank_or_mixed_column_isnt_offered(make_dataset: MakeDataset) -> None:
    mixed = ["90210", "n/a", "unknown", "10001", "tbc"]

    assert offers(make_dataset, column(mixed, "a")) == []
    assert offers(make_dataset, "a,b\n90210,x\n,y\n,z\n") == []


# --- companies and stock symbols ------------------------------------------------------------


def test_names_ending_like_companies_are_companies(make_dataset: MakeDataset) -> None:
    names = ["Acme Tools Ltd", "Birch Foods Inc.", "Cobalt Air", "Delta Works LLC"]

    assert kinds(offers(make_dataset, column(names, "a"))) == [("company_ticker", "a")]


def test_ordinary_words_that_also_end_company_names_arent_enough(
    make_dataset: MakeDataset,
) -> None:
    lines = ["Garden Group", "Kitchen Group", "Outdoor Group", "Supply Co"] * 3

    assert offers(make_dataset, column(lines, "a")) == []
    # With a name that points the same way, they are.
    assert kinds(offers(make_dataset, column(lines, "Company"))) == [("company_ticker", "Company")]


def test_names_on_the_companies_list_are_companies_even_without_an_ending(
    make_dataset: MakeDataset,
) -> None:
    names = ["Apple", "Microsoft", "Walmart", "Some Local Shop"]

    assert offers(make_dataset, column(names, "a")) == []
    assert kinds(offers(make_dataset, column(names, "a"), INDEX)) == [("company_ticker", "a")]


def test_people_and_places_arent_companies(make_dataset: MakeDataset) -> None:
    people = ["Ann Lee", "Bo Chen", "Cy Diaz", "Di Evans"]

    assert offers(make_dataset, column(people, "a"), INDEX) == []


def test_symbols_on_the_list_are_stock_symbols(make_dataset: MakeDataset) -> None:
    found = offers(make_dataset, column(["AAPL", "MSFT", "WMT", "AAPL"], "a"), INDEX)

    assert kinds(found) == [("stock_price", "a")]


def test_short_capitals_that_arent_on_the_list_are_something_else(
    make_dataset: MakeDataset,
) -> None:
    states = ["CA", "NY", "TX", "CA", "WA"]

    assert offers(make_dataset, column(states, "a"), INDEX) == []
    assert offers(make_dataset, column(states, "Symbol"), INDEX) == []


def test_without_the_list_symbols_need_the_name_to_agree(make_dataset: MakeDataset) -> None:
    symbols = ["AAPL", "MSFT", "WMT"]

    assert offers(make_dataset, column(symbols, "a")) == []
    assert kinds(offers(make_dataset, column(symbols, "Ticker"))) == [("stock_price", "Ticker")]


# --- real files -----------------------------------------------------------------------------


def test_the_sample_files_get_no_offers_they_shouldnt(make_dataset: MakeDataset) -> None:
    for sample in ("Messy_Employee_dataset", "store_orders"):
        filename = SAMPLE_FILES[sample]
        ds = make_dataset((SAMPLES_DIR / filename).read_bytes(), filename=filename)
        found = find_offers(ds.conn, ds.apply().columns, INDEX)

        assert [offer for offer in found if offer.connector != "postal_geocode"] == [], sample
