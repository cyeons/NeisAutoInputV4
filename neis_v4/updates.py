"""새 버전 알림: GitHub에 올린 최신 배포판(Latest Release)의 버전을 확인합니다."""
from __future__ import annotations

import json
import re
import urllib.request

# 공개 저장소의 'Latest' 배포판입니다. 배포할 때 태그를 v4.6.0처럼 붙여야 비교할 수 있습니다.
LATEST_RELEASE_API = "https://api.github.com/repos/cyeons/NeisAutoInput/releases/latest"
RELEASES_PAGE = "https://github.com/cyeons/NeisAutoInput/releases/latest"


def version_numbers(text: str) -> tuple[int, ...]:
    """'v4.6.0' → (4, 6, 0)"""
    return tuple(int(number) for number in re.findall(r"\d+", text))


def is_newer(latest: str, current: str) -> bool:
    return bool(version_numbers(latest)) and version_numbers(latest) > version_numbers(current)


def fetch_latest_release(timeout: float = 5) -> tuple[str, str]:
    """(태그, 내려받기 페이지 주소)를 돌려줍니다. 실패하면 예외가 납니다.

    사용자 정보는 보내지 않습니다. GitHub가 요구하는 User-Agent에도 프로그램 이름만 씁니다.
    """
    request = urllib.request.Request(
        LATEST_RELEASE_API,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "NeisAutoInputV4"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.load(response)
    url = str(data.get("html_url") or "")
    # 브라우저로 여는 주소이므로 GitHub 주소만 씁니다.
    return str(data.get("tag_name") or ""), url if url.startswith("https://github.com/") else RELEASES_PAGE
