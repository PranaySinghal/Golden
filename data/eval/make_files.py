"""Seeded test files that push the app past the samples it was built on.

Each file starts from data we know to be right and has specific problems put
into it, so there is a correct answer to score against (`KEYS`). The same seed
always writes the same files:

    cd backend && uv run python ../data/eval/make_files.py            # -> data/eval/files/
    cd backend && uv run python ../data/eval/evaluate.py --offline    # score them

Nothing here is a real person or a real customer. Company names, tickers and
head-office postal codes are public facts about listed companies.
"""

import csv
import io
import random
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from openpyxl import Workbook

OUT = Path(__file__).resolve().parent / "files"
SEED = 11


@dataclass
class Problem:
    """Something wrong that was put into a file, and which checks may report it."""

    what: str
    column: str
    detectors: tuple[str, ...]


@dataclass
class FillCheck:
    """A column a model could fill in, with the right answer for each value."""

    name: str
    based_on: str
    instruction: str
    kind: str
    choices: tuple[str, ...]
    # value in `based_on` (as written in the file) -> acceptable answers, lowercased
    truth: dict[str, set[str]]


@dataclass
class Key:
    """What a perfect run on one file looks like."""

    filename: str
    problems: list[Problem] = field(default_factory=list)
    # connector -> columns that should be offered
    offers: dict[str, list[str]] = field(default_factory=dict)
    # columns no connector should ever be offered for
    traps: list[str] = field(default_factory=list)
    # column -> {postal code: (latitude, longitude)} for a few codes we know
    positions: dict[str, dict[str, tuple[float, float]]] = field(default_factory=dict)
    postal_country: str = ""
    fills: list[FillCheck] = field(default_factory=list)
    # column -> what it should add up to once cleaned
    totals: dict[str, float] = field(default_factory=dict)
    rows_after_cleaning: int | None = None
    header: bool = True
    # The column names a reader would expect to see, when the file has them.
    columns: list[str] | None = None
    expect_no_issues: bool = False
    notes: str = ""


def _csv(rows: list[list[object]], delimiter: str = ",") -> str:
    buffer = io.StringIO()
    csv.writer(buffer, delimiter=delimiter, lineterminator="\n").writerows(rows)
    return buffer.getvalue()


# --- 1. listed companies --------------------------------------------------------------------

