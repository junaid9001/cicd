import hashlib
import hmac
import json
import os
from typing import Any, Dict, Tuple


def verify_stripe_signature(payload: bytes, signature_header: str, secret: str) -> bool:
    if not signature_header or not secret:
        return False

    parts = {}
    for part in signature_header.split(","):
        if "=" in part:
            key, value = part.split("=", 1)
            parts[key.strip()] = value.strip()
    timestamp = parts.get("t")
    signature = parts.get("v1")
    if not timestamp or not signature:
        return False

    signed_payload = f"{timestamp}.{payload.decode('utf-8')}"
    digest = hmac.new(secret.encode("utf-8"), signed_payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, signature)


def parse_subscription_event(body: bytes) -> Tuple[str, Dict[str, Any]]:
    data = json.loads(body.decode("utf-8"))
    event_type = str(data.get("type", "unknown"))
    obj = data.get("data", {}).get("object", {})
    if not isinstance(obj, dict):
        obj = {}
    return event_type, obj


def stripe_secret() -> str:
    return os.getenv("STRIPE_WEBHOOK_SECRET", "")
