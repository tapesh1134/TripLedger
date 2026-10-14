# API guide

Public base URL: `http://127.0.0.1:8080/api`.
All calls except login need `Authorization: Bearer <token>`.
Requests and responses are JSON unless receipt multipart/binary is specified.

| Method | Path | Permission / purpose |
|---|---|---|
| POST | /auth/login | Email/password → token, user, expiresIn |
| GET | /auth/me | Current account |
| POST | /auth/logout | Revoke current token |
| POST | /auth/password | Current/new password; revoke all sessions |
| GET, POST | /users | Admin list/create |
| PUT | /users/{id} | Admin edit, reset password, disable, role/manager assignment |
| GET | /users/audit | Admin recent account audit |
| GET | /reports | Most recent 500 accessible reports |
| POST | /reports | Employee/manager creates own draft |
| GET | /reports/{id} | Owner, assigned manager, or admin; includes audit/revisions/reviews |
| PUT | /reports/{id} | Owner edits draft/clarification with rowVersion |
| POST | /reports/{id}/receipts | Owner, editable state; multipart field `file` |
| GET | /reports/{id}/receipts/{receiptId} | Authorized private attachment download |
| POST | /reports/{id}/submit | Owner, current rowVersion |
| POST | /reports/{id}/decision | Assigned manager, current rowVersion, action/reason/approvedAmount |
| POST | /reports/{id}/retry | Assigned manager/admin; failed AI and awaiting review |
| POST | /reports/{id}/assign | Admin; rowVersion and managerId |
| GET | /policies | Any authenticated account |
| POST | /policies | Admin; title, content, rules |
| POST | /policies/{id}/publish | Admin; index before activation |

## Create an account

```json
{
  "email": "employee@example.com",
  "name": "Employee One",
  "password": "REPLACE_WITH_A_UNIQUE_PASSWORD",
  "role": "EMPLOYEE",
  "managerId": "MANAGER_UUID_FROM_CREATE_RESPONSE",
  "active": true
}
```

For manager creation, use role MANAGER and managerId null. To reset an existing
user's password, PUT the account fields with a new password. Otherwise use password
null. User edits revoke that account's active sessions.

## Create a report

```json
{
  "title": "Client meeting in Paris",
  "purpose": "Quarterly planning",
  "destination": "Paris",
  "startDate": "2026-10-01",
  "endDate": "2026-10-04",
  "baseCurrency": "EUR",
  "rowVersion": 0,
  "lines": [{
    "lineId": "L1",
    "date": "2026-10-02",
    "category": "hotel",
    "merchant": "Hotel Example",
    "amount": "360.00",
    "currency": "EUR",
    "description": "Three-night business stay",
    "receiptId": null,
    "hotelNights": 3,
    "attendeeCount": null,
    "clientDinner": null,
    "alcoholAmount": null
  }]
}
```

After creating a report, upload a receipt, copy its returned id into the relevant
line, and PUT the full draft using the latest `row_version` response value as
`rowVersion`. Submit with `{ "rowVersion": <latest> }`.

## Manager action

```json
{
  "rowVersion": 3,
  "action": "APPROVE",
  "reason": "Verified itemized receipt and booking; hotel cap applied.",
  "approvedAmount": "300.00"
}
```

Other actions: CLARIFY or REJECT; approvedAmount may be null for those actions.
The supplied rowVersion must come from the latest report response, not this example.

## Internal contracts

Internal endpoints are direct service calls, protected by `X-Service-Key`, and never
forwarded through the gateway:

- Identity: POST `/internal/session`, GET `/internal/users/{id}`.
- Expense: GET `/internal/jobs/{jobId}`, GET `/internal/jobs/{jobId}/receipts/{id}`,
  GET `/internal/jobs/{jobId}/duplicates`, POST `/internal/jobs/{jobId}/started`,
  POST `/internal/jobs/{jobId}/result`.
- Policy: GET `/internal/policies/active`, GET `/internal/policies/{id}`.
- Python: POST `/internal/index`.

Queue: durable `tripledger.review`, default direct exchange, persistent messages:

```json
{"jobId":"UUID","reportId":"UUID","revision":1}
```

The worker trusts the Expense Service's fetched job snapshot, not report data in
the queue message. Terminal callback status is COMPLETED or FAILED.

HTTP statuses: 400 validation/business input, 401 unauthenticated/expired, 403 scope
or role violation, 404 missing record, 409 stale version/state conflict, 413 upload
limit, 429 sign-in limit, 503 unavailable dependency/unexpected service failure.
