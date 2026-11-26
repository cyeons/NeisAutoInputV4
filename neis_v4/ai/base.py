from __future__ import annotations

import re
import time
from abc import ABC, abstractmethod

from neis_v4.models import GenerationRequest, GenerationResult


# 응답이 없을 때 무한정 기다리지 않도록 요청 1회당 최대 대기 시간(초)을 둡니다.
# AI 평어는 학생 전체를 한 번에 받으므로 학생 수가 많아도 넉넉하게 둡니다.
REQUEST_TIMEOUT_SECONDS = 300


class AIProviderError(RuntimeError):
    pass


# 다시 시도는 이 프로그램이 한 곳(call_with_retry)에서만 합니다. AI 회사 라이브러리의 자동 재시도는 끕니다.
# 둘 다 켜 두면 재시도가 곱으로 늘어(최대 9번) 응답이 없을 때 15분 넘게 기다릴 수 있었습니다.
SDK_MAX_RETRIES = 0
_TRANSIENT_STATUS = {429, 500, 502, 503, 504, 529}
_TRANSIENT_TEXT = re.compile(
    r"\b(?:429|50[0234]|529)\b|unavailable|high demand|rate limit|temporarily|overloaded"
)


def is_transient_error(exc: Exception) -> bool:
    """잠깐 기다리면 풀리는 오류(서버 혼잡·요청 한도)인지 봅니다.

    시간 초과는 다시 시도하지 않습니다. 이미 5분을 기다렸으므로 또 기다리게 하지 않고 바로 알립니다.
    """
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if isinstance(status, int):
        return status in _TRANSIENT_STATUS
    return bool(_TRANSIENT_TEXT.search(str(exc).lower()))


def call_with_retry(call, on_retry=None, sleep=time.sleep, attempts: int = 3):
    """서버 혼잡이면 1.2초, 2.4초 쉬었다가 최대 3번까지 시도합니다."""
    for attempt in range(attempts):
        try:
            return call()
        except Exception as exc:
            if attempt >= attempts - 1 or not is_transient_error(exc):
                raise
            if on_retry:
                on_retry(attempt + 1, attempts - 1)
            sleep(1.2 * (2**attempt))


def describe_error(exc: Exception) -> str:
    """자주 나는 AI 오류를 쉬운 한국어로 안내합니다.

    원문을 뒤에 붙여 두어야 행동발달 탭의 자동 재시도(429·503·timeout 등 글자 검사)가 계속 동작합니다.
    """
    original = str(exc).strip() or type(exc).__name__
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    lower = original.lower()
    kind = type(exc).__name__.lower()
    if status in (401, 403) or "api key" in lower and any(
        word in lower for word in ("invalid", "incorrect", "not valid", "expired")
    ):
        hint = "API 키가 거절되었습니다. 환경 설정 > API 키 관리에서 키가 맞는지, 사용 기간이 끝나지 않았는지 확인하세요."
    elif status == 429 or any(word in lower for word in ("rate limit", "quota", "resource_exhausted")):
        hint = "요청이 많거나 사용 한도를 넘었습니다. 1분쯤 뒤에 다시 시도하세요."
    elif "timeout" in kind or "timed out" in lower:
        hint = "응답이 너무 오래 걸려 멈췄습니다. 학생 수를 줄이거나 잠시 뒤에 다시 시도하세요."
    elif "connect" in kind or "certificate" in lower or "ssl" in lower:
        hint = (
            "AI 서버에 연결하지 못했습니다. 인터넷 연결을 확인하고, 학교망이라면 "
            "환경 설정의 'Windows 인증서 저장소 사용'을 켠 뒤 다시 실행해 보세요."
        )
    elif status in (500, 502, 503, 504, 529) or any(
        word in lower for word in ("overloaded", "unavailable", "high demand")
    ):
        hint = "AI 서버가 잠시 바쁩니다. 잠시 뒤에 다시 시도하세요."
    else:
        return original
    if len(original) > 300:
        original = original[:300] + "…"
    return f"{hint}\n(원문: {original})"


class AIProvider(ABC):
    name: str

    @abstractmethod
    def generate_comments(self, request: GenerationRequest) -> GenerationResult:
        raise NotImplementedError


