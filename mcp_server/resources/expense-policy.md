# TripLedger expense policy
version: 2026-Q2-demo-1
status: invented teaching policy; synthetic data only
base_currency: EUR
receipt_threshold: 25.00 (inclusive)
auto_approval_ceiling: 2500.00
minimum_auto_approval_confidence: 0.85

| Rule | Statement | Severity |
|---|---|---|
| R-01 | Expense dates must fall within the booked trip dates, allowing one day either side for travel. | query |
| R-02 | An itemised receipt is required for every line of EUR 25.00 or more. | query |
| R-03 | Hotel nightly room rates must not exceed the city's grade-band cap in per-diem. Disallow only the excess. | blocking |
| R-04 | Meals must not exceed the daily per-head city cap. Client dinners have a higher cap and require an attendee count in the description. | query |
| R-05 | Premium flight cabin requires Director grade or above, or a flight segment longer than 6 hours. | blocking |
| R-06 | Alcohol is reimbursable only within a client dinner and only up to 25% of that bill. | query |
| R-07 | Prohibited merchant categories (gambling, cash advance, adult entertainment) are never reimbursable and always escalate. Disallow the whole line. | blocking |
| R-08 | The same merchant, date and amount claimed twice, within this report or a settled report from the last 12 months, is a suspected duplicate. | blocking |
| R-09 | Submission more than 60 days after the trip ends requires manager review. | query |
| R-10 | Reimbursable totals above EUR 2500 may not be auto-approved. | advisory |

Auto-approval also requires no blocking findings, no queries, confidence at least
0.85, and total strictly below the ceiling (FR-18). At exactly EUR 2500, use
manager_review: FR-18 is the stricter gate at the boundary. Any suspected duplicate,
prohibited category or missing required receipt forces at least manager_review.
The supplied document does not fully define audit_hold selection; do not invent
that rule. Day 3 exposes policy data; the final decision gates arrive later.

Missing grade/city allowance means unknown policy, never an invented zero or
unlimited allowance. Source policy and allowance version must accompany decisions.
Only use calculation tools for monetary comparisons and totals. A decision is a
review-queue entry, never authorization to execute a payment.
