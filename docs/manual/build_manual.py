from __future__ import annotations

import html
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "report.md"
OUTPUT = ROOT / "docs" / "manual" / "manual.html"

SCREEN_BY_SLIDE = {
    1: "01-data-ready.png",
    2: "01-data-ready.png",
    4: "01-data-ready.png",
    5: "01-data-ready.png",
    6: "01-data-ready.png",
    7: "01-data-ready.png",
    8: "02-settings-ready.png",
    9: "01-data-ready.png",
    10: "01-data-ready.png",
    11: "02-settings-ready.png",
    12: "03-hotkey-wait.png",
    13: "04-input-running.png",
    14: "05-ai-standards.png",
    15: "05-ai-standards.png",
    16: "05-ai-standards.png",
    17: "05-ai-standards.png",
    18: "06-ai-results.png",
    19: "06-ai-results.png",
    20: "07-behavior.png",
    21: "07-behavior.png",
    22: "07-behavior.png",
    23: "07-behavior.png",
    24: "07-behavior.png",
    25: "08-settings.png",
    26: "09-api-keys.png",
    27: "04-input-running.png",
    28: "09-api-keys.png",
    31: "09-api-keys.png",
    34: "09-api-keys.png",
}

FORCE_DENSE: set[int] = set()

MARKERS = {
    2: [(3.8, 4.0, "1"), (3.8, 9.2, "2"), (3.8, 14.4, "3"), (3.8, 19.6, "4")],
    4: [(34, 13, "1"), (54, 45, "2"), (58, 91, "3")],
    5: [(24, 13, "1"), (15, 29, "2"), (33, 13, "3")],
    6: [(60, 28, "1"), (60, 50, "2"), (60, 69, "3")],
    7: [(35, 13, "1"), (43, 13, "2"), (51, 13, "3"), (59, 13, "4")],
    8: [(24, 91, "1"), (38, 91, "2"), (50, 91, "3"), (60, 91, "4")],
    10: [(20, 95, "1"), (93, 95, "2")],
    11: [(20, 95, "1"), (25, 95, "2")],
    12: [(20, 95, "1"), (93, 95, "2")],
    13: [(52, 85, "1"), (80, 85, "2"), (94, 95, "3")],
    15: [(28, 14, "1"), (40, 14, "2")],
    16: [(19, 29, "1"), (29, 34, "2")],
    17: [(18, 44, "1"), (19, 52, "2"), (30, 64, "3")],
    18: [(95, 95, "1"), (78, 48, "2")],
    19: [(89, 95, "1"), (4, 4, "2")],
    20: [(18, 42, "1"), (43, 43, "2"), (78, 43, "3")],
    21: [(18, 41, "1"), (43, 33, "2"), (43, 45, "3")],
    22: [(87, 35, "1"), (96, 36, "2")],
    23: [(91, 14, "1"), (91, 95, "2")],
    24: [(81, 58, "1"), (23, 95, "2")],
    25: [(48, 19, "1"), (54, 34, "2"), (54, 44, "3"), (70, 62, "4")],
    26: [(74, 42, "1"), (74, 68, "2")],
}

CALLOUTS = {
    2: ["자동 입력", "AI 평어", "행동발달", "환경 설정"],
    4: ["내용 준비", "학생 표", "입력 설정과 시작"],
    5: ["학생 수 조절", "이름과 학생 순서", "명단 저장"],
    6: ["첫 학생 내용", "중간 학생 내용", "마지막 학생 내용"],
    7: ["작업 저장", "작업 불러오기", "내용 지우기", "명단 저장"],
    8: ["이동 칸", "입력 간격", "앞에 빈칸", "긴급 중지"],
    10: ["키 입력 방식 끄기", "NEIS 입력 시작"],
    11: ["키 입력 방식 켜기", "시작 키 선택"],
    12: ["키 입력 방식과 F2", "시작 대기 취소"],
    13: ["진행률", "완료 학생 수", "입력 중지"],
    15: ["AI 서비스 선택", "API 키 관리"],
    16: ["학생 수", "학생당 문장 수"],
    17: ["학년군", "교과", "성취기준"],
    18: ["평어 생성", "생성 결과 확인"],
    19: ["NEIS 표에 넣기", "자동 입력 메뉴"],
    20: ["학생 명단", "특성 선택", "선택 및 결과"],
    21: ["학생 선택", "특성 종류·교과", "특성 키워드"],
    22: ["특성 단계 선택", "선택 특성 제거"],
    23: ["개별 문장 수", "현재 학생·전체 생성"],
    24: ["생성 결과 확인·수정", "생성 결과 적용"],
    25: ["창을 항상 위에 고정", "AI 평어 기본값", "행동발달 기본값", "API 키 관리"],
    26: ["Gemini 키 등록·변경", "OpenAI 키 등록·변경"],
}

