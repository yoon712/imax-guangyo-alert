import os
import re
import json
import hashlib
from pathlib import Path
from datetime import date, timedelta
import requests
from playwright.sync_api import sync_playwright

TARGET_URL = os.getenv("TARGET_URL", "https://cgv.co.kr/cnm/movieBook/cinema?siteNm=%EA%B4%91%EA%B5%90&siteNo=0257")
MOVIE_TITLE = os.getenv("MOVIE_TITLE", "오디세이")
THEATER_KEYWORD = os.getenv("THEATER_KEYWORD", "광교")
SCREEN_KEYWORD = os.getenv("SCREEN_KEYWORD", "IMAX")
START_DATE = os.getenv("START_DATE", "2026-08-31")
LOOKAHEAD_DAYS = int(os.getenv("LOOKAHEAD_DAYS", "14"))

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

CACHE_DIR = Path(".cache")
CACHE_DIR.mkdir(exist_ok=True)
STATE_FILE = CACHE_DIR / "last_state.txt"
DEBUG_FILE = CACHE_DIR / "last_page.txt"

def build_date_labels(start_date_str, days):
    y, m, d = map(int, start_date_str.split("-"))
    start = date(y, m, d)
    labels = set()

    for i in range(days):
        cur = start + timedelta(days=i)
        mm = cur.month
        dd = cur.day

        # 페이지에 여러 포맷으로 보일 수 있으니 넉넉하게
        labels.add(f"{mm}.{dd}")
        labels.add(f"{mm}/{dd}")
        labels.add(f"{mm}-{dd}")
        labels.add(f"{mm:02d}.{dd:02d}")
        labels.add(f"{mm:02d}/{dd:02d}")
        labels.add(f"{mm:02d}-{dd:02d}")
        labels.add(f"{cur.year}.{mm}.{dd}")
        labels.add(f"{cur.year}-{mm:02d}-{dd:02d}")

    return labels

def normalize_text(text: str) -> str:
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n+", "\n", text)
    return text.strip()

def fetch_rendered_text(url: str) -> str:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(8000)  # 동적 로딩 여유
        text = page.locator("body").inner_text()
        browser.close()
    return text

def extract_candidate_lines(text: str):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    out = []
    for line in lines:
        if (
            MOVIE_TITLE in line
            or SCREEN_KEYWORD.lower() in line.lower()
            or THEATER_KEYWORD in line
        ):
            out.append(line)
    return out

def is_match(full_text: str, candidate_lines: list[str], date_labels: set[str]):
    text_ok = (
        THEATER_KEYWORD in full_text
        and MOVIE_TITLE in full_text
        and SCREEN_KEYWORD.lower() in full_text.lower()
    )

    date_hit = any(label in full_text for label in date_labels)

    # 조금 더 보수적으로, 후보 줄에도 영화명이 있어야 함
    movie_line_exists = any(MOVIE_TITLE in line for line in candidate_lines)

    return text_ok and date_hit and movie_line_exists

def send_telegram(message: str):
    if not BOT_TOKEN or not CHAT_ID:
        raise RuntimeError("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 가 필요합니다.")

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    resp = requests.post(url, data={
        "chat_id": CHAT_ID,
        "text": message,
        "disable_notification": "false",
    }, timeout=30)
    resp.raise_for_status()

def load_last_state():
    if STATE_FILE.exists():
        return STATE_FILE.read_text(encoding="utf-8").strip()
    return ""

def save_state(state: str):
    STATE_FILE.write_text(state, encoding="utf-8")

def main():
    date_labels = build_date_labels(START_DATE, LOOKAHEAD_DAYS)

    full_text = fetch_rendered_text(TARGET_URL)
    full_text = normalize_text(full_text)
    DEBUG_FILE.write_text(full_text, encoding="utf-8")

    candidate_lines = extract_candidate_lines(full_text)

    found = is_match(full_text, candidate_lines, date_labels)

    relevant_text = "\n".join(candidate_lines[:50])
    state_source = json.dumps({
        "found": found,
        "relevant_text": relevant_text,
    }, ensure_ascii=False)

    state_hash = hashlib.sha256(state_source.encode("utf-8")).hexdigest()
    last_state = load_last_state()

    print("=== TARGET_URL ===")
    print(TARGET_URL)
    print("=== FOUND ===")
    print(found)
    print("=== CANDIDATE LINES ===")
    print(relevant_text if relevant_text else "(none)")

    if found and state_hash != last_state:
        message = (
            f"🎬 CGV 알림\n"
            f"- 극장: {THEATER_KEYWORD}\n"
            f"- 영화: {MOVIE_TITLE}\n"
            f"- 상영관: {SCREEN_KEYWORD}\n"
            f"- 기준일: {START_DATE} 이후\n\n"
            f"예매 페이지를 바로 확인해봐:\n{TARGET_URL}"
        )
        send_telegram(message)
        print("Telegram alert sent.")
    else:
        print("No new alert.")

    save_state(state_hash)

if __name__ == "__main__":
    main()
