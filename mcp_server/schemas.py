"""Day 1 contracts based on assignment sections 7.1 and 7.2.

Decimal values serialize as strings to preserve money exactly. Both JSON numeric
values and decimal strings are accepted. Business-policy enforcement is Day 5.
"""

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

Currency = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
Identifier = Annotated[str, Field(min_length=1, max_length=100)]
Amount = Annotated[Decimal, Field(ge=0, max_digits=18, decimal_places=6, allow_inf_nan=False)]
SignedAmount = Annotated[Decimal, Field(max_digits=18, decimal_places=6, allow_inf_nan=False)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class LineItem(Contract):
    line_id: Identifier
    date: date
    category: Annotated[str, Field(min_length=1)]
    merchant: Annotated[str, Field(min_length=1)]
    amount: Amount
    currency: Currency
    description: str
    receipt_file: str | None = None


class ExpenseReport(Contract):
    report_id: Identifier
    employee_id: Identifier
    trip_id: Identifier
    submitted_at: AwareDatetime
    base_currency: Currency
    line_items: Annotated[list[LineItem], Field(min_length=1)]

    @model_validator(mode="after")
    def unique_lines(self) -> Self:
        ids = [line.line_id for line in self.line_items]
        if len(ids) != len(set(ids)):
            raise ValueError("line_id must be unique within a report")
        return self


class Money(Contract):
    amount: Amount
    currency: Currency


class Evidence(Contract):
    source: Identifier
    ref: Annotated[str, Field(min_length=1)]


class Finding(Contract):
    rule_id: Identifier
    severity: Literal["blocking", "query", "advisory"]
    line_id: Identifier | None
    observed: str
    permitted: str
    excess: Amount | None
    evidence: Annotated[list[Evidence], Field(min_length=1)]


class Reconciliation(Contract):
    line_id: Identifier
    status: Literal[
        "matched",
        "missing_receipt",
        "missing_transaction",
        "amount_mismatch",
        "outside_trip_dates",
        "duplicate",
    ]
    transaction_id: Identifier | None
    delta: SignedAmount | None


class DuplicateCandidate(Contract):
    # The screenshot gives an empty array, so this inner contract is a documented choice.
    line_id: Identifier
    matched_line_id: Identifier
    matched_report_id: Identifier
    evidence: Annotated[list[Evidence], Field(min_length=1)]


class DecisionMeta(Contract):
    model: Identifier
    policy_version: Identifier
    prompt_hash: Annotated[str, Field(min_length=1)]
    tokens_in: Annotated[int, Field(ge=0)]
    tokens_out: Annotated[int, Field(ge=0)]
    steps: Annotated[int, Field(ge=0)]
    latency_ms: Annotated[int, Field(ge=0)]
    created_at: AwareDatetime


class Decision(Contract):
    report_id: Identifier
    decision: Literal["auto_approve", "manager_review", "audit_hold"]
    confidence: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
    reimbursable_total: Money
    disallowed_total: Money
    reconciliation: list[Reconciliation]
    findings: list[Finding]
    duplicate_candidates: list[DuplicateCandidate]
    draft_query_to_submitter: str
    meta: DecisionMeta

    @model_validator(mode="after")
    def consistent_currency(self) -> Self:
        if self.reimbursable_total.currency != self.disallowed_total.currency:
            raise ValueError("decision totals must use the same currency")
        ids = [line.line_id for line in self.reconciliation]
        if len(ids) != len(set(ids)):
            raise ValueError("reconciliation line_id must be unique")
        return self


class ComputeLine(Contract):
    line_id: Identifier
    amount: Amount
    currency: Currency


class Cap(Contract):
    """Caller supplies policy values. A limit is per unit; quantity is explicit."""

    line_id: Identifier
    rule_id: Identifier
    kind: Literal["cap_excess", "whole_line"]
    limit: Amount | None = None
    quantity: Annotated[int, Field(strict=True, ge=1, le=10000)] = 1

    @model_validator(mode="after")
    def validate_kind(self) -> Self:
        if self.kind == "cap_excess" and self.limit is None:
            raise ValueError("cap_excess requires a limit")
        if self.kind == "whole_line" and (self.limit is not None or self.quantity != 1):
            raise ValueError("whole_line does not take a limit or quantity")
        return self


class ComputeRequest(Contract):
    lines: Annotated[list[ComputeLine], Field(min_length=1)]
    caps: list[Cap]
    base_currency: Currency
