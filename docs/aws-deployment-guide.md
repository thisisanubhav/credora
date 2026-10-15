# AWS deployment guide — preparation only

**Stop: the authorized budget is ₹0. Do not run `serverless deploy`, create prerequisites, enable SES, or use real AWS credentials for M8.** This guide is a conditional runbook for a separately approved future deployment, not permission to execute it. The working demonstration is local (`make up`, `make s3-init`, `make api`, `make local-worker`, n8n and dispatcher).

## Offline commands now

From the repository root, install locked Python dependencies with `uv sync --frozen`. Run `make aws-config-offline aws-test` to parse and inspect the template without variable resolution or AWS calls. `make aws-package-local` builds `.build/m8/lambda.zip` with Linux x86_64 wheels and checks its handlers and size; it uses package-index downloads but no AWS. `make aws-preflight-offline` validates deployment environment *shapes* when a future operator has filled `infrastructure/aws.env.example` in an ignored private file. It does not test resource existence. No Makefile target deploys anything.

The checked-in `infrastructure/aws.env.example` deliberately contains placeholders; passing it to preflight must fail. Even a syntactically valid private preflight is **not** evidence that an AWS resource exists or that deployment is permitted.

The Serverless v4 CLI is pinned by `infrastructure/package-lock.json`. Do **not** treat `serverless package` as an offline check: [Serverless documents](https://www.serverless.com/framework/docs/providers/aws/guide/packaging) that packaging may need AWS credentials to resolve account/SSM/S3 state, and [v4 requires authentication](https://www.serverless.com/framework/docs/guides/upgrading-v4). Actual CLI packaging and CloudFormation validation remain blocked by the zero budget; local zip and static YAML checks are explicitly narrower.

## Conditional prerequisites (not performed)

1. Obtain spending approval, a budget/alarm, an AWS account and stage-specific least-privilege deploy identity. Confirm current regional pricing before any command.
2. Provision a private VPC with two Lambda subnets, a gateway S3 endpoint, restricted SGs, and PostgreSQL 16 RDS with encryption, backups, deletion protection and a separate n8n database. No NAT gateway is planned. RDS and Secrets Manager cost money even when no upload occurs.
3. Create a least-privilege runtime DB role and a distinct migration role. From a private-network operator host, apply `alembic -c database/alembic.ini upgrade head` with the migration role; grant the runtime role only required DML and sequence permissions. Never point destructive migration tests at RDS.
4. Configure a verified OIDC issuer/audience. The current M7 browser has no OIDC client and cannot yet call the protected AWS routes. Implement and review that integration before public deployment; do not remove JWT authorization. Set exact `FRONTEND_ORIGIN`, unique `UPLOAD_BUCKET_NAME`, private `DB_HOST`, VPC IDs, runtime username and password-secret ARN. Store values privately using the keys in `infrastructure/aws.env.example`; never commit them.
5. Put n8n, its helper and the outbox dispatcher on an operator-controlled VM in the VPC, using Docker Compose and private networking. Do not publish n8n editor/webhooks. Provide only allowlisted outbound access, encrypted n8n credentials, HMAC secret and the existing test-recipient enforcement. A cloud-specific Compose topology is still required and is a deployment blocker; local Compose must not be reused unchanged.
6. Verify a sender and controlled test recipient with SES, account for sandbox rules, then separately authorize any actual send. The current n8n workflow keeps mock mode by default. No sample-CSV recipient may receive mail.

After separate authorization, a deployment operator would build the zip, run authenticated Serverless packaging/deploy, inspect the generated CloudFormation change set and IAM policy, migrate with the separate role, and perform stage-specific smoke checks (JWT deny/allow, presign, S3 ObjectCreated→Lambda, RDS persistence, outbox→private n8n, mock notification first). Keep the SQS failed-invocation queue monitored and redrive only after investigating failures. Never equate a successful package or local mock with live AWS evidence.

## Rollback and recovery

Disable ingress or JWT audience for a faulty release before restoring a prior immutable Lambda artifact/configuration. Preserve the upload bucket, RDS snapshots, outbox and failed-event queue during rollback. Do not downgrade production data blindly: review each Alembic revision and take a backup first. Removing the stack while the bucket contains objects can fail or destroy evidence; use an approved retention/export procedure. Duplicate S3 events and webhook deliveries are expected and are fenced by batch/event identity. See [deployment design](aws-deployment-design.md) and [security review](security-review.md).
