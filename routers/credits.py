from fastapi import APIRouter, Depends, HTTPException, status

from database import get_conn
from dependencies import get_current_user, require_service
from schemas import CreditAmount, CreditOut

router = APIRouter(prefix="/credits", tags=["credits"])


@router.get("/me", response_model=CreditOut)
def get_credits(user: dict = Depends(get_current_user)):
    return CreditOut(credits=user["credits"])


@router.post("/minus", response_model=CreditOut, dependencies=[Depends(require_service)])
def minus_credits(body: CreditAmount, user: dict = Depends(get_current_user)):
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE users SET credits = credits - ?, updated_at = datetime('now') "
            "WHERE id = ? AND credits >= ?",
            (body.amount, user["id"], body.amount),
        )
        if cur.rowcount == 0:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED, detail="Insufficient credits"
            )
        row = conn.execute("SELECT credits FROM users WHERE id = ?", (user["id"],)).fetchone()
    return CreditOut(credits=row["credits"])


@router.post("/plus", response_model=CreditOut, dependencies=[Depends(require_service)])
def plus_credits(body: CreditAmount, user: dict = Depends(get_current_user)):
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET credits = credits + ?, updated_at = datetime('now') WHERE id = ?",
            (body.amount, user["id"]),
        )
        row = conn.execute("SELECT credits FROM users WHERE id = ?", (user["id"],)).fetchone()
    return CreditOut(credits=row["credits"])
