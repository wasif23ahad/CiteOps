<!-- page: 1 -->
# CloudPulse SOC 2 Type II & ISO-27001 Security Compliance Policy

**Policy Version:** v2.1  
**Effective Date:** January 15, 2026  
**Owner:** Office of the CISO  

## 1. Independent Certifications & Audit Scope

CloudPulse Infrastructure maintains continuous compliance and annual third-party attestation for:
* **SOC 2 Type II** (Trust Services Criteria: Security, Availability, and Confidentiality) audited annually by an AICPA-accredited CPA firm.
* **ISO/IEC 27001:2022** certified Information Security Management System (ISMS) covering production infrastructure, CI/CD pipelines, and corporate endpoints.
* **GDPR** Data Processing Addendum (DPA) with EU Standard Contractual Clauses (SCCs) included for all paid plans.

<!-- page: 3 -->
## 2. Cryptographic Key Management & Secret Rotation

### 2.1 KMS Key Rotation Policy
* Master KMS Key Encryption Keys (KEKs) rotate automatically every **90 days** without downtime.
* Tenant Data Encryption Keys (DEKs) are isolated per workspace and rotated upon tenant offboarding or security incident remediation.
* Webhook HMAC signing secrets support dual-secret zero-downtime rotation with a recommended rotation interval of **30 days** (maximum 90 days for SOC 2 compliance checks).

### 2.2 Audit Logging & Retention
Immutable administrative, authentication, and data-access audit logs are streamed to write-once (WORM) object storage and retained for **365 days** by default (extendable to **7 years** under Enterprise Compliance Archive).

<!-- page: 5 -->
## 3. Data Residency, Penetration Testing & Regulatory Addenda

### 3.1 Data Residency Regions
Enterprise tenants may pin primary data storage and backups to **US-East (`us-east-1`)** or **EU-Central (`eu-central-1`, Frankfurt)**. Cross-region replication stays strictly within the selected sovereign geography when residency pinning is enabled.

### 3.2 Penetration Testing & Vulnerability Remediation SLAs
Independent CREST-certified penetration tests are conducted **semi-annually** (twice per year). Critical vulnerabilities (CVSS `>= 9.0`) must be patched within **24 hours**; High vulnerabilities (CVSS `7.0–8.9`) within **7 calendar days**; Medium vulnerabilities within **30 calendar days**.

### 3.3 HIPAA Business Associate Agreement (BAA) Policy
**Important Compliance Boundary:** A **HIPAA Business Associate Agreement (BAA) is NOT included by default** on Standard, Pro, or base Enterprise subscriptions. Customers processing Protected Health Information (PHI) must execute a dedicated **Enterprise HIPAA Security Addendum**, enable CMEK + single-tenant isolated compute, and disable free/shared diagnostic telemetry before transmitting PHI.

### 3.4 PCI-DSS Scope
CloudPulse does not store raw primary account numbers (PAN) or CVV codes. All subscription billing is delegated to Stripe (PCI-DSS Level 1 Service Provider).