FLOW_STEPS = {
    14: ["AI 서비스", "생성 범위", "성취기준", "평어 생성", "결과 검토", "NEIS 표에 넣기"],
    20: ["학생 선택", "특성 선택", "단계 설정", "문장 생성", "결과 검토·수정", "결과 적용"],
}

SECTION_BY_SLIDE = {
    range(1, 4): "시작 안내",
    range(4, 14): "자동 입력",
    range(14, 20): "AI 평어",
    range(20, 25): "행동발달",
    range(25, 27): "환경 설정",
    range(27, 29): "문제 해결",
    range(29, 35): "부록 · API 키",
}


def section_name(number: int) -> str:
    for numbers, name in SECTION_BY_SLIDE.items():
        if number in numbers:
            return name
    return "사용 설명서"


def inline_markup(value: str) -> str:
    escaped = html.escape(value.strip())
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    return escaped


def strip_production_sections(lines: list[str]) -> list[str]:
    result: list[str] = []
    skip = False
    skip_entire = {"슬라이드 제목", "화면 구성"}
    hide_heading = {"핵심 원고", "표지 문구"}
    for line in lines:
        if line.startswith("### "):
            title = line[4:].strip()
            skip = title in skip_entire
            if skip:
                continue
            if title in hide_heading:
                continue
        if not skip:
            result.append(line)
    return result


def markdown_to_html(markdown: str) -> str:
    lines = strip_production_sections(markdown.splitlines())
    output: list[str] = []
    paragraph: list[str] = []
    list_type = ""
    list_items: list[str] = []

    def flush_paragraph() -> None:
        if paragraph:
            output.append(f"<p>{inline_markup(' '.join(paragraph))}</p>")
            paragraph.clear()

    def flush_list() -> None:
        nonlocal list_type
        if list_items:
            tag = "ol" if list_type == "ol" else "ul"
            output.append(f"<{tag}>" + "".join(f"<li>{inline_markup(item)}</li>" for item in list_items) + f"</{tag}>")
            list_items.clear()
        list_type = ""

    for raw in lines:
        line = raw.rstrip()
        if line.strip() == "---":
            continue
        if not line:
            flush_paragraph()
            flush_list()
            continue
        if line.startswith("#### "):
            flush_paragraph()
            flush_list()
            output.append(f"<h4>{inline_markup(line[5:])}</h4>")
            continue
        if line.startswith("### "):
            flush_paragraph()
            flush_list()
            output.append(f"<h3>{inline_markup(line[4:])}</h3>")
            continue
        if line.startswith("> "):
            flush_paragraph()
            flush_list()
            output.append(f"<blockquote>{inline_markup(line[2:])}</blockquote>")
            continue
        match = re.match(r"^(\d+)\.\s+(.+)$", line)
        if match:
            flush_paragraph()
            if list_type not in {"", "ol"}:
                flush_list()
            list_type = "ol"
            list_items.append(match.group(2))
            continue
        if line.startswith("- "):
            flush_paragraph()
            if list_type not in {"", "ul"}:
                flush_list()
            list_type = "ul"
            list_items.append(line[2:])
            continue
        flush_list()
        paragraph.append(line)

    flush_paragraph()
    flush_list()
    return "\n".join(output)


