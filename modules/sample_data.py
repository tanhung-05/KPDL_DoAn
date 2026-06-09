"""Synthetic retail data generator for live TA-PPHUIM demos."""

from __future__ import annotations

import random
from datetime import timedelta

import pandas as pd


def generate_synthetic_retail_data(
    num_rows: int = 1500,
    start_date: str = "2011-01-01",
    months: int = 6,
    seed: int = 42,
) -> pd.DataFrame:
    """Return a small synthetic Online-Retail-like transaction DataFrame.

    Output columns are ``InvoiceNo``, ``StockCode``, ``Description``,
    ``Quantity``, ``UnitPrice``, ``InvoiceDate``, and ``Country``.

    The generated data contains recurring products across monthly windows and
    three product combinations that peak in specific months. Quantities and
    prices are positive. A small controlled share of cancelled invoices and
    missing descriptions is included for raw-data demonstration.
    """
    if num_rows < 50:
        raise ValueError("num_rows must be at least 50 for a meaningful demo dataset.")
    if months < 1:
        raise ValueError("months must be at least 1.")

    rng = random.Random(seed)
    start = pd.Timestamp(start_date)
    month_starts = [start + pd.DateOffset(months=offset) for offset in range(months)]
    products = _product_catalog()
    catalog = _products_by_code(products)
    common_products = products[:12]
    peak_combos = [
        {"peak_month": 1 % months, "items": ["SYN1001", "SYN1002", "SYN1003"], "weight": 0.30},
        {"peak_month": 3 % months, "items": ["SYN1010", "SYN1011", "SYN1012"], "weight": 0.26},
        {"peak_month": 4 % months, "items": ["SYN1020", "SYN1021"], "weight": 0.24},
    ]

    rows: list[dict] = []
    invoice_counter = 100000
    while len(rows) < num_rows:
        month_index = rng.randrange(months)
        invoice_date = _random_datetime_in_month(rng, month_starts[month_index])
        invoice_no = str(invoice_counter)
        invoice_counter += 1
        if rng.random() < 0.015:
            invoice_no = "C" + invoice_no

        invoice_products = _choose_invoice_products(
            rng,
            common_products,
            peak_combos,
            products,
            month_index,
        )

        for stock_code in invoice_products:
            if len(rows) >= num_rows:
                break
            product = catalog[stock_code]
            description = product["Description"]
            if rng.random() < 0.01:
                description = pd.NA
            rows.append(
                {
                    "InvoiceNo": invoice_no,
                    "StockCode": stock_code,
                    "Description": description,
                    "Quantity": rng.randint(1, 8),
                    "UnitPrice": round(float(product["UnitPrice"]) * rng.uniform(0.9, 1.15), 2),
                    "InvoiceDate": invoice_date.strftime("%d/%m/%Y %H:%M"),
                    "Country": _choose_country(rng),
                }
            )

    return pd.DataFrame(
        rows,
        columns=[
            "InvoiceNo",
            "StockCode",
            "Description",
            "Quantity",
            "UnitPrice",
            "InvoiceDate",
            "Country",
        ],
    )


def _product_catalog() -> list[dict]:
    """Return a deterministic catalog with recurring and seasonal products."""
    entries = [
        ("SYN1001", "WHITE HANGING HEART T-LIGHT HOLDER", 2.55),
        ("SYN1002", "WHITE METAL LANTERN", 3.39),
        ("SYN1003", "CREAM CUPID HEARTS COAT HANGER", 2.75),
        ("SYN1004", "KNITTED UNION FLAG HOT WATER BOTTLE", 3.39),
        ("SYN1005", "RED WOOLLY HOTTIE WHITE HEART", 3.39),
        ("SYN1006", "SET 7 BABUSHKA NESTING BOXES", 7.65),
        ("SYN1007", "GLASS STAR FROSTED T-LIGHT HOLDER", 4.25),
        ("SYN1008", "HAND WARMER UNION JACK", 1.85),
        ("SYN1009", "HAND WARMER RED POLKA DOT", 1.85),
        ("SYN1010", "JUMBO BAG RED RETROSPOT", 2.08),
        ("SYN1011", "JUMBO BAG STRAWBERRY", 2.08),
        ("SYN1012", "JUMBO SHOPPER VINTAGE RED PAISLEY", 2.08),
        ("SYN1013", "LUNCH BAG RED RETROSPOT", 1.65),
        ("SYN1014", "LUNCH BAG BLACK SKULL", 1.65),
        ("SYN1015", "PACK OF 72 RETROSPOT CAKE CASES", 0.55),
        ("SYN1016", "REGENCY CAKESTAND 3 TIER", 12.75),
        ("SYN1017", "ASSORTED COLOUR BIRD ORNAMENT", 1.69),
        ("SYN1018", "PARTY BUNTING", 4.95),
        ("SYN1019", "VICTORIAN GLASS HANGING T-LIGHT", 1.25),
        ("SYN1020", "CHRISTMAS CRAFT TREE TOPPER", 2.95),
        ("SYN1021", "FELTCRAFT CHRISTMAS FAIRY", 4.25),
        ("SYN1022", "WOODEN PICTURE FRAME WHITE FINISH", 2.95),
        ("SYN1023", "WOODEN FRAME ANTIQUE WHITE", 2.95),
        ("SYN1024", "RECIPE BOX PANTRY YELLOW DESIGN", 2.95),
    ]
    return [
        {"StockCode": stock_code, "Description": description, "UnitPrice": unit_price}
        for stock_code, description, unit_price in entries
    ]


def _products_by_code(products: list[dict]) -> dict[str, dict]:
    """Return catalog keyed by StockCode."""
    return {product["StockCode"]: product for product in products}


def _choose_invoice_products(
    rng: random.Random,
    common_products: list[dict],
    peak_combos: list[dict],
    products: list[dict],
    month_index: int,
) -> list[str]:
    """Choose product StockCodes for one invoice."""
    chosen: list[str] = []
    for combo in peak_combos:
        probability = combo["weight"] if month_index == combo["peak_month"] else 0.04
        if rng.random() < probability:
            chosen.extend(combo["items"])

    common_codes = [product["StockCode"] for product in common_products]
    chosen.extend(rng.sample(common_codes, k=rng.randint(1, 5)))

    if rng.random() < 0.25:
        all_codes = [product["StockCode"] for product in products]
        chosen.extend(rng.sample(all_codes, k=rng.randint(1, 3)))

    return sorted(set(chosen))


def _random_datetime_in_month(rng: random.Random, month_start: pd.Timestamp) -> pd.Timestamp:
    """Return a random retail timestamp within a month."""
    month_end = month_start + pd.DateOffset(months=1)
    max_days = max(1, (month_end - month_start).days)
    return month_start + timedelta(
        days=rng.randrange(max_days),
        hours=rng.randint(8, 18),
        minutes=rng.choice([0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55]),
    )


def _choose_country(rng: random.Random) -> str:
    """Choose a country with UK-dominant retail distribution."""
    return rng.choices(
        ["United Kingdom", "France", "Germany", "Netherlands", "EIRE"],
        weights=[0.82, 0.06, 0.05, 0.04, 0.03],
        k=1,
    )[0]
