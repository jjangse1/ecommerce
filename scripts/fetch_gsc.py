"""
fetch_gsc.py — Google Search Console 전체 데이터 수집
수집 항목:
  - daily         : 날짜별 클릭/노출/CTR/순위 (90일)
  - queries       : 인기 검색어 Top 20
  - countries     : 국가별 클릭/노출/CTR/순위 Top 15 (전체 기간 합계)
  - devices       : 기기별 클릭/노출/CTR/순위 (전체 기간 합계)
  - pages         : 인기 페이지 Top 15
  - daily_country : 날짜×국가별 일별 데이터 → 대시보드 날짜 필터 연동용
  - daily_device  : 날짜×기기별 일별 데이터 → 대시보드 날짜 필터 연동용
  - daily_query   : 날짜×검색어별 일별 데이터 → 대시보드 날짜 필터 연동용  ← 신규
  - daily_page    : 날짜×페이지별 일별 데이터 → 대시보드 날짜 필터 연동용  ← 신규
모든 항목이 gsc-data.json 에 저장되어 index.html 이 자동으로 읽습니다.
"""

import os
import json
import requests
from datetime import datetime, timedelta
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# ── 환경변수 (GitHub Secrets) ──────────────────────────────
CLIENT_ID     = os.getenv("GSC_CLIENT_ID")
CLIENT_SECRET = os.getenv("GSC_CLIENT_SECRET")
REFRESH_TOKEN = os.getenv("GSC_REFRESH_TOKEN")
SITE_URL      = "https://myhubon.com/"

if not all([CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN]):
    raise ValueError("GitHub Secrets에 GSC_CLIENT_ID / GSC_CLIENT_SECRET / GSC_REFRESH_TOKEN 이 없습니다.")

# ════════════════════════════════════════════════════════════
# 토큰 자동갱신: 매 실행마다 fresh access_token 발급 → 401 완전 차단
# Refresh Token 자체가 revoke됐다면 로컬에서 refresh_token.py 실행
# ════════════════════════════════════════════════════════════
def get_fresh_access_token():
    resp = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id":     CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "refresh_token": REFRESH_TOKEN,
            "grant_type":    "refresh_token",
        },
        timeout=30,
    )
    if resp.status_code != 200:
        raise RuntimeError(
            f"❌ 토큰 갱신 실패 ({resp.status_code}): {resp.text}\n"
            "→ Refresh Token이 revoke됐을 가능성이 있습니다.\n"
            "→ 로컬에서 refresh_token.py를 실행해 새 토큰을 발급받고\n"
            "  GitHub Secrets의 GSC_REFRESH_TOKEN 값을 업데이트하세요."
        )
    token_data = resp.json()
    print(f"✅ Access Token 갱신 성공 (유효: {token_data.get('expires_in', 3600)}초)")
    return token_data["access_token"]

# ── 인증 (매번 fresh access token 발급) ────────────────────
print("🔑 Access Token 갱신 중...")
access_token = get_fresh_access_token()
creds = Credentials(
    token=access_token,
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    refresh_token=REFRESH_TOKEN,
    token_uri="https://oauth2.googleapis.com/token",
)
service = build("webmasters", "v3", credentials=creds)

# ── 조회 기간: 최근 90일 (GSC 2일 지연) ───────────────────
end_date   = datetime.utcnow().date() - timedelta(days=2)
start_date = end_date - timedelta(days=89)
date_range = {
    "startDate": start_date.strftime("%Y-%m-%d"),
    "endDate":   end_date.strftime("%Y-%m-%d"),
}

# ── 공통 파싱 헬퍼 ───────────────────────────────────────
def parse_row(row, key_field):
    return {
        key_field: row["keys"][0],
        "clicks": int(row.get("clicks", 0)),
        "impr":   int(row.get("impressions", 0)),
        "ctr":    round(float(row.get("ctr", 0)), 4),
        "pos":    round(float(row.get("position", 0)), 1),
    }

def query_gsc(dimensions, row_limit=100, extra=None):
    body = {**date_range, "dimensions": dimensions, "rowLimit": row_limit}
    if extra:
        body.update(extra)
    return service.searchanalytics().query(siteUrl=SITE_URL, body=body).execute()