def extract_slides(text: str) -> list[tuple[int, str, str]]:
    slides: list[tuple[int, str, str]] = []
    for chunk in re.split(r"(?m)^## ", text):
        match = re.match(r"슬라이드 (\d+)\. ([^\n]+)\n(.*)", chunk, re.S)
        if match:
            slides.append((int(match.group(1)), match.group(2).strip(), match.group(3).strip()))
    return slides


def marker_html(number: int) -> str:
    markers = MARKERS.get(number, [])
    if not markers:
        return ""

    gap = 6.2
    rail_y = [y for _x, y, _label in markers]
    sorted_indexes = sorted(range(len(markers)), key=lambda index: markers[index][1])
    groups: list[list[int]] = []
    for index in sorted_indexes:
        if not groups or markers[index][1] - markers[groups[-1][-1]][1] >= gap:
            groups.append([index])
        else:
            groups[-1].append(index)
    for group in groups:
        if len(group) == 1:
            continue
        center = sum(markers[index][1] for index in group) / len(group)
        start = max(3.2, min(96.8 - gap * (len(group) - 1), center - gap * (len(group) - 1) / 2))
        for offset, index in enumerate(group):
            rail_y[index] = start + gap * offset

    lines = "".join(
        f'<line x1="0" y1="{rail_y[index]}" x2="{x}" y2="{y}"></line>'
        f'<circle cx="{x}" cy="{y}" r="0.72"></circle>'
        for index, (x, y, _label) in enumerate(markers)
    )
    labels = "".join(
        f'<span class="marker" style="left:-2.4%;top:{rail_y[index]}%">{label}</span>'
        for index, (_x, _y, label) in enumerate(markers)
    )
    return f'<svg class="marker-links" viewBox="0 0 100 100" preserveAspectRatio="none">{lines}</svg>{labels}'


def callout_html(number: int) -> str:
    labels = CALLOUTS.get(number, [])
    if not labels:
        return ""
    items = "".join(
        f'<div><b>{index}</b><span>{html.escape(label)}</span></div>'
        for index, label in enumerate(labels, 1)
    )
    return f'<div class="screen-guide"><h3>화면 번호 안내</h3><div class="callout-list">{items}</div></div>'


def mini_flow_html(number: int) -> str:
    steps = FLOW_STEPS.get(number, [])
    if not steps:
        return ""
    items = "".join(
        f'<div><b>{index}</b><span>{html.escape(label)}</span></div>'
        for index, label in enumerate(steps, 1)
    )
    return f'<div class="mini-flow"><h3>기본 순서</h3><div>{items}</div></div>'


def overview_flow_html() -> str:
    paths = [
        ("직접 작성", ["내용 작성", "입력 설정", "첫 입력칸 선택", "자동 입력"]),
        ("AI 교과 평어", ["평어 생성", "NEIS 표에 넣기", "내용 확인", "자동 입력"]),
        ("행동특성", ["특성 선택", "문장 생성", "결과 적용", "내용 확인", "자동 입력"]),
    ]
    rows = []
    for label, steps in paths:
        route = '<i>›</i>'.join(f"<span>{html.escape(step)}</span>" for step in steps)
        rows.append(f'<div class="flow-row"><b>{html.escape(label)}</b><div>{route}</div></div>')
    return (
        '<div class="overview-flow"><h3>내용 준비 방법을 선택하세요</h3>'
        + "".join(rows)
        + '<p>어떤 경로를 선택해도 마지막에는 <strong>자동 입력 화면에서 학생 순서와 내용을 확인</strong>합니다.</p></div>'
    )


def remove_markdown_section(markdown: str, title: str) -> str:
    return re.sub(
        rf"(?ms)^### {re.escape(title)}\s*\n.*?(?=^### |\Z)",
        "",
        markdown,
    ).strip()


