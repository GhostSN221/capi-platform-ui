from fastapi import APIRouter, Depends, HTTPException
from app.models.user import User
from app.services.auth import get_current_user
from app.services import network

router = APIRouter()


@router.get("/suggest-cidr")
async def suggest_cidr(user: User = Depends(get_current_user)):
    try:
        return {"cidr": network.suggest_cidr()}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/check-cidr")
async def check_cidr(cidr: str, user: User = Depends(get_current_user)):
    try:
        return network.check_cidr(cidr)
    except Exception as e:
        raise HTTPException(500, str(e))
