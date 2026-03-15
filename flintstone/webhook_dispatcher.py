"""Webhook event dispatcher with background delivery and retry."""

import hashlib
import hmac
import json
import threading
import time

from sqlalchemy.orm import Session

from .models import Webhook, WebhookDelivery


def dispatch_event(event: str, payload: dict, db: Session):
    """Find matching webhooks and deliver payloads in a background thread."""
    webhooks = db.query(Webhook).filter(
        Webhook.is_active == 1,
    ).all()

    matching = []
    for wh in webhooks:
        events = [e.strip() for e in wh.events.split(",") if e.strip()]
        if event in events or "*" in events:
            matching.append({
                "id": wh.id,
                "url": wh.url,
                "secret": wh.secret,
            })

    if not matching:
        return

    payload_json = json.dumps(payload, default=str)

    # Record deliveries
    deliveries = []
    for wh in matching:
        delivery = WebhookDelivery(
            webhook_id=wh["id"],
            event=event,
            payload=payload_json,
        )
        db.add(delivery)
        deliveries.append({"delivery": delivery, "webhook": wh})

    db.flush()

    # Capture delivery IDs before background thread
    delivery_info = []
    for d in deliveries:
        delivery_info.append({
            "delivery_id": d["delivery"].id,
            "url": d["webhook"]["url"],
            "secret": d["webhook"]["secret"],
        })

    db.commit()

    # Deliver in background thread
    from .database import SessionLocal

    for info in delivery_info:
        thread = threading.Thread(
            target=_deliver,
            args=(info["delivery_id"], info["url"], info["secret"], event, payload_json),
            daemon=True,
        )
        thread.start()


def _deliver(delivery_id: int, url: str, secret: str | None, event: str, payload: str):
    """Deliver a webhook with retry (3 attempts, exponential backoff)."""
    from .database import SessionLocal

    try:
        import httpx
    except ImportError:
        return

    headers = {
        "Content-Type": "application/json",
        "X-Flintstone-Event": event,
    }
    if secret:
        signature = hmac.new(
            secret.encode(), payload.encode(), hashlib.sha256
        ).hexdigest()
        headers["X-Flintstone-Signature"] = signature

    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            with httpx.Client(timeout=10) as client:
                response = client.post(url, content=payload, headers=headers)
            status_code = response.status_code
            success = 200 <= status_code < 300
        except Exception:
            status_code = 0
            success = False

        # Update delivery record
        try:
            session = SessionLocal()
            delivery = session.query(WebhookDelivery).filter(
                WebhookDelivery.id == delivery_id
            ).first()
            if delivery:
                delivery.attempts = attempt
                delivery.status_code = status_code
                delivery.success = success
                from datetime import datetime, timezone
                delivery.last_attempt_at = datetime.now(timezone.utc)
                session.commit()
            session.close()
        except Exception:
            pass

        if success:
            return

        if attempt < max_attempts:
            time.sleep(2 ** attempt)