INDUSTRIES = (
    "Technology",
    "Retail",
    "Finance",
    "Healthcare",
    "Energy",
    "Consumer Goods",
    "Industrials",
    "Telecom",
    "Automotive",
    "Media",
    "Transport",
)
# ticker, name, industry, acceptable websites, head-office postal code
COMPANIES: list[tuple[str, str, str, set[str], str]] = [
    ("AAPL", "Apple Inc.", "Technology", {"apple.com"}, "95014"),
    ("MSFT", "Microsoft Corporation", "Technology", {"microsoft.com"}, "98052"),
    ("NVDA", "NVIDIA Corporation", "Technology", {"nvidia.com"}, "95051"),
    ("INTC", "Intel Corporation", "Technology", {"intel.com"}, "95054"),
    ("IBM", "International Business Machines Corporation", "Technology", {"ibm.com"}, "10504"),
    ("ORCL", "Oracle Corporation", "Technology", {"oracle.com"}, "78741"),
    ("CSCO", "Cisco Systems, Inc.", "Technology", {"cisco.com"}, "95134"),
    ("META", "Meta Platforms, Inc.", "Technology", {"meta.com", "about.meta.com"}, "94025"),
    ("AMZN", "Amazon.com, Inc.", "Retail", {"amazon.com", "aboutamazon.com"}, "98109"),
    ("WMT", "Walmart Inc.", "Retail", {"walmart.com", "corporate.walmart.com"}, "72716"),
    ("HD", "The Home Depot, Inc.", "Retail", {"homedepot.com"}, "30339"),
    ("TGT", "Target Corporation", "Retail", {"target.com", "corporate.target.com"}, "55403"),
    ("COST", "Costco Wholesale Corporation", "Retail", {"costco.com"}, "98027"),
    (
        "JPM",
        "JPMorgan Chase & Co.",
        "Finance",
        {"jpmorganchase.com", "jpmorgan.com", "chase.com"},
        "10017",
    ),
    ("BAC", "Bank of America Corporation", "Finance", {"bankofamerica.com"}, "28255"),
    ("GS", "The Goldman Sachs Group, Inc.", "Finance", {"goldmansachs.com", "gs.com"}, "10282"),
    ("MS", "Morgan Stanley", "Finance", {"morganstanley.com"}, "10036"),
    ("WFC", "Wells Fargo & Company", "Finance", {"wellsfargo.com"}, "94104"),
    ("PFE", "Pfizer Inc.", "Healthcare", {"pfizer.com"}, "10001"),
    ("JNJ", "Johnson & Johnson", "Healthcare", {"jnj.com"}, "08933"),
    ("MRK", "Merck & Co., Inc.", "Healthcare", {"merck.com"}, "07065"),
    ("ABBV", "AbbVie Inc.", "Healthcare", {"abbvie.com"}, "60064"),
    (
        "XOM",
        "Exxon Mobil Corporation",
        "Energy",
        {"exxonmobil.com", "corporate.exxonmobil.com"},
        "77389",
    ),
    ("CVX", "Chevron Corporation", "Energy", {"chevron.com"}, "94583"),
    ("COP", "ConocoPhillips", "Energy", {"conocophillips.com"}, "77079"),
    (
        "KO",
        "The Coca-Cola Company",
        "Consumer Goods",
        {"coca-colacompany.com", "coca-cola.com", "coke.com"},
        "30313",
    ),
    ("PEP", "PepsiCo, Inc.", "Consumer Goods", {"pepsico.com"}, "10577"),
    ("PG", "The Procter & Gamble Company", "Consumer Goods", {"pg.com", "us.pg.com"}, "45202"),
    ("NKE", "NIKE, Inc.", "Consumer Goods", {"nike.com", "about.nike.com"}, "97005"),
    ("BA", "The Boeing Company", "Industrials", {"boeing.com"}, "22202"),
    ("CAT", "Caterpillar Inc.", "Industrials", {"caterpillar.com", "cat.com"}, "75039"),
    ("HON", "Honeywell International Inc.", "Industrials", {"honeywell.com"}, "28202"),
    ("MMM", "3M Company", "Industrials", {"3m.com"}, "55144"),
    ("VZ", "Verizon Communications Inc.", "Telecom", {"verizon.com"}, "10036"),
    ("T", "AT&T Inc.", "Telecom", {"att.com"}, "75202"),
    ("TMUS", "T-Mobile US, Inc.", "Telecom", {"t-mobile.com"}, "98006"),
    ("F", "Ford Motor Company", "Automotive", {"ford.com", "corporate.ford.com"}, "48126"),
    ("GM", "General Motors Company", "Automotive", {"gm.com"}, "48226"),
    ("TSLA", "Tesla, Inc.", "Automotive", {"tesla.com"}, "78725"),
    (
        "DIS",
        "The Walt Disney Company",
        "Media",
        {"thewaltdisneycompany.com", "disney.com"},
        "91521",
    ),
    ("NFLX", "Netflix, Inc.", "Media", {"netflix.com"}, "95032"),
    ("DAL", "Delta Air Lines, Inc.", "Transport", {"delta.com"}, "30354"),
    ("UAL", "United Airlines Holdings, Inc.", "Transport", {"united.com"}, "60606"),
    ("UPS", "United Parcel Service, Inc.", "Transport", {"ups.com"}, "30328"),
    ("FDX", "FedEx Corporation", "Transport", {"fedex.com"}, "38120"),
]
# A few head offices whose position we know well enough to check a lookup against.
US_POSITIONS = {
    "95014": (37.32, -122.03),
    "98052": (47.67, -122.12),
    "10001": (40.75, -73.99),
    "10017": (40.75, -73.97),
    "30313": (33.76, -84.40),
    "60606": (41.88, -87.64),
    "75202": (32.78, -96.80),
    "48126": (42.32, -83.18),
    "08933": (40.49, -74.44),
    "94104": (37.79, -122.40),
}


