import os
import json
from pathlib import Path
from datetime import datetime, timedelta

import requests
from curl_cffi import requests as cffi_requests


# ============================================================
# 기본 설정
# ============================================================

SITE_NO = os.getenv("SITE_NO", "0257")
SITE_NAME = os.getenv("SITE_NAME", "광교")

MOVIE_NO = os.getenv("MOVIE_NO", "30001323")
MOVIE_TITLE = os.getenv("MOVIE_TITLE", "오디세이")

SCREEN_KEYWORD = os.getenv("SCREEN_KEYWORD", "IMAX")

START_DATE = os.getenv("START_DATE", "2026-09-01")
END_DATE = os.getenv("END_DATE", "2026-09-06")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


# ============================================================
# 상태 저장 폴더
# ============================================================

CACHE_DIR = Path(".cache")
CACHE_DIR.mkdir(exist_ok=True)

STATE_FILE = CACHE_DIR / "last_state.json"


# ============================================================
# 날짜 목록
# ============================================================

def get_target_dates():
    start = datetime.strptime(START_DATE, "%Y-%m-%d")
    end = datetime.strptime(END_DATE, "%Y-%m-%d")

    dates = []

    current = start

    while current <= end:
        dates.append(current.strftime("%Y%m%d"))
        current += timedelta(days=1)

    return dates


# ============================================================
# CGV 시간표 API
# ============================================================

def fetch_schedule(date_str):

    url = "https://cgv.co.kr/api/v1/booking/searchMovScnInfo"

    params = {
        "coCd": "A420",
        "siteNo": SITE_NO,
        "scnYmd": date_str,
        "rtctlScopCd": "08",
    }

    headers = {
        "Accept": "application/json",
        "Referer": "https://cgv.co.kr/cnm/movieBook/cinema",
    }

    print()
    print("==================================================")
    print("조회 날짜:", date_str)
    print("==================================================")

    response = cffi_requests.get(
        url,
        params=params,
        headers=headers,
        impersonate="chrome",
        timeout=30,
    )

    print("HTTP:", response.status_code)
    print("URL :", response.url)

    if response.status_code != 200:
        print("CGV API 호출 실패")
        print(response.text[:1000])

        raise RuntimeError(
            f"CGV API HTTP {response.status_code}"
        )

    try:
        payload = response.json()

    except Exception as e:
        print("JSON 파싱 실패")
        print(response.text[:1500])

        raise RuntimeError(
            "CGV 응답 JSON 파싱 실패"
        ) from e

    status_code = payload.get("statusCode")

    print("CGV statusCode:", status_code)

    if status_code != 0:
        print(
            "CGV statusMessage:",
            payload.get("statusMessage")
        )

        raise RuntimeError(
            "CGV API statusCode 오류"
        )

    data = payload.get("data", [])

    if not isinstance(data, list):
        raise RuntimeError(
            "CGV API data 형식이 예상과 다름"
        )

    print("전체 회차 수:", len(data))

    return data


# ============================================================
# 시간 표시
# ============================================================

def format_time(value):

    value = str(value or "")

    if len(value) == 4:
        return f"{value[:2]}:{value[2:]}"

    return value


# ============================================================
# CGV 한 회차 정보 정리
# ============================================================

def normalize_show(row):

    return {
        "date": str(
            row.get("scnYmd", "")
        ),

        "movie_no": str(
            row.get("movNo", "")
        ),

        "movie": str(
            row.get("movNm")
            or row.get("expoProdNm")
            or row.get("prodNm")
            or ""
        ),

        "screen_no": str(
            row.get("scnsNo", "")
        ),

        "screen": str(
            row.get("scnsNm")
            or row.get("expoScnsNm")
            or ""
        ),

        "sequence": str(
            row.get("scnSseq", "")
        ),

        "start": str(
            row.get("scnsrtTm", "")
        ),

        "end": str(
            row.get("scnendTm", "")
        ),

        "remaining": str(
            row.get("frSeatCnt", "")
        ),

        "total": str(
            row.get("stcnt", "")
        ),
    }


# ============================================================
# 우리가 원하는 회차인지 판별
# ============================================================

def is_target_show(show):

    movie_match = (
        show["movie_no"] == MOVIE_NO
        or show["movie"] == MOVIE_TITLE
    )

    imax_match = (
        SCREEN_KEYWORD.lower()
        in show["screen"].lower()
    )

    return movie_match and imax_match


# ============================================================
# 고유 회차 ID
# ============================================================

def get_show_id(show):

    return "|".join(
        [
            show["date"],
            show["movie_no"],
            show["screen_no"],
            show["sequence"],
            show["start"],
        ]
    )


# ============================================================
# 대상 IMAX 회차 찾기
# ============================================================