def append_custom_prompt(prompt: str, custom_prompt: str) -> str:
    custom = custom_prompt.strip()
    if not custom:
        return prompt
    return (
        f"{prompt}\n\n"
        "# 사용자 추가 지시\n"
        "아래 지시는 기존 작성 규칙, 출력 형식, 안전 규칙과 충돌하지 않는 범위에서만 반영하십시오.\n"
        f"{custom}"
    )


def build_prompt(request: GenerationRequest, repair_text: str = "") -> str:
    standards = []
    for standard in request.standards:
        domain = f"[{standard.domain}] " if standard.domain else ""
        line = f"- {domain}{standard.code} {standard.description}"
        if standard.explanation and "해설 없음" not in standard.explanation:
            line += f"\n  해설: {standard.explanation}"
        standards.append(line)

    previous = ""
    if request.previous_outputs:
        previous = (
            "\n# 이미 생성된 문장\n"
            + "\n".join(request.previous_outputs[-20:])
            + "\n위 문장과 표현·구조가 겹치지 않게 작성하십시오."
        )

    repair = ""
    if repair_text:
        repair = f"""
# 보정 지시
아래 이전 출력은 줄 수가 맞지 않았습니다. 반드시 {request.student_count}줄만 다시 작성하십시오.
이전 출력:
{repair_text}
"""

    prompt = f"""
# 역할
당신은 초등학교 생활기록부 교과 학습 발달 상황을 작성하는 교사 보조 전문가입니다.

# 입력
- 학생 수: {request.student_count}명
- 학생 1인당 문장 수: {request.sentence_count}개
- 성취기준:
{chr(10).join(standards)}
{previous}
{repair}

# 작성 규칙
1. 각 학생은 한 줄로만 출력하십시오.
2. 전체 출력은 정확히 {request.student_count}줄이어야 합니다.
3. 각 줄은 {request.sentence_count}개의 문장을 자연스럽게 이어 쓴 한 문단이어야 합니다.
4. 종결 어미는 반드시 '~함', '~음', '~임', '~보임', '~갖춤' 등 명사형으로 끝내십시오.
5. 부정적 표현보다 성장 가능성, 태도, 성취를 중심으로 작성하십시오.
6. 학생별 표현, 문장 구조, 서술어가 반복되지 않도록 다양하게 작성하십시오.
7. 번호, 불릿, 마크다운, 학생 라벨, 빈 줄을 출력하지 마십시오.
8. 모든 문장은 마침표(.)로 끝내십시오. 문장과 문장을 쉼표(,)로 이어 붙이지 말고 마침표로 나누십시오.
9. 성취기준과 관련된 학습 활동에서 드러난 구체적인 모습과 그 의미를 함께 담아 쓰십시오.

# 문장별 성취기준 배분 규칙
1. 한 학생의 한 문장은 하나의 주요 성취기준을 중심으로 작성하십시오.
2. 선택한 성취기준 수가 학생 1인당 문장 수보다 많으면, 학생별로 성취기준을 무작위로 골라 문장 수만큼만 반영하십시오.
3. 선택한 성취기준 수와 학생 1인당 문장 수가 같으면, 각 문장에 서로 다른 성취기준을 하나씩 반영하십시오.
4. 학생 1인당 문장 수가 선택한 성취기준 수보다 많으면, 한 성취기준을 여러 문장에 사용할 수 있으나 가능한 한 고르게 순환 배분하십시오.
5. 학생 1인당 문장 수가 1개이면 각 줄은 정확히 1개 문장만 작성하고, 선택한 성취기준 중 하나만 중심으로 삼으십시오.
""".strip()
    return append_custom_prompt(prompt, request.custom_prompt)


_LIST_MARKER = re.compile(r"^\s*(?:[-*•]|\d+[.)](?!\d))\s*")


def parse_comments(text: str) -> list[str]:
    """Split AI output into one comment per line, dropping '-', '1.', '2)' markers."""
    comments = (_LIST_MARKER.sub("", line).strip() for line in text.splitlines())
    return [comment for comment in comments if comment]