def _spellings(name: str, rng: random.Random) -> str:
    """The same company the way different people type it."""
    roll = rng.random()
    if roll < 0.15:
        return name.upper()
    if roll < 0.25:
        return name.replace(",", "").replace(".", "")
    if roll < 0.32:
        return f"  {name} "
    return name


def companies(rng: random.Random) -> tuple[bytes, Key]:
    rows: list[list[object]] = [["Company", "Ticker", "HQ Zip", "Employees", "Founded"]]
    fills_industry: dict[str, set[str]] = {}
    fills_site: dict[str, set[str]] = {}
    for ticker, name, industry, sites, postal in COMPANIES:
        for _ in range(rng.choice([1, 1, 2])):
            written = _spellings(name, rng)
            employees = rng.choice(["12,400", "98000", "n/a", "161,000", "45000", "7,300"])
            rows.append([written, ticker, postal, employees, rng.randint(1880, 2012)])
            fills_industry[written.strip()] = {industry.lower()}
            fills_site[written.strip()] = sites
    body = rows[1:]
    rng.shuffle(body)
    key = Key(
        filename="companies.csv",
        problems=[
            Problem(
                "Thousands separators and 'n/a' in a number column",
                "Employees",
                ("numbers_as_text", "placeholders"),
            ),
            Problem("Spaces around some company names", "Company", ("extra_spaces",)),
            Problem("One company typed several ways", "Company", ("category_variants",)),
        ],
        offers={
            "stock_price": ["Ticker"],
            "postal_geocode": ["HQ Zip"],
            "company_ticker": ["Company"],
        },
        traps=["Employees", "Founded"],
        positions={"HQ Zip": US_POSITIONS},
        postal_country="US",
        fills=[
            FillCheck(
                "Industry",
                "Company",
                "Industry. The company's main line of business.",
                "label",
                INDUSTRIES,
                fills_industry,
            ),
            FillCheck(
                "Website",
                "Company",
                "Website. The company's main web address.",
                "website",
                (),
                fills_site,
            ),
        ],
    )
    return _csv([rows[0], *body]).encode(), key


# --- 2. customers with UK and Canadian postcodes ---------------------------------------------

UK_CODES = {
    "SW1A 1AA": (51.50, -0.14),
    "M1 1AE": (53.48, -2.24),
    "EH1 1YZ": (55.95, -3.19),
    "B33 8TH": (52.48, -1.78),
    "CR2 6XH": (51.35, -0.08),
    "EC1A 1BB": (51.52, -0.10),
    "LS1 4AP": (53.80, -1.55),
    "BS1 4DJ": (51.45, -2.59),
}
CA_CODES = ["K1A 0B1", "M5V 3L9", "H2Y 1C6", "V6B 4Y8", "T2P 2M5"]
FIRST = ["Ann", "Bo", "Cy", "Di", "Eve", "Finn", "Gus", "Hana", "Ivo", "Jude", "Kit", "Lena"]
LAST = ["Lee", "Chen", "Diaz", "Evans", "Okafor", "Novak", "Reyes", "Singh", "Walsh", "Yilmaz"]


