<!-- page: 1 -->
# CloudPulse Enterprise Service Level Agreement (SLA)

**Contract Version:** v3.2  
**Customer Tier:** Enterprise Infrastructure Plan  

## Section 1. Availability Commitment & Service Credits

CloudPulse Infrastructure guarantees a Monthly Uptime Percentage of **99.99%** for all production multi-region API endpoints, control planes, and webhook dispatchers covered under an active Enterprise subscription.

### 1.1 Monthly Service Credit Schedule

| Monthly Uptime Percentage | Service Credit (% of Monthly Recurring Fee) |
| :--- | :--- |
| `< 99.99%` and `>= 99.90%` | `10%` credit |
| `< 99.90%` and `>= 99.00%` | `25%` credit |
| `< 99.00%` | `50%` credit (capped at 50% per billing month) |

Credit claims must be submitted via the CloudPulse Support Portal within **30 calendar days** of the incident end timestamp.

<!-- page: 4 -->
## Section 4. Security Architecture & Disaster Recovery Commitments

### Section 4.1 Network & Transport Security
All customer API traffic, webhook egress, and inter-region replication streams are encrypted in transit using **TLS 1.3** (with TLS 1.2 permitted solely for deprecated legacy webhook receivers until January 31, 2027). Mutual TLS (mTLS) is available for Enterprise PrivateLink connections.

### Section 4.2 Encryption at Rest & Sev-1 Failover Guarantees
Under Section 4.2 of the Enterprise SLA, CloudPulse strictly enforces **AES-256-GCM encryption at rest** across all relational databases, vector indices, object storage buckets, and encrypted write-ahead log backups using hardware-backed KMS envelope encryption. Customer-Managed Encryption Keys (CMEK via AWS KMS or GCP Cloud KMS) are supported on Enterprise plans.

For Disaster Recovery and High Availability under **Severity-1 (Sev-1) regional outages**, CloudPulse guarantees:
* **Guaranteed Sev-1 Recovery Time Objective (RTO):** **15 minutes** automated cross-region failover to a warm standby region.
* **Guaranteed Sev-1 Recovery Point Objective (RPO):** **5 minutes** maximum data loss via synchronous quorum WAL replication within region and continuous cross-region streaming.

<!-- page: 7 -->
## Section 6. Support Severity & Response Time Matrix

| Severity Level | Definition | Initial Response SLA | Continuous Update Cadence | Escalation Owner |
| :--- | :--- | :--- | :--- | :--- |
| **Sev-1 (Critical)** | Production outage, data loss risk, or total webhook delivery halt | **15 minutes** (24x7x365) | Every 30 minutes | On-Call Principal SRE + VP Engineering |
| **Sev-2 (High)** | Severe degradation with viable workaround | **1 hour** (24x7) | Every 2 hours | Tier-2 Support Lead |
| **Sev-3 (Normal)** | Non-critical bug or SDK integration question | **4 business hours** | Daily | Solutions Architect |
| **Sev-4 (Low)** | General inquiry or feature enhancement request | **1 business day** | As needed | Customer Success |
