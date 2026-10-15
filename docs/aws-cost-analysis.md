# AWS cost analysis — ₹0 authorization

The current authorized ceiling is **₹0**, so all cloud provisioning and live SES delivery are blocked. This is a cost inventory, not a spending recommendation or a quote. Prices and free-tier eligibility vary by region/account/date/usage. The [AWS Pricing Calculator](https://calculator.aws/) and the linked official service pages must be consulted immediately before any separately approved deployment. Free-tier availability does **not** guarantee a zero bill.

| Component | Cost driver | Idle cost / implication |
|---|---|---|
| S3 upload bucket | Stored GB-month, PUT/GET requests, transfer ([pricing](https://aws.amazon.com/s3/pricing/)) | Stored objects cost money; 7-day source expiry limits retention, not all charges |
| Lambda API + ingestion | Invocations, duration/GB-seconds, optional provisioned concurrency ([pricing](https://aws.amazon.com/lambda/pricing/)) | No provisioned concurrency; use is metered; CloudWatch still retains logs |
| API Gateway HTTP API | Requests and transfer ([pricing](https://aws.amazon.com/api-gateway/pricing/)) | No assumed zero-cost entitlement |
| RDS PostgreSQL | Instance hours, storage, backups beyond allowance, I/O/transfer depending configuration ([pricing](https://aws.amazon.com/rds/pricing/)) | **Fixed recurring instance/storage cost even at zero uploads** |
| VPC networking | S3 gateway endpoint has [no extra endpoint charge](https://docs.aws.amazon.com/vpc/latest/privatelink/gateway-endpoints.html); NAT gateway and public IPv4 have hourly/transfer charges ([pricing](https://aws.amazon.com/vpc/pricing/)) | No NAT in design; a future n8n VM's public IPv4 and EBS may still cost while idle |
| n8n VM | Compute instance-hours, EBS, IPv4, egress | Fixed recurring cost; local Docker is the ₹0 choice |
| Secrets Manager | Per-secret/month and API calls ([pricing](https://aws.amazon.com/secrets-manager/pricing/)) | Fixed recurring secret charge |
| CloudWatch | Ingested/stored log GB, metrics/alarms ([pricing](https://aws.amazon.com/cloudwatch/pricing/)) | 14-day retention bounds logs, not absolute spend |
| SQS failure queue | API requests/storage ([pricing](https://aws.amazon.com/sqs/pricing/)) | Usage based; monitor redrive |
| SES | Email and data/attachments; sandbox and identity constraints ([pricing](https://aws.amazon.com/ses/pricing/)) | Live mail is prohibited here, irrespective of any allowance |

For a future estimate, choose region, RDS class/storage/backup retention, VM class/EBS/IPv4, expected CSV bytes and request rates, Lambda duration/memory, log volume, and SES count. Compute a monthly minimum from **RDS + n8n host/storage/IP + secrets**, then add metered components. A 730-hour month is a useful explicit assumption for hourly resources, not a benchmark or quote. The local Compose/LocalStack pipeline remains the only approved zero-cloud-spend demonstration.

As a concrete avoided-cost illustration—not a project total—one NAT gateway at AWS's [US East (Ohio) example rate](https://aws.amazon.com/vpc/pricing/) of $0.045/hour would be **$32.85 for 730 hours**, before traffic. The proposed design provisions none. One public IPv4 at the [published $0.005/hour rate](https://aws.amazon.com/vpc/pricing/) would add **$3.65 for 730 hours** if a future VM used it. The larger RDS/VM baseline cannot be responsibly stated as one number without an approved region, class, storage and topology; the required cost estimate is therefore a priced-component model with those parameters explicit, not a fabricated ₹0 bill.
