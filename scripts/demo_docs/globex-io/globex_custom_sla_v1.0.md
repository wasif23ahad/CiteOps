<!-- page: 1 -->
# Globex IO — Confidential Sovereign Enterprise SLA Addendum

**Contract Version:** v1.0  
**Tenant Workspace:** `globex-io` (STRICTLY CONFIDENTIAL — DO NOT SHARE WITH OTHER TENANTS)  

## Section 1. Custom Sovereign Enclave Guarantees

Under Globex IO's bespoke sovereign agreement:
* **Dedicated Region:** All compute and database workloads are pinned exclusively to **`eu-west-1` (Dublin Sovereign Enclave)**.
* **Custom Sev-1 RTO Guarantee:** **5 minutes** hot-active failover (tighter than standard CloudPulse 15-minute RTO).
* **Custom Error Code `ERR_GLOBEX_9901`:** Returned when the Globex Hardware Security Module (HSM) bridge fails mutual attestation; resolve by rotating the Globex HSM slot PIN via `globex-hsmctl rotate --slot 4`.
* **Dedicated Technical Account Manager:** Escalate directly to `tam-globex-private@cloudpulse.internal`.
