import json
import os
from functools import lru_cache
from typing import Optional

from fastapi import APIRouter, HTTPException
from google import genai
from google.genai import types
from pydantic import BaseModel

router = APIRouter()

# 안정적인 정식(GA) 버전 + 무료 티어 한도가 더 넉넉한 모델을 사용한다.
# gemini-2.5-flash는 하루 20회 한도에 이 세션에서만 이미 도달했었다.
# gemini-1.5-flash/-8b는 API에서 완전히 제거되어(404) 사용 불가.
# gemini-2.0-flash-lite는 이 API 키에 한해 무료 할당량이 0으로 설정되어 있어
# 실제로는 항상 실패함 (client.models.list()에는 나오지만 quota 미부여 상태).
# 실제 호출 테스트로 확인한, 지금 이 키에서 살아있는 모델로 사용한다.
MODEL_NAME = "gemini-2.5-flash-lite"

class AIRequest(BaseModel):
    bzno: Optional[str] = None
    base_ym: Optional[str] = None
    borrower_data: dict

class AITip(BaseModel):
    title: str
    reason: str

class AITipsResponse(BaseModel):
    summary: str
    tips: list[AITip]

@lru_cache(maxsize=1000)
def _cached_tips_json(bzno: str, base_ym: str, prompt: str) -> str:
    """캐시 키는 (bzno, base_ym, prompt) — 동일 차주를 같은 기준월로 다시 조회할
    때는 API 재호출 없이 캐시를 쓰지만, 기준월이 바뀌면(재무/부도확률이 달라지므로)
    새로 생성한다. 실패 시 예외는 캐시되지 않으므로 다음 요청에서 재시도된다."""
    api_key = os.getenv("GEMINI_API_KEY")
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=AITipsResponse,
        ),
    )
    return response.text

@router.post("/tips")
def get_ai_tips(req: AIRequest):
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY is not set")

    prompt = f"""
    당신은 은행의 수석 기업신용평가역입니다.
    다음 중소기업의 재무/비재무 데이터를 보고,
    지점장이 이 기업을 어떻게 관리하면 좋을지 3가지 핵심 팁을 제안해주세요.
    각 팁은 한 줄로 요약되는 제목(title)과, 왜 그 조치가 필요한지 설명하는
    이유(reason)로 나누어 작성하세요. summary는 전체 상황에 대한 1~2문장 총평입니다.

    [기업 데이터]
    {req.borrower_data}
    """

    try:
        cache_key = req.bzno or json.dumps(req.borrower_data, sort_keys=True)
        text = _cached_tips_json(cache_key, req.base_ym or "", prompt)
        return json.loads(text)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Gemini API 호출 실패: {e}")