def browser_mock(number: int) -> str:
    if number == 30:
        return """
        <div class="browser-mock gemini">
          <div class="browser-bar"><span></span><span></span><span></span><div>🔒 aistudio.google.com/app/apikey</div></div>
          <div class="web-body"><div class="web-brand">Google AI Studio</div><h3>API Keys</h3>
          <div class="web-button">＋ Create API key</div><div class="web-row">Default project <b>Gemini API</b></div>
          <div class="web-safe">API 키 문자열은 설명서에 표시하지 않습니다</div></div>
        </div>"""
    if number in {32, 33}:
        title = "API Keys" if number == 32 else "Billing"
        action = "＋ Create new secret key" if number == 32 else "Usage · Credits · Auto recharge"
        return f"""
        <div class="browser-mock openai">
          <div class="browser-bar"><span></span><span></span><span></span><div>🔒 platform.openai.com</div></div>
          <div class="web-body"><div class="web-brand">OpenAI Platform</div><h3>{title}</h3>
          <div class="web-button">{action}</div>
          <div class="web-row">Project <b>NeisAutoInputV4</b></div>
          <div class="web-safe">계정·결제·키 정보는 흐림 처리합니다</div></div>
        </div>"""
    return ""


def cover_page() -> str:
    return """
    <section class="page cover">
      <div class="cover-copy">
        <div class="cover-badge">교사를 위한 쉬운 시작 안내서</div>
        <h1>NeisAutoInputV4</h1>
        <h2>평어 및 행동특성<br>자동 입력 및 AI 생성기</h2>
        <p>학생별 내용을 준비하고 NEIS에 안전하게<br>자동 입력하는 방법을 안내합니다.</p>
      </div>
      <div class="cover-shot"><img src="./assets/screens/01-data-ready.png" alt="NeisAutoInputV4 자동 입력 화면"></div>
      <div class="cover-flow">
        <div><b>1</b><span>데이터 준비</span></div><i>›</i>
        <div><b>2</b><span>입력 설정</span></div><i>›</i>
        <div><b>3</b><span>자동 입력</span></div>
      </div>
      <footer><span>NeisAutoInputV4 사용 설명서</span><span>01 / 34</span></footer>
    </section>
    """


def page_html(number: int, title: str, markdown: str) -> str:
    if number == 3:
        body = overview_flow_html()
    else:
        source = remove_markdown_section(markdown, "기본 순서") if number in FLOW_STEPS else markdown
        body = markdown_to_html(source)
        body += mini_flow_html(number)
        body += callout_html(number)
    body_length = len(re.sub(r"<[^>]+>", "", body))
    density = (
        " dense"
        if number in FORCE_DENSE or body_length > 1150
        else (" compact" if body_length > 820 else "")
    )
    screen = SCREEN_BY_SLIDE.get(number)
    mock = browser_mock(number)
    visual = ""
    if screen:
        outside_class = " marker-outside" if number in MARKERS else ""
        visual = (
            f'<div class="screen{outside_class}"><img src="./assets/screens/{screen}" alt="{html.escape(title)}">'
            f"{marker_html(number)}</div>"
        )
    elif mock:
        visual = mock

    no_visual = " no-visual" if not visual else ""
    flow_overview = " flow-overview" if number == 3 else ""
    return f"""
    <section class="page{density}{no_visual}{flow_overview}" data-slide="{number}" data-marker-count="{len(MARKERS.get(number, []))}" data-callout-count="{len(CALLOUTS.get(number, []))}">
      <header>
        <div class="brand"><span>N</span> NeisAutoInputV4</div>
        <div class="chapter">{section_name(number)}</div>
      </header>
      <div class="title-row"><div class="step">{number:02d}</div><h2>{html.escape(title)}</h2></div>
      <div class="page-content">
        <article>{body}</article>
        {visual}
      </div>
      <footer><span>{section_name(number)}</span><span>{number:02d} / 34</span></footer>
    </section>
    """


