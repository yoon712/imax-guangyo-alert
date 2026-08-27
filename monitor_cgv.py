import os
import json
import hashlib
from pathlib import Path
from datetime import datetime, timedelta

import requests
from curl_cffi import requests as cffi_requests


# ============================================================
# 설정
# ============================================================

SITE_NO = os.getenv("SITE_NO", "0257")          # CGV 광교
SITE_NAME = os.getenv("SITE_NAME", "광교")

MOVIE_TITLE = os.getenv("MOVIE_TITLE", "오디세이")
SCREEN_KEYWORD = os.getenv("SCREEN_KEYWORD", "IMAX")

START_DATE = os.getenv("START_DATE", "2026-08-31")
LOOKAHEAD_DAYS = int(os.getenv("LOOKAHEAD_DAYS", "14"))

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

CACHE_DIR = Path(".cache")
CACHE_DIR.mkdir(exist_ok=True)

STATE_FILE = CACHE_DIR / "last_state.json"
DEBUG_FILE = CACHE_DIR / "last_result.json"


# ============================================================
# 날짜 생성
# ============================================================

def get_dates():
    start = datetime.strptime(START_DATE, "%Y-%m-%d")

    return [
        (start + timedelta(days=i)).strftime("%Y%m%d")
        for i in range(LOOKAHEAD_DAYS)
    ]


# ============================================================
# CGV API 조회
# ============================================================

def fetch_schedule(date_str):
    """
    CGV 웹사이트가 사용하는 극장별 시간표 API 호출
    """

    url = "https://cgv.co.kr/cnm/atkt/searchMovScnInfo"

    params = {
        "coCd": "A420",
        "siteNo": SITE_NO,
        "scnYmd": date_str,
        "rtctlScopCd": "08",
    }

    print()
    print("======================================")
    print(f"조회 날짜: {date_str}")
    print("======================================")

    try:
        response = cffi_requests.get(
            url,
            params=params,
            impersonate="chrome",
            timeout=30,
        )

        print("HTTP:", response.status_code)
        print("URL :", response.url)

        if response.status_code != 200:
            print("CGV 응답 오류")
            print(response.text[:500])
            return []

        try:
            payload = response.json()
        except Exception:
            print("JSON 파싱 실패")
            print(response.text[:1000])
            return []

        print("statusCode:", payload.get("statusCode"))

        data = payload.get("data")

        if not isinstance(data, list):
            print("data가 리스트가 아님")
            print(json.dumps(payload, ensure_ascii=False)[:1500])
            return []

        print("전체 회차 수:", len(data))

        return data

    except Exception as e:
        print("CGV 조회 예외:", repr(e))
        return []


# ============================================================
# 회차 정보 정리
# ============================================================

def first_value(item, keys):
    for key in keys:
        value = item.get(key)

        if value not in (None, ""):
            return str(value)

    return ""


def normalize_show(item, date_str):

    movie = first_value(
        item,
        [
            "movNm",
            "movieNm",
            "movieName",
        ],
    )

    start_time = first_value(
        item,
        [
            "scnsrtTm",
            "scnSrtTm",
            "startTime",
        ],
    )

    end_time = first_value(
        item,
        [
            "scnendTm",
            "scnEndTm",
            "endTime",
        ],
    )

    hall = first_value(
        item,
        [
            "scnsrtNm",
            "scrnNm",
            "screenNm",
            "theaterNm",
            "hallNm",
        ],
    )

    screen_type = first_value(
        item,
        [
            "scrnKindNm",
            "screenTypeNm",
            "spclHallNm",
            "roomTypeNm",
        ],
    )

    remaining = first_value(
        item,
        [
            "frSeatCnt",
            "remainSeatCnt",
            "availableSeatCnt",
        ],
    )

    total = first_value(
        item,
        [
            "stcnt",
            "seatCnt",
            "totalSeatCnt",
        ],
    )

    # CGV 응답 필드가 변해도 IMAX라는 값이 다른 필드에
    # 들어 있을 수 있으므로 JSON 전체도 검색한다.
    raw_text = json.dumps(
        item,
        ensure_ascii=False,
    )

    return {
        "date": date_str,
        "movie": movie,
        "start": start_time,
        "end": end_time,
        "hall": hall,
        "screen_type": screen_type,
        "remaining": remaining,
        "total": total,
        "raw": raw_text,
    }