def customers(rng: random.Random) -> tuple[bytes, Key]:
    header = [
        "customer_id",
        "full_name",
        "email",
        "phone",
        "postcode",
        "ship_postcode",
        "country",
        "signup_date",
    ]
    clean: list[list[object]] = []
    country_truth: dict[str, set[str]] = {}
    for number in range(1, 281):
        name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
        email = f"{name.lower().replace(' ', '.')}{number}@example.com"
        # Every customer has their own number, written one of four ways.
        phone = rng.choice(
            [
                f"+44 20 7946 {number:04d}",
                f"020-7946-{number:04d}",
                f"(416) 555-{number:04d}",
                f"416555{number:04d}",
            ]
        )
        home = rng.choice(list(UK_CODES))
        if rng.random() < 0.3:
            ship = rng.choice(CA_CODES)
            country_truth[ship] = {"canada"}
        else:
            ship = rng.choice(list(UK_CODES))
            country_truth[ship] = {"united kingdom"}
        signup = date(2023, 1, 1) + timedelta(days=rng.randint(0, 700))
        clean.append(
            [f"C{number:04d}", name, email, phone, home, ship, "United Kingdom", signup.isoformat()]
        )

    rows = [list(row) for row in clean]
    for row in rng.sample(rows, 14):
        row[2] = str(row[2]).replace("@", " at ")  # not an email any more
    for row in rng.sample(rows, 9):
        row[3] = "0207"  # too short to be a phone number
    for row in rng.sample(rows, 60):
        row[6] = rng.choice(["UK", "uk ", "U.K.", "united kingdom"])
    for row in rng.sample(rows, 25):
        row[4] = str(row[4]).lower()
    exact = [list(row) for row in rng.sample(rows, 12)]
    near = []
    for row in rng.sample(rows, 8):
        copy = list(row)
        copy[1] = f" {str(copy[1]).upper()}"
        near.append(copy)
    rows += exact + near
    rng.shuffle(rows)
    key = Key(
        filename="customers_intl.csv",
        problems=[
            Problem("14 emails with no @", "email", ("contact_formats",)),
            Problem("9 phone numbers that are too short", "phone", ("contact_formats",)),
            Problem("One country written five ways", "country", ("category_variants",)),
            Problem("12 rows entered twice", "", ("duplicates",)),
            Problem(
                "8 customers entered again with the name typed differently",
                "customer_id",
                ("identifier_repeats", "duplicates"),
            ),
        ],
        offers={"postal_geocode": ["postcode"]},
        positions={"postcode": UK_CODES},
        postal_country="GB",
        fills=[
            FillCheck(
                "Ship country",
                "ship_postcode",
                "Ship country. The country this postcode is in.",
                "label",
                ("United Kingdom", "Canada"),
                country_truth,
            ),
        ],
        rows_after_cleaning=280,
        notes="ship_postcode mixes two countries in one column, on purpose.",
    )
    return _csv([header, *rows]).encode(), key


# --- 3. European orders ----------------------------------------------------------------------

PRODUCTS = {
    "Bürostuhl ergonomisch": "Furniture",
    "Schreibtisch höhenverstellbar": "Furniture",
    "Bücherregal Eiche": "Furniture",
    "Laptop 14 Zoll": "Electronics",
    "Kabellose Maus": "Electronics",
    "USB-C Ladegerät": "Electronics",
    "Monitor 27 Zoll": "Electronics",
    "Druckerpapier A4": "Office Supplies",
    "Kugelschreiber 10er Pack": "Office Supplies",
    "Aktenordner": "Office Supplies",
    "Regenjacke Herren": "Clothing",
    "Wollpullover Damen": "Clothing",
}
DE_CODES = {
    "10115": (52.53, 13.39),
    "80331": (48.14, 11.57),
    "50667": (50.94, 6.96),
    "20095": (53.55, 10.00),
    "01067": (51.05, 13.74),
    "04109": (51.34, 12.37),
    "60311": (50.11, 8.68),
    "70173": (48.78, 9.18),
}
DE_CITIES = {
    "10115": "Berlin",
    "80331": "München",
    "50667": "Köln",
    "20095": "Hamburg",
    "01067": "Dresden",
    "04109": "Leipzig",
    "60311": "Frankfurt",
    "70173": "Stuttgart",
}


