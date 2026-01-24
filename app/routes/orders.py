from fastapi import APIRouter, UploadFile, File, Form, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Order
import json, uuid, datetime

router = APIRouter()

@router.post("")
def create_order(
    items: str = Form(...),
    address: str = Form(...),
    proof: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    ref = f"KB-{datetime.datetime.utcnow().year}-{uuid.uuid4().hex[:6].upper()}"
    fname = f"orders/{ref}-{proof.filename}"

    with open(f"uploads/{fname}", "wb") as f:
        f.write(proof.file.read())

    order = Order(
        order_reference=ref,
        items=json.loads(items),
        delivery_address=json.loads(address),
        total_amount=0,
        proof_file_url=f"/uploads/{fname}"
    )
    db.add(order)
    db.commit()
    return {"order_reference": ref}
