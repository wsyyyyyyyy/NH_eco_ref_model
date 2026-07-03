import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


class LoginRequest(BaseModel):
    emp_id: str
    password: str


@router.post("/login")
def login(req: LoginRequest):
    # 간단한 고정 계정 검증. 운영 전환 시 실제 사용자 디렉터리/SSO 연동으로 교체 필요.
    valid_id = os.getenv("PORTAL_EMP_ID", "admin")
    valid_password = os.getenv("PORTAL_PASSWORD", "admin1234")
    if req.emp_id != valid_id or req.password != valid_password:
        raise HTTPException(status_code=401, detail="사번 또는 비밀번호가 올바르지 않습니다.")
    return {"success": True}
