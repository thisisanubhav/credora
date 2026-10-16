"""Release one held notification event for future targeted dispatch; never send."""

from __future__ import annotations

import argparse
import getpass
import os
import uuid

from services.common.db import make_engine
from services.notifications.recovery import release_recovery
from scripts.prepare_notification_recovery import n8n_read_engine


def main() -> None:
    parser = argparse.ArgumentParser(description="Release one held event for targeted dispatch; no send")
    parser.add_argument("--release", action="store_true", required=True)
    parser.add_argument("--event-id", type=uuid.UUID, required=True)
    parser.add_argument("--batch-id", type=uuid.UUID, required=True)
    parser.add_argument("--audit-id", type=uuid.UUID, required=True)
    args = parser.parse_args()
    key = os.environ.get("NOTIFICATION_RECOVERY_IDEMPOTENCY_KEY", "")
    if len(key) != 64:
        raise SystemExit("Recovery notification key is not configured")
    token = getpass.getpass("Recovery release authorization token: ")
    app_engine = make_engine()
    evidence_engine = n8n_read_engine()
    try:
        audit_id = release_recovery(
            app_engine, evidence_engine, event_id=args.event_id, batch_id=args.batch_id,
            notification_key=key, recovery_audit_id=args.audit_id, authorization=token,
        )
        print(f"Recovery released for targeted dispatch only; release audit ID: {audit_id}. No event dispatched.")
    finally:
        evidence_engine.dispose()
        app_engine.dispose()


if __name__ == "__main__":
    main()
