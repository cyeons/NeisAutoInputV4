# AGENTS.md

AI 코딩 도구(Claude Code, Codex, Cursor 등)를 위한 프로젝트 안내입니다. 사용자는 대부분 코딩 경험이 적은 초등 교사입니다. 설명은 쉬운 한국어로 하고, 전문 용어는 처음 나올 때 풀어서 설명하세요.

## 프로젝트

- NEIS(교육행정정보시스템) 생활기록부 입력을 돕는 Windows 데스크톱 앱입니다. Python 3.10+와 PySide6를 씁니다.
- 핵심 동작: 표의 각 행 내용을 클립보드에 복사 → `Ctrl+V` → `Tab` N회 (`neis_v4/automation/runner.py`).
- AI(Gemini/OpenAI)로 교과 평어·행동발달 초안을 생성합니다 (`neis_v4/ai/`).
- 파일별 역할은 README.md의 "무엇을 어디서 고치나요?"와 "프로젝트 구조"를 보세요.

## 명령

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt   # 의존성 설치
.\.venv\Scripts\python.exe main.py                              # 실행
.\.venv\Scripts\python.exe -m unittest discover -s tests -v     # 테스트
.\.venv\Scripts\python.exe -m PyInstaller NeisAutoInputV4.spec  # exe 빌드 → dist\
```

코드를 고친 뒤에는 반드시 테스트를 실행하고 결과를 사용자에게 알려 주세요.

## 반드시 지킬 규칙

- **학생 개인정보 보호**: `data.csv`, `student.csv`, `hb_work.json`, `hb_custom_traits.json`, `config.json`은 실제 학생 정보가 들어가는 파일입니다. 읽거나 출력하거나 커밋하지 말고, `.gitignore`에서 빼지 마세요. 테스트와 예시에는 "학생 1" 같은 가짜 데이터만 쓰세요.
- **API 키**: 코드·파일에 API 키를 적지 마세요. 키는 `neis_v4/secrets.py`가 keyring(Windows 자격 증명 관리자)에 저장합니다.
- **행동발달 AI 요청에는 학생 이름을 넣지 마세요.** 학생은 `student_id`(UUID)로만 구분합니다.
- 입력 동작(`runner.py`, `neis_tab.py`)을 바꿀 때는 빈 행 처리, `Esc` 중지, 긴급 중지(`pyautogui.FAILSAFE`)가 그대로 동작해야 합니다. 이 부분은 자동 테스트로 확인되지 않으니, 메모장 등에서 직접 시험해 보라고 사용자에게 안내하세요.
- 기본 설정값은 `neis_v4/models.py`의 `AppSettings`와 `neis_v4/storage.py`의 `load_settings` 두 곳에 있습니다. 바꿀 때는 둘 다 고치세요.
- 새 리소스 파일을 추가하면 `NeisAutoInputV4.spec`의 `datas`에도 추가해야 exe에 포함됩니다.

## 코드 스타일

- 기존 코드의 구조와 이름 짓는 방식을 따르세요. 화면 문구는 한국어로 씁니다.
- 요청받지 않은 리팩터링이나 새 라이브러리 추가는 하지 마세요. 꼭 필요하면 `requirements.txt`에 추가하고 이유를 설명하세요.
