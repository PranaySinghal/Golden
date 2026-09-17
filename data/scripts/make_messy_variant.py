"""Make a messier, seeded copy of a sample CSV for detector tests.

Columns are chosen by what the profiler says they hold, never by name, so this
works on any sample:

    cd backend && uv run python ../data/scripts/make_messy_variant.py \
        --input ../data/samples/Messy_Employee_dataset.csv \
        --output ../data/samples/Messy_Employee_dataset_messier.csv --seed 7

The same input and seed always produce the same file.
"""

import argparse
import csv
import datetime as dt
import io
import random
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND))

from app.config import Settings  # noqa: E402
from app.db import create_workspace, open_dataset_connection, raw_db_path, remove_workspace  # noqa: E402
from app.ingest.loader import ingest_to_file  # noqa: E402
from app.ingest.models import IngestOptions  # noqa: E402
from app.profile.models import DatasetProfile, SemanticRole  # noqa: E402
from app.profile.profiler import profile_table  # noqa: E402

CASE_SHARE = 0.05
SPACE_SHARE = 0.05
DATE_RESTYLE_SHARE = 0.15
MONEY_SHARE = 0.05
THOUSANDS_SUFFIX_SHARE = 0.05
PLACEHOLDER_SHARE = 0.02
EXACT_REPEAT_SHARE = 0.03
NEAR_REPEAT_SHARE = 0.02
PLACEHOLDERS = ["n/a", "-", "unknown"]


def profile_of(data: bytes, filename: str) -> DatasetProfile:
    workspace = create_workspace()
    try:
        ingest_to_file(raw_db_path(workspace), filename, data, IngestOptions(), Settings())
        conn = open_dataset_connection(raw_db_path(workspace))
        try:
            return profile_table(conn)
        finally:
            conn.close()
    finally:
        remove_workspace(workspace)


def recase(value: str, rng: random.Random) -> str:
    return value.upper() if rng.random() < 0.5 else value.lower()


def respace(value: str, rng: random.Random) -> str:
    return rng.choice([f" {value}", f"{value} ", f"  {value}  "])


def restyle_date(value: str, rng: random.Random, formats: list[str]) -> str:
    for fmt in formats:
        try:
            parsed = dt.datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
        # Only unambiguous styles, so the variant never changes what a date means.
        return rng.choice(
            [parsed.strftime("%Y-%m-%d"), f"{parsed.strftime('%b')} {parsed.day}, {parsed.year}"]
        )
    return value


def restyle_number(value: str, rng: random.Random) -> str:
    try:
        number = float(value)
    except ValueError:
        return value
    roll = rng.random()
    if roll < MONEY_SHARE:
        return f"${number:,.2f}"
    if roll < MONEY_SHARE + THOUSANDS_SUFFIX_SHARE and abs(number) >= 1000:
        return f"${number / 1000:.1f}k".replace(".0k", "k")
    if roll < MONEY_SHARE + THOUSANDS_SUFFIX_SHARE + PLACEHOLDER_SHARE:
        return rng.choice(PLACEHOLDERS)
    return value


def make_variant(data: bytes, filename: str, seed: int) -> tuple[bytes, dict[str, int]]:
    rng = random.Random(seed)
    profile = profile_of(data, filename)
    roles = {c.position: c.semantic_role for c in profile.columns}
    rows = list(csv.reader(io.StringIO(data.decode("utf-8-sig"))))
    header, body = rows[0], rows[1:]
    date_formats = ["%m/%d/%Y", "%d/%m/%Y", "%Y-%m-%d"]
    stats = {"recased": 0, "respaced": 0, "dates": 0, "numbers": 0, "exact": 0, "near": 0}

    for row in body:
        for index, value in enumerate(row):
            if not value.strip():
                continue
            role = roles.get(index)
            if role in (SemanticRole.CATEGORY, SemanticRole.TEXT):
                if rng.random() < CASE_SHARE:
                    row[index] = recase(row[index], rng)
                    stats["recased"] += 1
                if rng.random() < SPACE_SHARE:
                    row[index] = respace(row[index], rng)
                    stats["respaced"] += 1
            elif role is SemanticRole.DATE and rng.random() < DATE_RESTYLE_SHARE:
                row[index] = restyle_date(value, rng, date_formats)
                stats["dates"] += 1
            elif role is SemanticRole.MEASURE:
                changed = restyle_number(value, rng)
                if changed != value:
                    row[index] = changed
                    stats["numbers"] += 1

    text_columns = [i for i, r in roles.items() if r in (SemanticRole.CATEGORY, SemanticRole.TEXT)]
    output = list(body)
    for _ in range(round(EXACT_REPEAT_SHARE * len(body))):
        output.insert(rng.randrange(len(output) + 1), list(rng.choice(body)))
        stats["exact"] += 1
    for _ in range(round(NEAR_REPEAT_SHARE * len(body))):
        copy = list(rng.choice(body))
        if text_columns:
            index = rng.choice(text_columns)
            copy[index] = recase(copy[index], rng) + " "
        output.insert(rng.randrange(len(output) + 1), copy)
        stats["near"] += 1

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(output)
    return buffer.getvalue().encode("utf-8"), stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    data, stats = make_variant(args.input.read_bytes(), args.input.name, args.seed)
    args.output.write_bytes(data)
    print(f"Wrote {args.output} ({', '.join(f'{k}: {v}' for k, v in stats.items())})")


if __name__ == "__main__":
    main()
