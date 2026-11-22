<!-- page: 1 -->
# Globex IO — Private Webhook Relay Rotation Runbook

**Runbook Version:** v1.2  
**Tenant Workspace:** `globex-io`  

## 1. Zero-Downtime Relay Secret Rotation

Globex IO rotates its dual-signing webhook relay keys every **14 days** (stricter than the standard 30-day policy) using the internal cluster command:

```bash
cloudpulse relay rotate-keys --tenant globex-io --enclave eu-west-1 --grace-window 6h
```

Verify dual-key validation succeeds across both `relay-dub-01` and `relay-dub-02` before retiring the previous key slot.