def _german_number(value: float) -> str:
    whole, cents = f"{value:,.2f}".split(".")
    return f"{whole.replace(',', '.')},{cents}"


def orders_eu(rng: random.Random) -> tuple[bytes, Key]:
    header = ["Bestell-Nr", "Datum", "Kunde", "Produkt", "Menge", "Einzelpreis", "PLZ", "Stadt"]
    rows: list[list[object]] = []
    total_price = 0.0
    total_quantity = 0
    for number in range(1, 241):
        product = rng.choice(list(PRODUCTS))
        quantity = rng.randint(1, 12)
        price = round(rng.uniform(4, 1800), 2)
        code = rng.choice(list(DE_CODES))
        day = date(2024, 1, 1) + timedelta(days=rng.randint(0, 300))
        total_price += price
        total_quantity += quantity
        rows.append(
            [
                f"B-{number:05d}",
                day.strftime("%d.%m.%Y"),
                f"{rng.choice(LAST)} GmbH",
                product,
                quantity,
                f"{_german_number(price)} €",
                code,
                DE_CITIES[code],
            ]
        )
    key = Key(
        filename="orders_eu.csv",
        problems=[
            Problem(
                "Prices with decimal commas and a euro sign", "Einzelpreis", ("numbers_as_text",)
            ),
            Problem("Dates written day first with dots", "Datum", ("dates",)),
        ],
        offers={"postal_geocode": ["PLZ"], "company_ticker": []},
        traps=["Menge", "Bestell-Nr"],
        positions={"PLZ": DE_CODES},
        postal_country="DE",
        fills=[
            FillCheck(
                "Category",
                "Produkt",
                "Category. What kind of product this is.",
                "label",
                ("Furniture", "Electronics", "Office Supplies", "Clothing"),
                {name: {category.lower()} for name, category in PRODUCTS.items()},
            ),
        ],
        totals={"Einzelpreis": round(total_price, 2), "Menge": float(total_quantity)},
        notes="Semicolons, decimal commas, Windows-1252. Two postal codes start with zero.",
    )
    return _csv([header, *rows], delimiter=";").encode("cp1252"), key


# --- 4. a survey in Excel --------------------------------------------------------------------

COMMENTS = {
    "Really happy with the service, the team was quick and friendly.": "Positive",
    "Delivery was fast and everything worked first time.": "Positive",
    "Great value, I would buy again.": "Positive",
    "Support solved my problem in minutes. Thank you!": "Positive",
    "The product broke after a week and nobody answered my emails.": "Negative",
    "Far too expensive for what you get.": "Negative",
    "I waited three weeks and the order was wrong.": "Negative",
    "Terrible experience, I want a refund.": "Negative",
    "It arrived on the date stated.": "Neutral",
    "I ordered the blue one.": "Neutral",
    "No comment.": "Neutral",
    "Used it twice so far.": "Neutral",
}


