"""Generate a deliberately messy sample CSV for testing DataPilot."""

import csv
import random
import os

random.seed(42)

REGIONS = {
    "clean": ["California", "New York", "Texas", "Florida", "Illinois"],
    "aliases": {
        "California": ["CA", "Calif.", "california", "ca", " California"],
        "New York": ["NY", "New York", "new york", "N.Y."],
        "Texas": ["TX", "Texas", "texas", "Tex."],
        "Florida": ["FL", "Florida", "florida", " FL "],
        "Illinois": ["IL", "Illinois", "illinois"],
    },
}

DATE_FORMATS = [
    lambda y, m, d: f"{y}-{m:02d}-{d:02d}",           # 2024-01-15
    lambda y, m, d: f"{['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][m-1]} {d}, {y}",  # Jan 15, 2024
    lambda y, m, d: f"{m:02d}/{d:02d}/{str(y)[2:]}",   # 01/15/24
    lambda y, m, d: f"{d:02d}-{m:02d}-{y}",             # 15-01-2024
]

SCORE_FORMATS = {
    "normal": lambda s: str(s),
    "word": lambda s: ["one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"][s - 1],
    "na": lambda _: "N/A",
    "none": lambda _: "",
    "dash": lambda _: "-",
}

REVENUE_FORMATS = [
    lambda v: f"${v:,.2f}",     # $1,234.56
    lambda v: str(round(v, 2)), # 1234.56
    lambda v: f"${v:.2f}",      # $1234.56
]

PRODUCTS = ["Widget A", "Widget B", "Service X", "Service Y", "Bundle Pro", "Basic Plan"]
CHANNELS = ["Online", "In-Store", "Phone", "Referral", "Social Media"]
SATISFACTION = ["Very Satisfied", "Satisfied", "Neutral", "Dissatisfied", "Very Dissatisfied"]


def generate_row(row_id: int) -> dict:
    # Date with mixed formats
    year = random.choice([2023, 2024])
    month = random.randint(1, 12)
    day = random.randint(1, 28)
    date_fmt = random.choice(DATE_FORMATS)
    date_str = date_fmt(year, month, day)

    # Region with aliases
    region_clean = random.choice(REGIONS["clean"])
    region_aliases = REGIONS["aliases"][region_clean]
    region = random.choice(region_aliases)

    # Score with mixed formats
    score_val = random.randint(1, 10)
    score_fmt_key = random.choices(
        ["normal", "word", "na", "none", "dash"],
        weights=[70, 10, 8, 7, 5],
    )[0]
    score = SCORE_FORMATS[score_fmt_key](score_val)

    # Revenue with mixed formats
    revenue_val = round(random.uniform(50, 5000), 2)
    revenue_fmt = random.choice(REVENUE_FORMATS)
    revenue = revenue_fmt(revenue_val)

    # Whitespace issues
    product = random.choice(PRODUCTS)
    if random.random() < 0.15:
        product = f"  {product} "
    channel = random.choice(CHANNELS)
    if random.random() < 0.1:
        channel = f" {channel}"

    satisfaction = random.choice(SATISFACTION)

    # Null patterns
    row = {
        "id": row_id,
        "date": date_str,
        "region": region,
        "product": product,
        "channel": channel,
        "score": score,
        "revenue": revenue,
        "satisfaction": satisfaction,
        "comments": f"Comment for order {row_id}" if random.random() > 0.3 else "",
    }

    # Scatter ~10% nulls
    nullable_fields = ["date", "region", "score", "revenue", "satisfaction", "comments"]
    if random.random() < 0.10:
        field = random.choice(nullable_fields)
        null_val = random.choice(["", "N/A", "none", "-", None])
        row[field] = null_val if null_val is not None else ""

    return row


def main():
    rows = []
    for i in range(1, 186):  # 185 unique rows
        rows.append(generate_row(i))

    # Add ~15 duplicate rows
    for _ in range(15):
        rows.append(random.choice(rows[:185]).copy())

    random.shuffle(rows)

    output_path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "apps",
        "web",
        "public",
        "sample_survey.csv",
    )
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "date", "region", "product", "channel", "score", "revenue", "satisfaction", "comments"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"Generated {len(rows)} rows to {output_path}")


if __name__ == "__main__":
    main()
