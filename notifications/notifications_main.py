from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session
from common.db import get_db
from notifications.notifications_models import Notification
from common.security import get_current_user
from datetime import datetime, timezone

app = FastAPI()

@app.get("/")
async def get_notifications(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    notifs = db.query(Notification).filter(
        Notification.user_id == current_user["user_id"]
    ).order_by(Notification.created_at.desc()).limit(20).all()

    unread_count = db.query(Notification).filter(
        Notification.user_id == current_user["user_id"],
        Notification.is_read == False
    ).count()

    return {
        "unread_count": unread_count,
        "notifications": [
            {
                "id": str(n.id),
                "type": n.type,
                "title": n.title,
                "message": n.message,
                "is_read": n.is_read,
                "pa_request_id": str(n.pa_request_id) if n.pa_request_id else None,
                "created_at": n.created_at.isoformat() if n.created_at else None,
            }
            for n in notifs
        ]
    }

@app.post("/{notification_id}/read")
async def mark_read(notification_id: str, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    notif = db.query(Notification).filter(
        Notification.id == notification_id,
        Notification.user_id == current_user["user_id"]
    ).first()
    if notif:
        notif.is_read = True
        notif.read_at = datetime.now(timezone.utc)
        db.commit()
    return {"success": True}

@app.post("/mark-all-read")
async def mark_all_read(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    db.query(Notification).filter(
        Notification.user_id == current_user["user_id"],
        Notification.is_read == False
    ).update({"is_read": True, "read_at": datetime.now(timezone.utc)})
    db.commit()
    return {"success": True}
