"""Strict public contracts for all nine MCP tools."""

from datetime import date
from typing import Annotated, Self

from pydantic import Field, model_validator

from mcp_server.schemas import Amount, Contract, Currency, Identifier


class EmployeeArgs(Contract):
    employee_id: Identifier


class TripArgs(Contract):
    trip_id: Identifier


class CardArgs(EmployeeArgs):
    from_date: date = Field(alias="from")
    to_date: date = Field(alias="to")
    cursor: Annotated[str, Field(pattern=r"^\d+$")] | None = None

    @model_validator(mode="after")
    def date_range(self) -> Self:
        if self.from_date > self.to_date:
            raise ValueError("from must not be after to")
        return self


class SettledArgs(EmployeeArgs):
    months: Annotated[int, Field(strict=True, ge=1, le=12)] = 12


class ReceiptArgs(Contract):
    file_path: Annotated[str, Field(min_length=1, max_length=500)]


class Receipt(Contract):
    merchant: Annotated[str, Field(min_length=1)]
    date: date
    currency: Currency
    total: Amount
    tax: Amount
    confidence: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]


class FxArgs(Contract):
    amount: Amount
    from_ccy: Currency
    to_ccy: Currency
    on_date: date


class MatchLine(Contract):
    line_id: Identifier
    date: date
    merchant: Annotated[str, Field(min_length=1)]
    amount: Amount
    currency: Currency
    category: str = "other"


class MatchTransaction(Contract):
    txn_id: Identifier
    posted_date: date
    merchant_raw: Annotated[str, Field(min_length=1)]
    amount: Amount
    currency: Currency
    employee_id: Identifier | None = None
    mcc: str | None = None
    card_last4: Annotated[str, Field(pattern=r"^\d{4}$")] | None = None


class MatchArgs(Contract):
    lines: Annotated[list[MatchLine], Field(max_length=100)]
    transactions: Annotated[list[MatchTransaction], Field(max_length=1000)]

    @model_validator(mode="after")
    def unique_ids(self) -> Self:
        for values in ([x.line_id for x in self.lines], [x.txn_id for x in self.transactions]):
            if len(values) != len(set(values)):
                raise ValueError("duplicate identifiers")
        return self
