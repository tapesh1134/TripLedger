"""Generate repeatable synthetic records. Full card numbers never exist here."""

import json
from pathlib import Path
from typing import Any

DEFAULT_PATH = Path(__file__).parent / "seed" / "data.json"


def generate() -> dict[str, Any]:
    employees = [
        dict(
            employee_id=f"EMP-{2231 + i}",
            name=f"Synthetic Employee {i + 1:02}",
            grade="Director" if i % 5 == 4 else "Consultant",
            cost_center=f"CC-{i % 4 + 1}",
            manager_id=f"MGR-{i % 3 + 1}",
            home_city="London",
            prior_violations_12m=i % 3,
        )
        for i in range(30)
    ]
    cities = [("Milan", "IT"), ("Paris", "FR"), ("Berlin", "DE"), ("London", "GB")]
    trips = []
    transactions = []
    settled = []
    for i in range(20):
        city, country = cities[i % len(cities)]
        employee_id = employees[i]["employee_id"]
        trips.append(
            dict(
                trip_id=f"TRP-{8890 + i}",
                employee_id=employee_id,
                purpose="Synthetic client workshop",
                city=city,
                country=country,
                start_date="2026-04-09",
                end_date="2026-04-12",
                hotel_nights=3,
                flights=[
                    dict(
                        segment_id=f"SEG-{i}",
                        cabin="economy",
                        duration_hours="2.00",
                        departure_date="2026-04-09",
                    )
                ],
            )
        )
        for j in range(30):
            # First employee aligns with the supplied Day 1 sample. First matching
            # transaction is deliberately on page two (sorted by txn_id).
            amount = f"{10 + j}.00"
            merchant = f"Synthetic Merchant {j:02}"
            mcc = "5812"
            if j == 21:
                amount, merchant, mcc = "412.00", "Hotel Ascot Milano", "7011"
            if j == 22:
                amount, merchant, mcc = "38.40", "UBER BV AMSTERDAM", "4121"
            if j == 23:
                amount, merchant = "96.00", "Trattoria Mandarin"
            currency = "USD" if j == 29 else "EUR"
            transactions.append(
                dict(
                    txn_id=f"TXN-{i:02}-{j:03}",
                    employee_id=employee_id,
                    posted_date="2026-04-10" if j == 23 else "2026-04-09",
                    merchant_raw=merchant,
                    mcc=mcc,
                    amount=amount,
                    currency=currency,
                    card_last4=f"{1000 + i:04}",
                )
            )
        settled.append(
            dict(
                report_id=f"EXP-SETTLED-{i:03}",
                line_id=f"OLD-{i:03}",
                employee_id=employee_id,
                date="2026-04-09",
                settled_at="2026-04-15",
                merchant="UBER *TRIP",
                amount="38.40",
                currency="EUR",
            )
        )
    # Outside the 12-month window, useful for testing the ledger filter.
    settled.append(
        dict(
            report_id="EXP-OLD",
            line_id="OLD-EXPIRED",
            employee_id="EMP-2231",
            date="2024-01-01",
            settled_at="2024-01-02",
            merchant="Synthetic old taxi",
            amount="12.00",
            currency="EUR",
        )
    )
    return dict(
        synthetic=True,
        as_of="2026-04-18",
        employees=employees,
        trips=trips,
        transactions=transactions,
        settled_lines=settled,
    )


def write_seed(path: Path = DEFAULT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(generate(), indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    write_seed()
    print("Generated 30 employees, 20 trips, 600 transactions and 21 settled lines.")
