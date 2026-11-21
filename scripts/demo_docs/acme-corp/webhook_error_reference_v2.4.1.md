<!-- page: 1 -->
# CloudPulse Webhook Integration & Error Reference

**Document Version:** v2.4.1  
**Applies To:** `@cloudpulse/sdk` (Node.js) and `cloudpulse-sdk` (Python)  

## 1. Overview & Delivery Guarantees

CloudPulse delivers real-time infrastructure and billing webhooks over HTTPS (`TLS 1.3` required in production) with at-least-once delivery semantics. Each delivery includes a unique `X-CloudPulse-Delivery-ID` UUID header for consumer idempotency and an HMAC-SHA256 signature header `X-CloudPulse-Signature-256`.

### 1.1 Supported SDK Compatibility Matrix

| SDK Version | Runtime Support | Signature Format | Default Timestamp Tolerance | Status |
| :--- | :--- | :--- | :--- | :--- |
| `v2.4.1` | Node 20+, Python 3.11+ | `t=<unix>,v1=<hex>` (Strict raw-byte digest) | `300 seconds` | Current GA |
| `v2.4.0` | Node 18+, Python 3.10+ | `t=<unix>,v1=<hex>` (Permissive JSON fallback) | `300 seconds` | Previous Stable (Rollback Target) |
| `v2.3.x` | Node 18+, Python 3.10+ | `v1=<hex>` (Legacy header) | `600 seconds` | Deprecated (EOL 2027-01-31) |

<!-- page: 6 -->
## 2. Authentication & Rate-Limit Error Codes

### 2.1 ERR_AUTH_4011 — Expired Scoped API Token
`ERR_AUTH_4011` indicates that the bearer token passed in `Authorization: Bearer <token>` exceeded its configured TTL (maximum 24 hours for short-lived workload tokens). Rotate the token via `POST /v2/oauth/token` using your client credentials.

### 2.2 ERR_RATE_4290 — Tenant API Burst Exceeded
`ERR_RATE_4290` is returned with HTTP status `429 Too Many Requests` when a tenant exceeds its sliding-window quota (`600 req/min` on Pro, `3,000 req/min` on Enterprise). Clients must inspect the `X-RateLimit-Reset` Unix epoch header and apply exponential backoff with full jitter before retrying.

### 2.3 ERR_TLS_5021 — Downstream Webhook Handshake Failure
`ERR_TLS_5021` occurs when the customer webhook receiver presents a self-signed certificate, TLS version older than `1.2`, or an expired intermediate CA chain. CloudPulse retries failed deliveries up to 8 times over 24 hours with exponential backoff (`15s, 60s, 5m, 15m, 1h, 4h, 8h, 10h`).

<!-- page: 14 -->
## 4.3 Webhook Signature Verification & Error Codes

### ERR_SIG_4092 — HMAC-SHA256 Payload Digest Mismatch (SDK v2.4.1)
`ERR_SIG_4092` is triggered on SDK `v2.4.1` when HTTP middleware (such as `express.json()`, FastAPI body parsers, or API gateways) parses and re-serializes the incoming JSON request body prior to HMAC-SHA256 verification. Because JSON re-serialization mutates key ordering, unicode escaping, or whitespace, the recomputed digest no longer matches `X-CloudPulse-Signature-256`.

In SDK `v2.4.0`, the verifier fell back to canonicalized JSON hashing when raw bytes were missing; **SDK `v2.4.1` intentionally removed the permissive JSON fallback** to close signature-malleability attacks.

#### Resolution Procedure
Pass the unparsed raw request byte buffer directly to `verifySignature()` before any JSON parsing middleware runs:

```ts
// Express example (Node.js @cloudpulse/sdk v2.4.1)
app.post(
  "/webhooks/cloudpulse",
  express.raw({ type: "application/json" }),
  (req, res) => {
    const sig = req.header("X-CloudPulse-Signature-256");
    cloudpulse.webhooks.verifySignature(req.body, sig, process.env.WEBHOOK_SECRET);
    const event = JSON.parse(req.body.toString("utf8"));
    res.sendStatus(200);
  }
);
```

If an immediate hotfix cannot bypass middleware mutation in production, follow the **Production Rollback Runbook (`v2.4`)** to pin back to SDK `v2.4.0` while refactoring the route middleware.

<!-- page: 15 -->
### ERR_SIG_4093 — Signature Timestamp Drift Exceeded
`ERR_SIG_4093` occurs when the `t=<unix>` timestamp inside `X-CloudPulse-Signature-256` differs from receiver system clock time by more than `300 seconds` (default tolerance). Verify NTP clock synchronization on receiver nodes or explicitly configure `toleranceSeconds` (maximum permitted value: `600 seconds`).
