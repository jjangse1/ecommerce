"""
fetch_gsc.py — Google Search Console 일별 집계 데이터 수집
버그 수정 내역:
  #1 dimensions ['date'] 단독 사용 → 날짜별 정확한 합산
  #2 dataByDate[:500] 슬라이싱 제거 → 전체 기간 보존
  #3 dataByDate 정렬 후 저장 → 날짜 순서 보장
"""

import os
import json
from datetime import datetime, timedelta
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# ── 환경변수 (GitHub Secrets) ─────────────────────────────
CLIENT_ID     = os.getenv("GSC_CLIENT_ID")
CLIENT_SECRET = os.getenv("GSC_CLIENT_SECRET")
REFRESH_TOKEN = os.getenv("GSC_REFRESH_TOKEN")
SITE_URL      = "https://myhubon.com/"   # ← sc-domain: 형식이면 도메인만

if not all([CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN]):
    raise ValueError("GitHub Secrets에 GSC_CLIENT_ID / GSC_CLIENT_SECRET / GSC_REFRESH_TOKEN 이 없습니다.")

# ── 인증 ──────────────────────────────────────────────────
creds = Credentials(
    token=None,
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    refresh_token=REFRESH_TOKEN,
    token_uri="https://oauth2.googleapis.com/token",
)
service = build("webmasters", "v3", credentials=creds)

# ── 조회 기간: 최근 90일 ──────────────────────────────────
end_date   = datetime.utcnow().date() - timedelta(days=2)   # GSC는 2일 지연
start_date = end_date - timedelta(days=89)

# ────────────────────────────────────────────────────────────
# BUG #1 수정:
#   기존: dimensions=['date','query','page']
#         → 같은 날짜에 쿼리×페이지 조합만큼 row가 생겨
#           날짜별 합산이 아닌 쿼리별 쪼개진 값이 저장됨
#   수정: dimensions=['date'] 단독
#         → GSC가 서버에서 날짜별로 합산해서 반환
# ────────────────────────────────────────────────────────────
request_body = {
    "startDate": start_date.strftime("%Y-%m-%d"),
    "endDate":   end_date.strftime("%Y-%m-%d"),
    "dimensions": ["date"],          # ← 핵심 수정
    "rowLimit": 90,                  # 날짜 단독이면 최대 90행(90일)
}

response = service.searchanalytics().query(
    siteUrl=SITE_URL,
    body=request_body,
).execute()

# ── 파싱 ──────────────────────────────────────────────────
daily_data = []
for row in response.get("rows", []):
    daily_data.append({
        "date":   row["keys"][0],
        "clicks": int(row.get("clicks", 0)),
        "impr":   int(row.get("impressions", 0)),
        "ctr":    round(float(row.get("ctr", 0)), 4),
        "pos":    round(float(row.get("position", 0)), 1),
    })

# ────────────────────────────────────────────────────────────
# BUG #2 수정:
#   기존: daily_data[:500]  ← 슬라이싱으로 데이터 잘림
#   수정: 슬라이싱 제거, 날짜 오름차순 정렬
# ────────────────────────────────────────────────────────────
daily_data.sort(key=lambda r: r["date"])   # ← BUG #2+#3 수정

# ── 저장 ──────────────────────────────────────────────────
output = {
    "updated": datetime.utcnow().strftime("%Y-%m-%d"),
    "daily":   daily_data,           # 슬라이싱 없음
}

with open("gsc-data.json", "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

# ── 결과 출력 ─────────────────────────────────────────────
total_clicks = sum(r["clicks"] for r in daily_data)
total_impr   = sum(r["impr"]   for r in daily_data)
print(f"✅ GSC 데이터 수집 완료")
print(f"   기간: {start_date} ~ {end_date} ({len(daily_data)}일)")
print(f"   총 클릭: {total_clicks:,}  |  총 노출: {total_impr:,}")
print(f"   평균 CTR: {total_clicks/total_impr*100:.1f}%" if total_impr else "   (노출 없음)")
