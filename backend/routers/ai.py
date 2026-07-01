import os
from fastapi import APIRouter, HTTPException
from google import genai
from pydantic import BaseModel

router = APIRouter()

class AIRequest(BaseModel):
    borrower_data: dict

@router.post("/tips")
def get_ai_tips(req: AIRequest):
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY is not set")

    prompt = f"""
    당신은 은행의 수석 기업신용평가역입니다.
    다음 중소기업의 재무/비재무 데이터를 보고,
    지점장이 이 기업을 어떻게 관리하면 좋을지 3가지 핵심 팁을 짧고 명확하게 제안해주세요.

    [기업 데이터]
    {req.borrower_data}
    """

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
        return {"tips": response.text}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Gemini API 호출 실패: {e}")