# ============================================================
# 오디세이 + IMAX 검색
# ============================================================

def find_matches():

    matches = []
    debug = {}

    for date_str in get_dates():

        rows = fetch_schedule(date_str)

        debug[date_str] = rows

        for row in rows:

            show = normalize_show(row, date_str)

            movie_match = (
                MOVIE_TITLE.lower()
                in show["movie"].lower()
            )

            imax_match = (
                SCREEN_KEYWORD.lower()
                in show["raw"].lower()
            )

            if movie_match and imax_match:

                matches.append(show)

                print()
                print("★★★★★ MATCH ★★★★★")
                print("영화:", show["movie"])
                print("날짜:", show["date"])
                print("시간:", show["start"])
                print("상영관:", show["hall"])
                print("타입:", show["screen_type"])
                print(
                    "좌석:",
                    show["remaining"],
                    "/",
                    show["total"],
                )

    DEBUG_FILE.write_text(
        json.dumps(
            debug,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    return matches


# ============================================================
# Telegram
# ============================================================

def send_telegram(text):

    if not BOT_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN secret 없음"
        )

    if not CHAT_ID:
        raise RuntimeError(
            "TELEGRAM_CHAT_ID secret 없음"
        )

    url = (
        f"https://api.telegram.org/"
        f"bot{BOT_TOKEN}/sendMessage"
    )

    response = requests.post(
        url,
        data={
            "chat_id": CHAT_ID,
            "text": text,
        },
        timeout=20,
    )

    response.raise_for_status()


# ============================================================
# 기존 상태
# ============================================================

def load_state():

    if not STATE_FILE.exists():
        return []

    try:
        return json.loads(
            STATE_FILE.read_text(
                encoding="utf-8"
            )
        )

    except Exception:
        return []


def save_state(state):

    STATE_FILE.write_text(
        json.dumps(
            state,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


# ============================================================
# 비교용 ID
# ============================================================

def show_id(show):

    source = "|".join(
        [
            show["date"],
            show["movie"],
            show["start"],
            show["hall"],
            show["screen_type"],
        ]
    )

    return hashlib.sha256(
        source.encode("utf-8")
    ).hexdigest()


# ============================================================
# 실행
# ============================================================

def main():

    print("CGV 감시 시작")
    print("극장:", SITE_NAME, SITE_NO)
    print("영화:", MOVIE_TITLE)
    print("상영관:", SCREEN_KEYWORD)
    print(
        "기간:",
        START_DATE,
        "~",
        LOOKAHEAD_DAYS,
        "일",
    )

    matches = find_matches()

    print()
    print("==============================")
    print("총 매칭 회차:", len(matches))
    print("==============================")

    previous = load_state()

    previous_ids = set(
        item["id"]
        for item in previous
        if "id" in item
    )

    current_state = []

    new_matches = []

    for show in matches:

        sid = show_id(show)

        current_state.append({
            "id": sid,
            **show,
        })

        if sid not in previous_ids:
            new_matches.append(show)

    # 최초 실행인데 이미 회차가 있는 경우도
    # 테스트할 수 있게 로그 출력
    if matches:

        print()
        print("현재 확인된 회차")

        for show in matches:

            print(
                show["date"],
                show["start"],
                show["movie"],
                show["hall"],
                show["remaining"],
            )

    if new_matches:

        lines = [
            "🚨 CGV 광교 IMAX 예매 감지",
            "",
            f"영화: {MOVIE_TITLE}",
        ]

        for show in new_matches:

            d = datetime.strptime(
                show["date"],
                "%Y%m%d",
            ).strftime("%m/%d")

            line = (
                f"{d} "
                f"{show['start']} "
                f"{show['hall']}"
            )

            if show["remaining"]:
                line += (
                    f" | 잔여 "
                    f"{show['remaining']}석"
                )

            lines.append(line)

        lines.append("")
        lines.append(
            "CGV 앱에서 바로 확인하세요."
        )

        send_telegram(
            "\n".join(lines)
        )

        print()
        print(
            "Telegram 알림 전송 완료"
        )

    else:

        print()
        print(
            "새로운 회차 없음"
        )

    save_state(current_state)


if __name__ == "__main__":
    main()