# 국가 코드 → 한국어 이름 매핑 (공통 사용)
COUNTRY_NAMES = {
    "kor":"한국","usa":"미국","jpn":"일본","chn":"중국","ind":"인도",
    "twn":"대만","sgp":"싱가포르","mys":"말레이시아","deu":"독일","gbr":"영국",
    "fra":"프랑스","aus":"호주","can":"캐나다","bra":"브라질","tha":"태국",
    "vnm":"베트남","idn":"인도네시아","phl":"필리핀","hkg":"홍콩","nld":"네덜란드",
    "ita":"이탈리아","esp":"스페인","mex":"멕시코","tur":"터키","sau":"사우디아라비아",
    "are":"UAE","rus":"러시아","pol":"폴란드","swe":"스웨덴","che":"스위스",
}

DEVICE_NAMES = {"DESKTOP":"데스크톱","MOBILE":"모바일","TABLET":"태블릿"}

# ════════════════════════════════════════════════════════════
# 1. 날짜별 집계 (90일)
# ════════════════════════════════════════════════════════════
print("📡 [1/9] 날짜별 데이터 수집 중...")
resp_daily = query_gsc(["date"], row_limit=90)
daily_data = [parse_row(r, "date") for r in resp_daily.get("rows", [])]
daily_data.sort(key=lambda r: r["date"])

# ════════════════════════════════════════════════════════════
# 2. 인기 검색어 Top 20
# ════════════════════════════════════════════════════════════
print("📡 [2/9] 검색어 데이터 수집 중...")
resp_queries = query_gsc(["query"], row_limit=20)
queries_data = [parse_row(r, "query") for r in resp_queries.get("rows", [])]
queries_data.sort(key=lambda r: r["clicks"], reverse=True)

# ════════════════════════════════════════════════════════════
# 3. 국가별 Top 15 (전체 기간 합계)
# ════════════════════════════════════════════════════════════
print("📡 [3/9] 국가별 데이터 수집 중...")
resp_countries = query_gsc(["country"], row_limit=15)
countries_data = []
for r in resp_countries.get("rows", []):
    code = r["keys"][0].lower()
    entry = parse_row(r, "country")
    entry["country"] = COUNTRY_NAMES.get(code, code.upper())
    entry["code"] = code
    countries_data.append(entry)
countries_data.sort(key=lambda r: r["clicks"], reverse=True)

# ════════════════════════════════════════════════════════════
# 4. 기기별 (전체 기간 합계)
# ════════════════════════════════════════════════════════════
print("📡 [4/9] 기기별 데이터 수집 중...")
resp_devices = query_gsc(["device"], row_limit=10)
devices_data = []
for r in resp_devices.get("rows", []):
    raw = r["keys"][0].upper()
    entry = parse_row(r, "device")
    entry["device"] = DEVICE_NAMES.get(raw, raw)
    devices_data.append(entry)
devices_data.sort(key=lambda r: r["clicks"], reverse=True)

# ════════════════════════════════════════════════════════════
# 5. 인기 페이지 Top 15
# ════════════════════════════════════════════════════════════
print("📡 [5/9] 페이지별 데이터 수집 중...")
resp_pages = query_gsc(["page"], row_limit=15)
pages_data = [parse_row(r, "page") for r in resp_pages.get("rows", [])]
pages_data.sort(key=lambda r: r["clicks"], reverse=True)

# ════════════════════════════════════════════════════════════
# 6. 날짜×국가 (daily_country) — 대시보드 날짜 필터 연동용
#    90일 × 최대 15개국 = 최대 1,350행 → rowLimit 2000으로 여유있게
# ════════════════════════════════════════════════════════════
print("📡 [6/9] 날짜×국가 일별 데이터 수집 중...")
resp_dc = query_gsc(["date", "country"], row_limit=2000)
daily_country = []
for r in resp_dc.get("rows", []):
    date_val = r["keys"][0]
    code     = r["keys"][1].lower()
    daily_country.append({
        "date":    date_val,
        "country": COUNTRY_NAMES.get(code, code.upper()),
        "code":    code,
        "clicks":  int(r.get("clicks", 0)),
        "impr":    int(r.get("impressions", 0)),
        "ctr":     round(float(r.get("ctr", 0)), 4),
        "pos":     round(float(r.get("position", 0)), 1),
    })
daily_country.sort(key=lambda r: (r["date"], r["country"]))