STYLE = """
  @font-face{font-family:Pretendard;src:url('./assets/fonts/Pretendard-Regular.ttf') format('truetype');font-weight:400}
  @font-face{font-family:Pretendard;src:url('./assets/fonts/Pretendard-SemiBold.ttf') format('truetype');font-weight:600}
  @font-face{font-family:Pretendard;src:url('./assets/fonts/Pretendard-Bold.ttf') format('truetype');font-weight:700}
  :root{--blue:#2f73f6;--blue2:#1557cf;--pale:#f3f7ff;--ink:#172033;--body:#455064;--muted:#7b8597;--line:#dce2eb;--green:#16815e;--red:#cf4949}
  *{box-sizing:border-box}
  html,body{margin:0;background:#e9edf3;color:var(--ink);font-family:Pretendard,sans-serif;-webkit-print-color-adjust:exact;print-color-adjust:exact}
  body{display:flex;flex-direction:column;align-items:center;gap:28px;padding:28px 0}
  .page{position:relative;width:1600px;height:900px;overflow:hidden;background:#fff;padding:42px 58px 38px;page-break-after:always;break-after:page;box-shadow:0 16px 50px rgb(30 43 68 / 12%)}
  .page>header{height:34px;display:flex;justify-content:space-between;align-items:center;color:var(--muted);font-size:16px;font-weight:600}
  .brand{display:flex;align-items:center;gap:9px;color:var(--blue2)}.brand span{display:grid;place-items:center;width:28px;height:28px;border-radius:8px;background:var(--blue);color:white}
  .chapter{letter-spacing:.02em}.title-row{height:94px;display:flex;align-items:center;gap:18px;border-bottom:1px solid var(--line)}
  .step{display:grid;place-items:center;width:47px;height:47px;border-radius:15px;background:var(--blue);color:#fff;font-size:20px;font-weight:700}
  h1,h2,h3,h4,p{margin:0}.title-row h2{font-size:37px;letter-spacing:-.04em}
  .page-content{display:grid;grid-template-columns:minmax(0,0.93fr) minmax(0,1.42fr);gap:30px;height:668px;padding-top:24px}
  article{min-width:0;height:100%;padding:20px 22px;border:1px solid var(--line);border-radius:18px;background:linear-gradient(180deg,#fff,#fbfcfe);overflow:hidden;font-size:17px;line-height:1.43;color:var(--body)}
  article h3{margin:2px 0 10px;color:var(--blue2);font-size:20px}article h3:not(:first-child){margin-top:18px;padding-top:14px;border-top:1px solid #e9edf3}
  article h4{margin:14px 0 6px;color:var(--ink);font-size:17px}article p{margin:0 0 10px}
  article ul,article ol{margin:5px 0 12px;padding-left:24px}article li{margin:4px 0;padding-left:2px}
  article strong{color:var(--ink)}article code{padding:2px 6px;border-radius:6px;background:#edf3ff;color:var(--blue2);font-family:Pretendard,sans-serif;font-weight:600}
  blockquote{margin:12px 0;padding:12px 14px;border-left:4px solid var(--blue);border-radius:0 10px 10px 0;background:var(--pale);color:#294a7c;font-weight:600}
  .screen-guide{margin-top:15px;padding-top:13px;border-top:1px solid #e9edf3}.screen-guide h3{margin:0 0 9px!important;padding:0!important;border:0!important}
  .callout-list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:7px 9px}
  .callout-list>div{display:flex;align-items:center;gap:8px;min-width:0;padding:7px 9px;border:1px solid #dbe5f8;border-radius:10px;background:#f6f9ff;color:#294a7c;font-size:.92em;font-weight:600}
  .callout-list b{display:grid;place-items:center;flex:0 0 23px;width:23px;height:23px;border-radius:50%;background:rgb(47 115 246 / 88%);color:#fff;font-size:12px}
  .mini-flow{margin-top:14px;padding-top:12px;border-top:1px solid #e9edf3}.mini-flow h3{margin:0 0 9px!important;padding:0!important;border:0!important}
  .mini-flow>div{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:7px}
  .mini-flow>div>div{display:flex;align-items:center;gap:8px;padding:7px 9px;border-radius:10px;background:#edf3ff;color:#294a7c;font-size:.9em;font-weight:600}
  .mini-flow b{display:grid;place-items:center;flex:0 0 22px;width:22px;height:22px;border-radius:7px;background:var(--blue);color:#fff;font-size:12px}
  .compact article{font-size:15.5px;line-height:1.36}.compact article h3{font-size:18px;margin-bottom:7px}.compact article h3:not(:first-child){margin-top:12px;padding-top:10px}.compact article h4{font-size:16px;margin:10px 0 4px}.compact article p{margin-bottom:7px}.compact article li{margin:2px 0}
  .dense article{font-size:14px;line-height:1.29;padding:15px 17px}.dense article h3{font-size:16px;margin-bottom:5px}.dense article h3:not(:first-child){margin-top:8px;padding-top:7px}.dense article h4{font-size:14.5px;margin:7px 0 3px}.dense article p{margin-bottom:5px}.dense article ul,.dense article ol{margin:3px 0 7px}.dense article li{margin:1px 0}
  .screen{position:relative;align-self:start;width:100%;aspect-ratio:16/9;overflow:hidden;border:1px solid #cad2df;border-radius:17px;background:#f5f7fa;box-shadow:0 15px 32px rgb(31 52 91 / 13%)}
  .screen img{display:block;width:100%;height:100%;object-fit:contain}
  .screen.marker-outside{overflow:visible}
  .screen.marker-outside img{border-radius:16px}
  .marker-links{position:absolute;inset:0;width:100%;height:100%;overflow:visible;pointer-events:none}
  .marker-links line{stroke:rgb(47 115 246 / 35%);stroke-width:.42;stroke-dasharray:1.1 1.15;vector-effect:non-scaling-stroke}
  .marker-links circle{fill:rgb(47 115 246 / 58%);stroke:rgb(255 255 255 / 88%);stroke-width:.22;vector-effect:non-scaling-stroke}
  .marker{position:absolute;display:grid;place-items:center;width:25px;height:25px;transform:translate(-50%,-50%);border:2px solid rgb(255 255 255 / 88%);border-radius:50%;background:rgb(47 115 246 / 74%);color:#fff;box-shadow:0 3px 8px rgb(25 76 175 / 18%);font-size:13px;font-weight:700}
  footer{position:absolute;left:58px;right:58px;bottom:18px;display:flex;justify-content:space-between;color:#8b95a7;font-size:14px}
  .no-visual .page-content{grid-template-columns:1fr}.no-visual article{column-count:2;column-gap:34px;padding:24px 30px}.no-visual article h3,.no-visual article h4,.no-visual article blockquote{break-after:avoid}.no-visual article p,.no-visual article ul,.no-visual article ol{break-inside:avoid}
  .flow-overview article{column-count:1;padding:34px 40px}
  .overview-flow h3{margin:0 0 22px;font-size:25px;color:var(--ink)}
  .flow-row{display:grid;grid-template-columns:170px 1fr;gap:18px;align-items:center;margin:14px 0;padding:17px 18px;border:1px solid #dbe5f8;border-radius:15px;background:linear-gradient(90deg,#f4f8ff,#fff)}
  .flow-row>b{color:var(--blue2);font-size:18px}.flow-row>div{display:flex;align-items:center;gap:9px}.flow-row span{flex:1;padding:10px 8px;border-radius:10px;background:#fff;box-shadow:0 3px 12px rgb(31 52 91 / 8%);color:#294a7c;text-align:center;font-weight:600}.flow-row i{color:#8fa5c8;font-size:23px}
  .overview-flow p{margin-top:22px;padding:16px 18px;border-left:4px solid var(--blue);border-radius:0 12px 12px 0;background:var(--pale);font-size:18px}
  .browser-mock{align-self:start;overflow:hidden;aspect-ratio:16/9;border:1px solid #cfd6e2;border-radius:17px;background:#fff;box-shadow:0 15px 32px rgb(31 52 91 / 13%)}
  .browser-bar{height:48px;display:flex;align-items:center;gap:8px;padding:0 16px;background:#edf1f6}.browser-bar>span{width:12px;height:12px;border-radius:50%;background:#c4ccd8}.browser-bar>div{flex:1;margin-left:8px;padding:8px 15px;border-radius:9px;background:#fff;color:#687389;font-size:14px}
  .web-body{padding:42px}.web-brand{color:var(--muted);font-weight:600}.web-body h3{margin:15px 0 24px;font-size:36px}.web-button{display:inline-block;padding:13px 19px;border-radius:10px;background:var(--blue);color:#fff;font-weight:700}.web-row{margin-top:28px;padding:18px;border:1px solid var(--line);border-radius:12px}.web-safe{margin-top:28px;padding:14px;border-radius:10px;background:#fff2f2;color:#994141}
  .cover{background:radial-gradient(circle at 6% 0%,rgb(72 132 255 / 18%),transparent 32%),linear-gradient(135deg,#f9fbff 0%,#fff 70%)}
  .cover-copy{position:absolute;z-index:2;left:78px;top:92px;width:630px}.cover-badge{display:inline-block;padding:9px 15px;border:1px solid #bad0ff;border-radius:999px;color:var(--blue2);font-weight:700}.cover h1{margin-top:25px;font-size:68px;letter-spacing:-.055em}.cover h2{margin-top:18px;font-size:36px;line-height:1.28;letter-spacing:-.035em}.cover-copy p{margin-top:25px;color:var(--muted);font-size:21px;line-height:1.55}
  .cover-shot{position:absolute;right:30px;top:150px;width:820px;aspect-ratio:16/9;overflow:hidden;border:12px solid #dbe6fb;border-radius:25px;box-shadow:0 20px 50px rgb(37 66 119 / 20%);transform:rotate(-1deg)}.cover-shot img{width:100%;height:100%;object-fit:cover}
  .cover-flow{position:absolute;left:78px;right:78px;bottom:70px;display:flex;align-items:center;gap:16px;padding:16px 22px;border:1px solid var(--line);border-radius:18px;background:rgb(255 255 255 / 92%);box-shadow:0 14px 35px rgb(31 52 91 / 10%)}
  .cover-flow div{display:flex;align-items:center;gap:11px;flex:1;font-size:18px;font-weight:600}.cover-flow b{display:grid;place-items:center;width:34px;height:34px;border-radius:10px;background:var(--blue);color:#fff}.cover-flow i{color:#9ba5b7;font-size:26px}
  @page{size:13.333333in 7.5in;margin:0}
  @media print{html,body{width:13.333333in;background:#fff}body{display:block;padding:0}.page{width:1600px;height:900px;zoom:.8;box-shadow:none}}
"""


