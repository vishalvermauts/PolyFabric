"""
Backend API and Auth Service for controlled fullstack evaluation fixture.
"""
from typing import Optional, Dict
from pydantic import BaseModel
import jwt
import time

SECRET_KEY = "controlled_evaluation_secret"
ALGORITHM = "HS256"

class LoginRequest(BaseModel):
    username: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = 3600

class UserProfile(BaseModel):
    user_id: str
    role: str
    is_active: bool

def create_access_token(user_id: str, role: str) -> str:
    """Token creation: generates signed JWT for authenticated user."""
    payload = {
        "sub": user_id,
        "role": role,
        "exp": int(time.time()) + 3600
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def verify_token(token: str) -> Optional[UserProfile]:
    """Token validation: extracts payload and enforces expiration."""
    try:
        data = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return UserProfile(user_id=data["sub"], role=data["role"], is_active=True)
    except Exception:
        return None

def login_handler(req: LoginRequest) -> TokenResponse:
    """Login route: validates credentials and returns token."""
    if req.username == "admin" and req.password == "secret123":
        token = create_access_token("admin_01", "administrator")
        return TokenResponse(access_token=token)
    raise ValueError("Invalid username or password")

def protected_resource_handler(auth_header: str) -> Dict[str, str]:
    """Protected API request: checks Bearer authorization and enforces admin permissions."""
    if not auth_header or not auth_header.startswith("Bearer "):
        raise PermissionError("Missing or malformed Authorization header")
    token = auth_header.split(" ")[1]
    profile = verify_token(token)
    if not profile or profile.role != "administrator":
        raise PermissionError("Insufficient permissions: administrator required")
    return {"status": "success", "data": "Protected internal telemetry"}

# Deliberately broken integration (negative test target)
def broken_legacy_auth(token: str):
    """Broken integration: uses wrong signature method and unmounted route."""
    return jwt.decode(token, "wrong_key", algorithms=["none"])

# Negative control: unrelated mathematical utility
def calculate_interest(principal: float, rate: float, time_period: float) -> float:
    """Negative control: financial calculation with no authentication relationship."""
    return principal * (1.0 + rate * time_period)
