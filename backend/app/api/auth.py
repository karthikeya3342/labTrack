from fastapi import APIRouter, HTTPException, status, Depends
from backend.app.models.schemas import LoginRequest, TokenResponse
from backend.app.core.security import verify_password, create_access_token, get_current_user_token_payload
from backend.app.core.database import fetch_one

router = APIRouter(prefix="/auth", tags=["Authentication"])

@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest):
    user = await fetch_one(
        "SELECT id, roll_no, name, email, password_hash, role, is_active FROM users WHERE roll_no = $1",
        req.roll_no
    )
    if not user or not user["is_active"]:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid roll number or inactive account"
        )

    if not verify_password(req.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect password"
        )

    token = create_access_token({
        "sub": str(user["id"]),
        "roll_no": user["roll_no"],
        "name": user["name"],
        "role": user["role"]
    })

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user={
            "id": user["id"],
            "roll_no": user["roll_no"],
            "name": user["name"],
            "email": user["email"],
            "role": user["role"]
        }
    )

@router.get("/me")
async def get_current_user_profile(payload: dict = Depends(get_current_user_token_payload)):
    user_id = int(payload["sub"])
    user = await fetch_one(
        """SELECT u.id, u.roll_no, u.name, u.email, u.role,
                  sp.batch_year, sp.cgpa, sp.quota_hours_remaining,
                  fp.designation
           FROM users u
           LEFT JOIN student_profiles sp ON sp.user_id = u.id
           LEFT JOIN faculty_profiles fp ON fp.user_id = u.id
           WHERE u.id = $1""",
        user_id
    )
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user
