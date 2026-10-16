from __future__ import annotations

import json

from neis_v4.ai.base import append_custom_prompt
from neis_v4.models import BehaviorGenerationRequest


BEHAVIOR_RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "student_id": {"type": "string"},
                    "comment": {"type": "string"},
                    "used_trait_ids": {"type": "array", "items": {"type": "string"}},
                    "omitted_trait_ids": {"type": "array", "items": {"type": "string"}},
                    "character_count": {"type": "integer"},
                    "utf8_byte_count": {"type": "integer"},
                    "sentence_count": {"type": "integer"},
                },
                "required": [
                    "student_id",
                    "comment",
                    "used_trait_ids",
                    "omitted_trait_ids",
                    "character_count",
                    "utf8_byte_count",
                    "sentence_count",
                ],
            },
        }
    },
    "required": ["results"],
}


SYSTEM_PROMPT = """
당신은 초등학교 담임교사이자 학교생활기록부 작성 전문가입니다.
입력된 학생의 특성 키워드를 종합하여 행동특성 및 종합의견 문단을 작성합니다.

[절대 원칙]
1. 학생 이름은 제공되지 않으며 주어 없이 교사의 객관적인 현재 관찰 기록처럼 작성합니다.
2. 모든 문장은 현재형 명사형 종결인 ~함, ~임, ~보임, ~드러남, ~갖춤, ~나타냄, ~실천함, ~있음, ~기대됨 등으로 끝냅니다.
3. ~했음, ~보였음, ~있었음, ~되었음 등 과거형을 절대 사용하지 않습니다.
4. comment는 공백 포함 250자 이상 280자 이하이며 학생별로 요청된 1~8문장으로 정확히 작성합니다.
5. comment 전체는 줄바꿈 없는 하나의 문단이어야 합니다.
6. 쉼표 기호 , 또는 ，를 절대 사용하지 않습니다. 절은 연결어미로 자연스럽게 이어 씁니다.
7. 번호, 소제목, 따옴표, 괄호, 불릿, 설명, 안내문을 comment에 넣지 않습니다.
8. 과장, 미사여구, 교사의 감상, 학생 간 비교, 낙인, 단정적인 평가를 쓰지 않습니다.
9. 질병, 장애, 심리 진단, 가정환경, 경제상황, 종교, 인종, 외모, 성별을 추측하거나 언급하지 않습니다.
10. 입력에 없는 구체적인 사건, 직책, 날짜, 빈도, 장소, 성적, 친구 관계, 원인, 감정, 수상 내용을 만들지 않습니다.

[키워드 확장]
1. 키워드는 교사가 확인한 일반적인 행동 특성으로 간주하고 관찰 가능한 일반 행동 경향과 교육적 의미로 자연스럽게 확장합니다.
2. 입력 특성이 많으면 모두 나열하지 않고 강점과 성장 필요 특성을 우선하여 핵심만 선별합니다.
3. strength는 뚜렷하게 관찰되는 강점으로 표현합니다.
4. standard는 과장 없이 관찰되는 특성으로 표현합니다.
5. growth는 학생 전체의 결함으로 규정하지 않고 연습과 성장 가능성이 드러나게 표현합니다.
6. 말수가 적음은 신중하고 차분한 태도로 표현하고 자기주장이 강함은 자신의 기준을 바탕으로 노력하는 특성으로 표현합니다.
7. 관계의 폭이 좁음은 소수와 안정적인 관계를 형성하는 경향으로 표현하고 발표 참여가 어려움은 충분히 생각한 뒤 표현하는 경향으로 작성합니다.
8. 집중 유지가 필요한 특성은 다양한 분야에 관심을 보이며 상황에 맞는 집중 조절이 필요한 방향으로 작성합니다.
9. trait의 generation_role이 required이면 반드시 반영하고 omit이면 문단에 반영하지 않은 뒤 omitted_trait_ids에 넣습니다.

[문단 흐름]
입력에서 확인할 수 있는 범위 안에서 기본 성향, 학교생활 태도, 교우관계와 공동체성, 주요 강점, 성장 가능성의 흐름으로 작성합니다. 입력에 근거가 없는 영역은 만들지 않습니다.

[구조화 출력]
JSON 스키마에 맞는 객체만 반환합니다. comment에는 완성 문단만 넣습니다.
used_trait_ids에는 실제 문단에 반영한 특성 ID를 넣고 omitted_trait_ids에는 분량상 제외한 특성 ID를 넣습니다.
두 목록은 중복되지 않아야 하며 합치면 입력된 모든 특성 ID와 같아야 합니다.
""".strip()


def build_behavior_prompt(request: BehaviorGenerationRequest) -> str:
    students = [
        {
            "student_id": student.student_id,
            "sentence_count": student.sentence_count,
            "traits": student.traits,
        }
        for student in request.students
    ]
    previous = request.previous_outputs[-20:]
    prompt = (
        "# 작업\n"
        "아래 익명 학생별 특성을 바탕으로 행동특성 및 종합의견을 작성하십시오.\n"
        "학생별 sentence_count를 1~8 범위에서 정확히 지키고 각 comment를 250~280자로 작성하십시오.\n"
        "generation_role이 지정된 특성은 required/omit 지시를 반드시 따르십시오.\n\n"
        f"# 학생별 입력\n{json.dumps(students, ensure_ascii=False, indent=2)}\n\n"
        f"# 최근 생성 결과 중복 방지 참고\n{json.dumps(previous, ensure_ascii=False, indent=2)}"
    )
    return append_custom_prompt(prompt, request.custom_prompt)
