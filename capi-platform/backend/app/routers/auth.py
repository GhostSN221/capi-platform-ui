from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models.user import User
from app.schemas.auth import LoginRequest, TokenResponse, UserOut
from app.services.auth import verify_password, create_token, get_current_user, hash_password

router = APIRouter()

@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    res  = await db.execute(select(User).where(User.username == req.username))
    user = res.scalar_one_or_none()
    if not user or not verify_password(req.password, user.hashed_pw):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return TokenResponse(access_token=create_token({"sub": str(user.id), "admin": user.is_admin}))

@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return user

@router.post("/register", response_model=UserOut)
async def register(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    u = User(username=req.username, email=req.username, hashed_pw=hash_password(req.password))
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u