def build() -> None:
    source = REPORT.read_text(encoding="utf-8")
    slides = extract_slides(source)
    if [number for number, _title, _body in slides] != list(range(1, 35)):
        raise RuntimeError("report.md의 슬라이드 번호가 1~34 순서가 아닙니다.")
    for number, markers in MARKERS.items():
        labels = CALLOUTS.get(number, [])
        marker_numbers = [label for _x, _y, label in markers]
        expected_numbers = [str(index) for index in range(1, len(markers) + 1)]
        if marker_numbers != expected_numbers:
            raise RuntimeError(f"슬라이드 {number}: 스크린샷 번호가 1부터 순서대로 이어지지 않습니다.")
        if len(labels) != len(markers):
            raise RuntimeError(f"슬라이드 {number}: 스크린샷 번호와 설명 번호 개수가 다릅니다.")

    pages = [cover_page()]
    pages.extend(page_html(number, title, body) for number, title, body in slides if number != 1)
    document = f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>NeisAutoInputV4 사용 설명서</title>
  <style>{STYLE}</style>
</head>
<body>
{''.join(pages)}
</body>
</html>
"""
    document = "\n".join(line.rstrip() for line in document.splitlines()) + "\n"
    OUTPUT.write_text(document, encoding="utf-8", newline="\n")
    print(f"{OUTPUT} 생성 완료 · {len(pages)} pages")


if __name__ == "__main__":
    build()