def survey(rng: random.Random) -> tuple[bytes, Key]:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.title = "Responses"
    sheet.append(["Customer satisfaction survey"])
    sheet.append(["Exported 2024-11-02 by the research team"])
    sheet.append([])
    sheet.append(["Respondent", "Age band", "Satisfied", "Would recommend", "Score", "Comment"])
    for number in range(1, 201):
        satisfied = rng.choice(
            ["Agree", "agree", "AGREE ", "Strongly agree", "Disagree", "disagree", "Neither"]
        )
        recommend = rng.choice(["Yes", "yes", "Y", "No", "no", "N/A"])
        score: object = rng.randint(1, 10)
        if rng.random() < 0.12:
            score = rng.choice(["N/A", "-", "none"])
        sheet.append(
            [
                f"R{number:03d}",
                rng.choice(["18-24", "25-34", "35-44", "45-54", "55+"]),
                satisfied,
                recommend,
                score,
                rng.choice(list(COMMENTS)),
            ]
        )
    notes = workbook.create_sheet("Notes")
    notes.append(["Do not share outside the team."])
    buffer = io.BytesIO()
    workbook.save(buffer)
    key = Key(
        filename="survey.xlsx",
        problems=[
            Problem(
                "'N/A', '-' and 'none' where a score should be",
                "Score",
                ("placeholders", "numbers_as_text"),
            ),
            Problem("'Agree' typed four ways", "Satisfied", ("category_variants", "extra_spaces")),
            Problem(
                "'Yes' and 'No' typed several ways",
                "Would recommend",
                ("category_variants", "placeholders"),
            ),
        ],
        columns=["Respondent", "Age band", "Satisfied", "Would recommend", "Score", "Comment"],
        traps=["Respondent", "Age band", "Score", "Comment"],
        fills=[
            FillCheck(
                "Sentiment",
                "Comment",
                "Sentiment. Whether the comment is positive, negative or neutral.",
                "label",
                ("Positive", "Negative", "Neutral"),
                {text: {mood.lower()} for text, mood in COMMENTS.items()},
            ),
        ],
        notes="Three lines above the header row, and a second sheet that isn't data.",
    )
    return buffer.getvalue(), key


# --- 5. a wide file full of look-alikes ------------------------------------------------------


def inventory(rng: random.Random) -> tuple[bytes, Key]:
    header = [
        "sku",
        "model_year",
        "state",
        "bin",
        "product_line",
        "batch",
        "unit_cost",
        "reorder_level",
    ]
    header += [f"m{number:02d}" for number in range(1, 63)]
    lines = ["Garden Group", "Kitchen Group", "Outdoor Group", "Workshop Group"]
    rows: list[list[object]] = []
    for number in range(150):
        row: list[object] = [
            10000 + number * 7,  # five digits, never repeats: an id, not a postal code
            rng.randint(2015, 2024),  # four digits that repeat: years
            rng.choice(["CA", "NY", "TX", "WA", "FL", "IL"]),  # short capitals: not tickers
            rng.choice(["A1", "B2", "C3", "D4"]),
            rng.choice(lines),  # ends like a company name, isn't one
            rng.choice([20231, 20232, 20233, 20241, 20242]),  # five digits that repeat
            round(rng.uniform(2, 400), 2),
            rng.choice([10000, 12500, 15000, 20000]),  # five digits that repeat, a quantity
        ]
        row += [round(rng.uniform(0, 100), 3) if rng.random() > 0.3 else "" for _ in range(62)]
        rows.append(row)
    key = Key(
        filename="inventory_traps.csv",
        traps=header[:8],
        expect_no_issues=False,
        notes="70 columns. Nothing here is a postal code, a company or a stock symbol.",
    )
    return _csv([header, *rows]).encode(), key


# --- 6. six rows and no header ---------------------------------------------------------------


def tiny(rng: random.Random) -> tuple[bytes, Key]:
    rows = [
        [1001, "Ann Lee", "ann.lee@example.com", "2024-01-05", "90210", "1200.50"],
        [1002, "Bo Chen", "bo.chen@example.com", "2024-01-09", "10001", "860.00"],
        [1003, "Cy Diaz", "cy.diaz@example", "2024-02-11", "90210", "N/A"],
        [1004, "Di Evans", "di.evans@example.com", "2024-02-14", "60601", "415.25"],
        [1005, "Eve Okafor", "eve.okafor@example.com", "2024-03-02", "10001", "990.10"],
        [1006, "Finn Novak", "finn.novak@example.com", "2024-03-20", "60601", "72.00"],
    ]
    key = Key(
        filename="tiny_headerless.csv",
        header=False,
        problems=[
            Problem("'N/A' where an amount should be", "", ("placeholders", "numbers_as_text")),
            Problem("One email with no domain ending", "", ("contact_formats",)),
        ],
        notes="No header row, and too few rows for most thresholds.",
    )
    return _csv(rows).encode(), key


