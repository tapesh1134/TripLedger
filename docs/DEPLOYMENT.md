# Deployment and operations

## Local versus team use

The supplied launchers bind applications to 127.0.0.1. This is intentional: local
setup does not accidentally expose accounts or receipts to the network. To make
the application available to other people, deploy the React production build and
gateway behind an HTTPS reverse proxy. Java and Python services remain on a private
network. Do not expose PostgreSQL, RabbitMQ management, or internal service ports.

Example reverse proxy outline (adapt hostnames/certificates to your environment):

```nginx
server {
    listen 443 ssl;
    server_name expenses.example.com;
    # Configure your organization-issued certificate and key here.
    root /srv/tripledger/frontend/dist;
    client_max_body_size 10m;
    add_header X-Content-Type-Options nosniff always;
    add_header Referrer-Policy same-origin always;
    add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'" always;
    location /api/ {
        proxy_pass http://127.0.0.1:8080;
        proxy_read_timeout 190s;
        proxy_set_header Host $host;
    }
    location / { try_files $uri /index.html; }
}
```

The Vite development server and `vite preview` are for development/validation,
not the production web server. Build using `npm ci && npm run build` in frontend.

## Secrets and accounts

- Configure secrets outside source control. `.env` is ignored and never packaged.
- Use separate database logins with access only to each service's own database.
  Current local defaults use one DB_USER; set service-specific datasource environment
  overrides or deployment properties for stronger isolation.
- Protect and rotate SERVICE_KEY; deploy internal authentication with short-lived
  service credentials or mTLS when moving beyond a trusted private network.
- Use HTTPS for all browser traffic. Do not send real reports to a model provider
  until your organization has authorized that provider and its data handling.
- Have users change initial passwords. Account updates and password changes revoke
  sessions. Bootstrap credentials only create the first administrator on an empty DB.
- Sign-in throttling is per gateway process/client IP. Configure trusted-proxy-aware,
  distributed rate limiting at the public ingress for a multi-instance deployment.

## Durability and recovery

Back up all four PostgreSQL databases and RabbitMQ state. Receipt bytes are included
in the Expense database backup. Outbox records persist when the broker is down;
confirmed messages persist when the worker is down. A crash before a provider response
is committed can repeat that call. A committed result is reused on redelivery.

OutboxPublisher retries every five seconds. Inspect `outbox.attempts/last_error` when
reports remain PENDING. Check `ai-worker` logs for review errors and model access.
A worker killed mid-job leaves RUNNING until the broker redelivers its unacknowledged
message. A live but stalled process may require an operator restart; heartbeat/stuck-job
monitoring is not a supplied production orchestration system.

Never run `docker compose down -v` as an authentication fix. Existing database volumes
retain passwords and database versions. Use PostgreSQL administration to rotate a
password, or migrate/back up before changing image major versions. This project pins
PostgreSQL major 17 and uses a distinct named volume.

## Monitoring

Java health: `/actuator/health` on each private service port. Expense health includes
the database and RabbitMQ. Python API health: `/health`. The worker logs readiness,
failures and reconnect attempts. Request logs include correlation IDs and latency;
provider response bodies and API keys are not logged. Audit records capture account
changes, report transitions, manager reasons and policy publication.

## Known extension points

- Corporate card, HR and travel-booking adapters with real authentication and scopes.
- Payroll/export/payment workflow after approval (currently absent).
- Email/push notifications (currently users see status and clarification in the UI).
- Object storage and malware scanning for receipts, OCR/PDF support and retention jobs.
- Full legacy policy-rule parity and regression evaluation on your real case-study corpus.
- Cursor pagination and search beyond the current 500 most recent reports.
- SSO/OIDC, MFA and more granular multi-role permissions.
- Dedicated service identities, managed secret rotation, distributed rate limiting,
  circuit breakers, dashboards and workload-specific load tests.

These are deployment extensions, not silently simulated features.
