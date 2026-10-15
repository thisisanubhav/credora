# M8 security review

## Implemented offline controls

- HTTP API protects upload creation and batch status/error routes with a JWT authorizer. The Lambda API reads only API Gateway-verified `sub` claims, persists batch ownership, scopes idempotency to the owner, and gives non-owners a 404. The additive migration leaves local historical rows unowned; local mode is loopback-only and not suitable for public exposure.
- Presigned POSTs are short lived and constrain bucket, key prefix, size and CSV content type. Browser CORS is an exact origin allowlist, not an authentication mechanism. S3 blocks public access, uses bucket-owner enforcement and AES-256 encryption, denies non-TLS requests and expires upload objects after seven days.
- API and worker IAM roles are separate: upload API may `s3:PutObject` only to `uploads/*`; worker may `s3:GetObject` there and send only to its failure queue. Both use standard Lambda log/VPC execution policies. No wildcard S3 data access, SES access or resource-creation permissions are in either role.
- Lambda uses private subnets and bounded reserved concurrency; PostgreSQL connection credentials are externalized. The M5 HMAC/timestamp/replay checks remain the private n8n boundary, and M6 remains test-inbox-only. No AWS or Gemini key is committed.
- Offline tests check JWT ownership, S3 event shape, policy structure and handler imports. They do not prove live IAM, network, identity-provider or SES behavior.

## Open blockers before any public use

1. The M7 frontend does not acquire or refresh OIDC tokens. Anonymous access must **not** be enabled as a workaround. Decide an identity provider, tenant/audience policy, user lifecycle and abuse controls.
2. HTTP API throttling/WAF and per-subject quotas are not provisioned. [API Gateway throttling](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-throttling.html) helps control abuse but is not authorization. Upload object quotas, account spending alarms and retention/privacy policy require review.
3. RDS TLS uses `sslmode=require`: encryption is enforced, certificate/hostname verification is not. Bundle the RDS CA and use `verify-full` before production; see [AWS RDS TLS guidance](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/UsingWithRDS.SSL.html).
4. RDS/VPC/SG/endpoint, OIDC issuer, cloud-specific n8n Compose and dispatcher hosting are prerequisites outside the template. They are intentionally absent at ₹0. Serverless packaging/static checks cannot validate live connectivity or effective IAM.
5. The Lambda password is resolved from Secrets Manager into the environment at deployment. This avoids source secrets but requires restricted deployment/operator access, secret rotation and a redeploy/refresh process. Avoid logging environment variables.
6. The native S3 notification and async failure destination need a real AWS integration check after approval; failed queue items require deliberate, idempotent redrive. SES acceptance and inbox receipt remain separate facts. Never send to CSV addresses.

Risk acceptance for any future deployment belongs to the project owner. M8 has made no cloud-side security or cost changes.