# --- 7. fifty thousand events ----------------------------------------------------------------


def events(rng: random.Random) -> tuple[bytes, Key]:
    header = ["event_id", "user_id", "timestamp", "event_type", "amount", "zip"]
    codes = [f"{rng.randint(10001, 99950):05d}" for _ in range(150)]
    rows: list[list[object]] = []
    total = 0.0
    start = datetime(2024, 3, 1, 8, 0)
    for number in range(1, 50001):
        moment = start + timedelta(seconds=number * 37)
        style = number % 3
        stamp = (
            moment.strftime("%Y-%m-%d %H:%M:%S")
            if style == 0
            else moment.strftime("%m/%d/%Y %H:%M")
            if style == 1
            else moment.strftime("%d %b %Y %H:%M")
        )
        kind = rng.choice(["Login", "login", "LOGIN ", "Purchase", "purchase", "Refund"])
        amount = round(rng.uniform(1, 250), 2)
        shown = f"${amount:.2f}" if number % 4 == 0 else f"{amount:.2f}"
        if number % 97 == 0:
            shown = "N/A"
        else:
            total += amount
        rows.append(
            [
                f"E{number:07d}",
                f"U{rng.randint(1, 4000):05d}",
                stamp,
                kind,
                shown,
                rng.choice(codes),
            ]
        )
    rows += [list(row) for row in rng.sample(rows, 1000)]
    rng.shuffle(rows)
    key = Key(
        filename="events_large.csv",
        problems=[
            Problem("Timestamps written three ways", "timestamp", ("dates",)),
            Problem(
                "One event type typed several ways",
                "event_type",
                ("category_variants", "extra_spaces"),
            ),
            Problem(
                "Dollar signs and 'N/A' in an amount column",
                "amount",
                ("numbers_as_text", "placeholders"),
            ),
            Problem("1,000 events entered twice", "", ("duplicates",)),
        ],
        offers={"postal_geocode": ["zip"]},
        postal_country="US",
        totals={"amount": round(total, 2)},
        rows_after_cleaning=50000,
        notes="51,000 rows. 150 different postal codes, more than one lookup run allows.",
    )
    return _csv([header, *rows]).encode(), key


# --- 8. nothing wrong with it ----------------------------------------------------------------


def already_clean(rng: random.Random) -> tuple[bytes, Key]:
    header = ["employee_id", "name", "department", "start_date", "salary"]
    rows: list[list[object]] = []
    for number in range(1, 121):
        start = date(2018, 1, 1) + timedelta(days=rng.randint(0, 2200))
        rows.append(
            [
                f"E{number:04d}",
                f"{rng.choice(FIRST)} {rng.choice(LAST)}",
                rng.choice(["Sales", "Support", "Finance", "Engineering"]),
                start.isoformat(),
                rng.randint(42, 140) * 1000,
            ]
        )
    key = Key(
        filename="already_clean.csv",
        expect_no_issues=True,
        traps=header,
        notes="A tidy file. The right answer is that there is nothing to fix.",
    )
    return _csv([header, *rows]).encode(), key


MAKERS = (companies, customers, orders_eu, survey, inventory, tiny, events, already_clean)


def build(seed: int = SEED) -> list[tuple[bytes, Key]]:
    """Every file with its answer key. The same seed always gives the same bytes."""
    return [maker(random.Random(f"{seed}-{maker.__name__}")) for maker in MAKERS]


def write(out: Path = OUT, seed: int = SEED) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for data, key in build(seed):
        path = out / key.filename
        path.write_bytes(data)
        paths.append(path)
    return paths


if __name__ == "__main__":
    for written in write():
        print(written.relative_to(Path.cwd()) if written.is_relative_to(Path.cwd()) else written)
    sys.exit(0)