def find_matches():

    matches = []

    for date_str in get_target_dates():

        rows = fetch_schedule(date_str)

        for row in rows:

            show = normalize_show(row)

            if not is_target_show(show):
                continue

            show["id"] = get_show_id(show)

            matches.append(show)

            print()
            print("★★★★★ IMAX MATCH ★★★★★")
            print("영화:", show["movie"])
            print("날짜:", show["date"])
            print(
                "시간:",
                format_time(show["start"])
            )
            print("상영관:", show["screen"])
            print(
                "좌석:",
                show["remaining"],
                "/",
                show["total"],
            )
            print(
                "회차 ID:",
                show["id"],
            )

    return matches


# ============================================================
# 기존 상태 읽기
# ============================================================

def load_state():

    if not STATE_FILE.exists():
        return None

    try:

        data = json.loads(
            STATE_FILE.read_text(
                encoding="utf-8"
            )
        )

        if not isinstance(data, dict):
            return None

        return data

    except Exception:

        return None


# ============================================================
# 상태 저장
# ============================================================

def save_state(seen_ids):

    data = {
        "seen_ids": sorted(seen_ids),
    }

    STATE_FILE.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


# ============================================================
# Telegram 전송
# ============================================================

def send_telegram(message):

    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN이 없습니다."
        )

    if not TELEGRAM_CHAT_ID:
        raise RuntimeError(
            "TELEGRAM_CHAT_ID가 없습니다."
        )

    url = (
        "https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    response = requests.post(
        url,
        data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "disable_notification": "false",
        },
        timeout=30,
    )

    print(
        "Telegram HTTP:",
        response.status_code,
    )

    response.raise_for_status()


# ============================================================
# Telegram 메시지 작성
# ============================================================

def build_alert_message(new_matches):

    lines = [
        "🚨 CGV 광교 IMAX 예매 오픈 감지",
        "",
        f"영화: {MOVIE_TITLE}",
        "",
    ]

    new_matches = sorted(
        new_matches,
        key=lambda x: (
            x["date"],
            x["start"],
        ),
    )

    for show in new_matches:

        date_text = datetime.strptime(
            show["date"],
            "%Y%m%d",
        ).strftime("%m/%d")

        time_text = format_time(
            show["start"]
        )

        line = (
            f"{date_text} "
            f"{time_text} "
            f"{show['screen']}"
        )

        if show["remaining"]:
            line += (
                f" | 잔여 "
                f"{show['remaining']}석"
            )

        lines.append(line)

    lines.extend(
        [
            "",
            "CGV 앱에서 바로 확인하세요.",
        ]
    )

    return "\n".join(lines)


# ============================================================
# 메인
# ============================================================

def main():

    print("CGV 감시 시작")
    print("------------------------------")
    print("극장:", SITE_NAME, SITE_NO)
    print(
        "영화:",
        MOVIE_TITLE,
        f"({MOVIE_NO})",
    )
    print("상영관:", SCREEN_KEYWORD)
    print(
        "기간:",
        START_DATE,
        "~",
        END_DATE,
    )
    print("------------------------------")

    matches = find_matches()

    print()
    print("==================================================")
    print("현재 IMAX 매칭 회차:", len(matches))
    print("==================================================")

    current_ids = {
        show["id"]
        for show in matches
    }

    state = load_state()

    # --------------------------------------------------------
    # 최초 실행
    #
    # 현재 열려 있는 회차를 baseline으로만 저장한다.
    # 따라서 이미 열린 9/1 회차 때문에 알림이 울리지 않는다.
    # --------------------------------------------------------

    if state is None:

        print()
        print("최초 실행입니다.")
        print(
            "현재 회차를 기준 상태로 저장합니다."
        )

        save_state(current_ids)

        print(
            "기존 회차에 대한 Telegram 알림은 보내지 않습니다."
        )

        return

    seen_ids = set(
        state.get(
            "seen_ids",
            []
        )
    )

    new_matches = [
        show
        for show in matches
        if show["id"] not in seen_ids
    ]

    print()
    print(
        "이전에 확인한 회차:",
        len(seen_ids),
    )

    print(
        "새로 발견한 회차:",
        len(new_matches),
    )

    # --------------------------------------------------------
    # 새 IMAX 회차 발견
    # --------------------------------------------------------

    if new_matches:

        print()
        print("🚨 새로운 IMAX 회차 발견")

        for show in new_matches:

            print(
                show["date"],
                format_time(show["start"]),
                show["screen"],
            )

        message = build_alert_message(
            new_matches
        )

        send_telegram(message)

        print()
        print(
            "Telegram 알림 전송 완료"
        )

    else:

        print()
        print(
            "새로운 IMAX 회차 없음"
        )

    # 지금까지 본 회차를 누적 저장
    seen_ids.update(current_ids)

    save_state(seen_ids)


if __name__ == "__main__":
    main()
