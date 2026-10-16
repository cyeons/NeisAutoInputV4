from __future__ import annotations

from abc import ABC, abstractmethod

from neis_v4.models import GenerationRequest, GenerationResult


class AIProviderError(RuntimeError):
    pass


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
        previous = "\n# 이미 생성된 문장\n" + "\n".join(request.previous_outputs[-20:])

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

# 문장별 성취기준 배분 규칙
1. 한 학생의 한 문장은 하나의 주요 성취기준을 중심으로 작성하십시오.
2. 선택한 성취기준 수가 학생 1인당 문장 수보다 많으면, 학생별로 성취기준을 무작위로 골라 문장 수만큼만 반영하십시오.
3. 선택한 성취기준 수와 학생 1인당 문장 수가 같으면, 각 문장에 서로 다른 성취기준을 하나씩 반영하십시오.
4. 학생 1인당 문장 수가 선택한 성취기준 수보다 많으면, 한 성취기준을 여러 문장에 사용할 수 있으나 가능한 한 고르게 순환 배분하십시오.
5. 학생 1인당 문장 수가 1개이면 각 줄은 정확히 1개 문장만 작성하고, 선택한 성취기준 중 하나만 중심으로 삼으십시오.
""".strip()
    return append_custom_prompt(prompt, request.custom_prompt)


def parse_comments(text: str) -> list[str]:
    return [line.strip(" -\t") for line in text.splitlines() if line.strip()]
