<!-- page: 1 -->
# Production Rollback Runbook: Webhook SDK v2.4.1 Incident Recovery

**Runbook ID:** RB-WH-204  
**Version:** v2.4  
**Audience:** Tier-2 Support Engineers & On-Call SREs  

## 1. Trigger Conditions

Execute this rollback procedure when a customer upgraded to SDK `v2.4.1` experiences sustained `ERR_SIG_4092` signature verification failures exceeding `5%` of webhook traffic and cannot immediately remove JSON body-parsing middleware in front of `verifySignature()`.

<!-- page: 2 -->
## 2. Step-by-Step SDK Rollback Procedure

### Step 1: Pin SDK Back to v2.4.0
Instruct the customer engineering team to downgrade and redeploy their webhook consumer service:

```bash
# Node.js consumers
npm install @cloudpulse/sdk@2.4.0 --save-exact

# Python consumers
pip install cloudpulse-sdk==2.4.0
```

### Step 2: Verify Canary Webhook Health
Send a synthetic test event from the CloudPulse CLI and confirm HTTP `200 OK` without `ERR_SIG_4092`:

```bash
cloudpulse webhooks trigger --event invoice.paid --tenant acme-corp --canary
```

### Step 3: Replay Dead-Letter Queue (DLQ) Events
Once the canary returns `200 OK` for 3 consecutive probes, replay undelivered webhooks from the affected window (do not replay before Step 2 passes to avoid duplicate failure storms):

```bash
cloudpulse webhooks replay --tenant acme-corp --since 15m --status failed_sig
```

<!-- page: 3 -->
## 3. Post-Incident Follow-Up & Permanent Remediation

1. Open a P2 follow-up engineering ticket tracking migration to raw-byte middleware (`express.raw({ type: "application/json" })` or FastAPI `await request.body()`) so the customer can safely upgrade back to `v2.4.1`.
2. If webhook delivery loss persisted longer than **15 minutes**, page the **On-Call Principal SRE** via `#inc-sev1-bridge` and initiate a Sev-1 RCA report within 48 hours.