# ════════════════════════════════════════════════════════════
# 7. 날짜×기기 (daily_device) — 대시보드 날짜 필터 연동용
#    90일 × 3기기 = 최대 270행
# ════════════════════════════════════════════════════════════
print("📡 [7/9] 날짜×기기 일별 데이터 수집 중...")
resp_dd = query_gsc(["date", "device"], row_limit=500)
daily_device = []
for r in resp_dd.get("rows", []):
    date_val = r["keys"][0]
    raw      = r["keys"][1].upper()
    daily_device.append({
        "date":   date_val,
        "device": DEVICE_NAMES.get(raw, raw),
        "clicks": int(r.get("clicks", 0)),
        "impr":   int(r.get("impressions", 0)),
        "ctr":    round(float(r.get("ctr", 0)), 4),
        "pos":    round(float(r.get("position", 0)), 1),
    })
daily_device.sort(key=lambda r: (r["date"], r["device"]))

# ════════════════════════════════════════════════════════════
# 8. 날짜×검색어 (daily_query) — 대시보드 날짜 필터 연동용  ← 신규
#    90일 × Top 20 검색어 = 최대 1,800행
#    rowLimit 5000으로 넉넉하게 (GSC API 최대 25,000)
# ════════════════════════════════════════════════════════════
print("📡 [8/9] 날짜×검색어 일별 데이터 수집 중...")
resp_dq = query_gsc(["date", "query"], row_limit=5000)
daily_query = []
for r in resp_dq.get("rows", []):
    date_val = r["keys"][0]
    query_val = r["keys"][1]
    daily_query.append({
        "date":   date_val,
        "query":  query_val,
        "clicks": int(r.get("clicks", 0)),
        "impr":   int(r.get("impressions", 0)),
        "ctr":    round(float(r.get("ctr", 0)), 4),
        "pos":    round(float(r.get("position", 0)), 1),
    })
daily_query.sort(key=lambda r: (r["date"], r["query"]))

# ════════════════════════════════════════════════════════════
# 9. 날짜×페이지 (daily_page) — 대시보드 날짜 필터 연동용  ← 신규
#    90일 × Top 15 페이지 = 최대 1,350행
# ════════════════════════════════════════════════════════════
print("📡 [9/9] 날짜×페이지 일별 데이터 수집 중...")
resp_dp = query_gsc(["date", "page"], row_limit=5000)
daily_page = []
for r in resp_dp.get("rows", []):
    date_val = r["keys"][0]
    page_val = r["keys"][1]
    daily_page.append({
        "date":   date_val,
        "page":   page_val,
        "clicks": int(r.get("clicks", 0)),
        "impr":   int(r.get("impressions", 0)),
        "ctr":    round(float(r.get("ctr", 0)), 4),
        "pos":    round(float(r.get("position", 0)), 1),
    })
daily_page.sort(key=lambda r: (r["date"], r["page"]))

# ════════════════════════════════════════════════════════════
# 저장
# ════════════════════════════════════════════════════════════
output = {
    "updated": datetime.utcnow().strftime("%Y-%m-%d"),
    "period": {
        "start": start_date.strftime("%Y-%m-%d"),
        "end":   end_date.strftime("%Y-%m-%d"),
    },
    "daily":         daily_data,
    "queries":       queries_data,
    "countries":     countries_data,
    "devices":       devices_data,
    "pages":         pages_data,
    "daily_country": daily_country,
    "daily_device":  daily_device,
    "daily_query":   daily_query,   # ← 신규
    "daily_page":    daily_page,    # ← 신규
}

with open("gsc-data.json", "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

# ── 결과 요약 출력 ───────────────────────────────────────
total_clicks = sum(r["clicks"] for r in daily_data)
total_impr   = sum(r["impr"]   for r in daily_data)
print(f"\n✅ GSC 데이터 수집 완료")
print(f"   기간             : {start_date} ~ {end_date} ({len(daily_data)}일)")
print(f"   총 클릭          : {total_clicks:,}  |  총 노출: {total_impr:,}")
if total_impr:
    print(f"   평균 CTR         : {total_clicks/total_impr*100:.1f}%")
print(f"   검색어           : {len(queries_data)}개")
print(f"   국가             : {len(countries_data)}개")
print(f"   기기             : {len(devices_data)}개")
print(f"   페이지           : {len(pages_data)}개")
print(f"   날짜×국가 행수   : {len(daily_country)}행")
print(f"   날짜×기기 행수   : {len(daily_device)}행")
print(f"   날짜×검색어 행수 : {len(daily_query)}행")   # ← 신규
print(f"   날짜×페이지 행수 : {len(daily_page)}행")    # ← 신규
print(f"   저장 완료        : gsc-data.json")
