"""Webhook CRUD API endpoints."""

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Webhook, WebhookDelivery
from ..schemas import WebhookCreate, WebhookDeliveryResponse, WebhookResponse, WebhookUpdate
from ..webhook_dispatcher import dispatch_event

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


def _webhook_to_response(wh: Webhook) -> WebhookResponse:
    return WebhookResponse(
        id=wh.id,
        url=wh.url,
        secret="***" if wh.secret else None,
        events=[e.strip() for e in wh.events.split(",") if e.strip()],
        project_id=wh.project_id,
        is_active=bool(wh.is_active),
        created_at=wh.created_at,
    )


@router.get("", response_model=list[WebhookResponse])
def list_webhooks(
    project_id: int | None = Query(None),
    db: Session = Depends(get_db),
):
    query = db.query(Webhook)
    if project_id is not None:
        query = query.filter(Webhook.project_id == project_id)
    return [_webhook_to_response(wh) for wh in query.order_by(Webhook.created_at.desc()).all()]


@router.post("", response_model=WebhookResponse, status_code=201)
def create_webhook(data: WebhookCreate, db: Session = Depends(get_db)):
    wh = Webhook(
        url=data.url,
        secret=data.secret,
        events=",".join(data.events),
        project_id=data.project_id,
        is_active=1,
    )
    db.add(wh)
    db.commit()
    db.refresh(wh)
    return _webhook_to_response(wh)


@router.get("/{webhook_id}", response_model=WebhookResponse)
def get_webhook(webhook_id: int, db: Session = Depends(get_db)):
    wh = db.query(Webhook).filter(Webhook.id == webhook_id).first()
    if not wh:
        raise HTTPException(404, "Webhook not found")
    return _webhook_to_response(wh)


@router.put("/{webhook_id}", response_model=WebhookResponse)
def update_webhook(webhook_id: int, data: WebhookUpdate, db: Session = Depends(get_db)):
    wh = db.query(Webhook).filter(Webhook.id == webhook_id).first()
    if not wh:
        raise HTTPException(404, "Webhook not found")
    if data.url is not None:
        wh.url = data.url
    if data.events is not None:
        wh.events = ",".join(data.events)
    if data.is_active is not None:
        wh.is_active = data.is_active
    if data.secret is not None:
        wh.secret = data.secret
    db.commit()
    db.refresh(wh)
    return _webhook_to_response(wh)


@router.delete("/{webhook_id}", status_code=204)
def delete_webhook(webhook_id: int, db: Session = Depends(get_db)):
    wh = db.query(Webhook).filter(Webhook.id == webhook_id).first()
    if not wh:
        raise HTTPException(404, "Webhook not found")
    db.delete(wh)
    db.commit()


@router.get("/{webhook_id}/deliveries", response_model=list[WebhookDeliveryResponse])
def list_deliveries(
    webhook_id: int,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    wh = db.query(Webhook).filter(Webhook.id == webhook_id).first()
    if not wh:
        raise HTTPException(404, "Webhook not found")
    deliveries = db.query(WebhookDelivery).filter(
        WebhookDelivery.webhook_id == webhook_id
    ).order_by(WebhookDelivery.created_at.desc()).offset(offset).limit(limit).all()
    return [WebhookDeliveryResponse.model_validate(d) for d in deliveries]


@router.post("/{webhook_id}/test")
def test_webhook(webhook_id: int, db: Session = Depends(get_db)):
    wh = db.query(Webhook).filter(Webhook.id == webhook_id).first()
    if not wh:
        raise HTTPException(404, "Webhook not found")
    dispatch_event("webhook.test", {"message": "Test ping from Flintstone"}, db)
    return {"status": "test event dispatched"}
