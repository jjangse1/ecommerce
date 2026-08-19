"""
fetch_bing.py — Bing Webmaster Tools API 데이터 수집
수집 항목:
  - daily    : 날짜별 클릭/노출/CTR/순위 (최근 90일)
  - queries  : 인기 검색어 Top 20
  - pages    : 인기 페이지 Top 15
  - countries: 국가별 클릭/노출 Top 10
  - daily_country: 날짜×국가 (날짜 필터 연동용)

Bing WMT API 문서:
  https://docs.microsoft.com/en-us/dotnet/api/microsoft.bing.webmaster.api
  Base URL: https://ssl.bing.com/webmaster/api.svc/json/
"""

import os
import json
import requests
from datetime import datetime, timedelta

# ── 환경변수 (GitHub Secrets) ──────────────────────────────
BING_API_KEY = os.getenv("BING_API_KEY")
SITE_URL     = "https://myhubon.com/"   # Bing WMT에 등록된 URL 그대로

if not BING_API_KEY:
    raise ValueError("GitHub Secrets에 BING_API_KEY 가 없습니다.")

BASE_URL = "https://ssl.bing.com/webmaster/api.svc/json"
HEADERS  = {"Content-Type": "application/json; charset=utf-8"}

# ── 조회 기간: 최근 90일 ───────────────────────────────────
end_date   = datetime.utcnow().date() - timedelta(days=2)
start_date = end_date - timedelta(days=89)

def fmt(d): return d.strftime("%Y-%m-%d")

print(f"📅 조회 기간: {fmt(start_date)} ~ {fmt(end_date)}")

# ── 공통 GET 헬퍼 ─────────────────────────────────────────
def bing_get(endpoint, params=None):
    p = {"apikey": BING_API_KEY}
    if params:
        p.update(params)
    resp = requests.get(f"{BASE_URL}/{endpoint}", headers=HEADERS, params=p, timeout=30)
    if resp.status_code != 200:
        print(f"  ⚠ {endpoint} 실패 ({resp.status_code}): {resp.text[:200]}")
        return {}
    return resp.json()

# ── 공통 POST 헬퍼 ────────────────────────────────────────
def bing_post(endpoint, payload):
    params = {"apikey": BING_API_KEY}
    resp = requests.post(
        f"{BASE_URL}/{endpoint}",
        headers=HEADERS,
        params=params,
        json=payload,
        timeout=30,
    )
    if resp.status_code != 200:
        print(f"  ⚠ {endpoint} 실패 ({resp.status_code}): {resp.text[:200]}")
        return {}
    return resp.json()

# ════════════════════════════════════════════════════════════
# 1. 날짜별 트래픽 (GetRankAndTrafficStats)
#    Bing은 날짜별로 1건씩 반환
# ════════════════════════════════════════════════════════════
print("📡 [1/5] 날짜별 클릭·노출...")
daily_data = []
cur = start_date
while cur <= end_date:
    data = bing_get("GetRankAndTrafficStats", {
        "siteUrl":   SITE_URL,
        "startDate": fmt(cur),
        "endDate":   fmt(cur),
    })
    rows = data.get("d", {}).get("Results", []) if "d" in data else data.get("Results", [])
    for r in rows:
        try:
            daily_data.append({
                "date":   cur.strftime("%Y-%m-%d"),
                "clicks": int(r.get("Clicks", 0)),
                "impr":   int(r.get("Impressions", 0)),
                "ctr":    round(float(r.get("Ctr", 0)), 4),
                "pos":    round(float(r.get("AvgRank", 0)), 1),
            })
        except Exception:
            pass
    cur += timedelta(days=1)

# 날짜별 단일 호출이 느릴 경우를 위한 대안: GetQueryStats (전체 기간 집계)
# 위에서 daily_data가 비어있으면 bulk로 재시도
if not daily_data:
    print("  → 날짜별 단건 실패, bulk GetQueryStats 시도...")
    data = bing_get("GetQueryStats", {
        "siteUrl":   SITE_URL,
        "startDate": fmt(start_date),
        "endDate":   fmt(end_date),
        "granularity": "Day",
    })
    rows = data.get("d", {}).get("Results", []) if "d" in data else data.get("Results", [])
    for r in rows:
        try:
            daily_data.append({
                "date":   r.get("Date", "")[:10],
                "clicks": int(r.get("Clicks", 0)),
                "impr":   int(r.get("Impressions", 0)),
                "ctr":    round(float(r.get("Ctr", 0)), 4),
                "pos":    round(float(r.get("AvgRank", 0)), 1),
            })
        except Exception:
            pass

daily_data = [d for d in daily_data if d["date"]]
daily_data.sort(key=lambda r: r["date"])

# ════════════════════════════════════════════════════════════
# 2. 인기 검색어 Top 20 (GetKeywordStats)
# ════════════════════════════════════════════════════════════
print("📡 [2/5] 인기 검색어...")
data = bing_get("GetKeywordStats", {
    "siteUrl":   SITE_URL,
    "startDate": fmt(start_date),
    "endDate":   fmt(end_date),
})
raw_queries = data.get("d", {}).get("Results", []) if "d" in data else data.get("Results", [])
queries_data = []
for r in raw_queries[:20]:
    try:
        queries_data.append({
            "query":  r.get("Query", ""),
            "clicks": int(r.get("Clicks", 0)),
            "impr":   int(r.get("Impressions", 0)),
            "ctr":    round(float(r.get("Ctr", 0)), 4),
            "pos":    round(float(r.get("AvgRank", 0)), 1),
        })
    except Exception:
        pass
queries_data.sort(key=lambda r: r["clicks"], reverse=True)

# ════════════════════════════════════════════════════════════
# 3. 인기 페이지 Top 15 (GetPageStats)
# ════════════════════════════════════════════════════════════
print("📡 [3/5] 인기 페이지...")
data = bing_get("GetPageStats", {
    "siteUrl":   SITE_URL,
    "startDate": fmt(start_date),
    "endDate":   fmt(end_date),
})
raw_pages = data.get("d", {}).get("Results", []) if "d" in data else data.get("Results", [])
pages_data = []
for r in raw_pages[:15]:
    try:
        pages_data.append({
            "page":   r.get("Url", ""),
            "clicks": int(r.get("Clicks", 0)),
            "impr":   int(r.get("Impressions", 0)),
            "ctr":    round(float(r.get("Ctr", 0)), 4),
            "pos":    round(float(r.get("AvgRank", 0)), 1),
        })
    except Exception:
        pass
pages_data.sort(key=lambda r: r["clicks"], reverse=True)

# ════════════════════════════════════════════════════════════
# 4. 국가별 Top 10 (GetCountryStats)
# ════════════════════════════════════════════════════════════
print("📡 [4/5] 국가별...")

COUNTRY_NAMES = {
    "KR":"한국","US":"미국","JP":"일본","CN":"중국","IN":"인도",
    "TW":"대만","SG":"싱가포르","MY":"말레이시아","DE":"독일","GB":"영국",
    "FR":"프랑스","AU":"호주","CA":"캐나다","BR":"브라질","TH":"태국",
    "VN":"베트남","ID":"인도네시아","PH":"필리핀","HK":"홍콩","NL":"네덜란드",
}
data = bing_get("GetCountryStats", {
    "siteUrl":   SITE_URL,
    "startDate": fmt(start_date),
    "endDate":   fmt(end_date),
})
raw_countries = data.get("d", {}).get("Results", []) if "d" in data else data.get("Results", [])
countries_data = []
for r in raw_countries[:10]:
    try:
        code = r.get("CountryCode", "").upper()
        countries_data.append({
            "country": COUNTRY_NAMES.get(code, code),
            "code":    code.lower(),
            "clicks":  int(r.get("Clicks", 0)),
            "impr":    int(r.get("Impressions", 0)),
            "ctr":     round(float(r.get("Ctr", 0)), 4),
            "pos":     round(float(r.get("AvgRank", 0)), 1),
        })
    except Exception:
        pass
countries_data.sort(key=lambda r: r["clicks"], reverse=True)

# ════════════════════════════════════════════════════════════
# 5. 날짜×국가 (날짜 필터 연동 — Top 5 국가)
#    Bing은 날짜×국가 교차 API가 없으므로 국가별 일별 루프
# ════════════════════════════════════════════════════════════
print("📡 [5/5] 날짜×국가...")
top_codes = [c["code"].upper() for c in countries_data[:5]]
daily_country = []
for code in top_codes:
    data = bing_get("GetCountryStats", {
        "siteUrl":     SITE_URL,
        "startDate":   fmt(start_date),
        "endDate":     fmt(end_date),
        "countryCode": code,
        "granularity": "Day",
    })
    rows = data.get("d", {}).get("Results", []) if "d" in data else data.get("Results", [])
    for r in rows:
        try:
            daily_country.append({
                "date":    r.get("Date", "")[:10],
                "country": COUNTRY_NAMES.get(code, code),
                "clicks":  int(r.get("Clicks", 0)),
                "impr":    int(r.get("Impressions", 0)),
                "ctr":     round(float(r.get("Ctr", 0)), 4),
                "pos":     round(float(r.get("AvgRank", 0)), 1),
            })
        except Exception:
            pass
daily_country = [d for d in daily_country if d["date"]]
daily_country.sort(key=lambda r: (r["date"], r["country"]))

# ════════════════════════════════════════════════════════════
# 저장
# ════════════════════════════════════════════════════════════
output = {
    "updated": datetime.utcnow().strftime("%Y-%m-%d"),
    "period":  {"start": fmt(start_date), "end": fmt(end_date)},
    "daily":         daily_data,
    "queries":       queries_data,
    "pages":         pages_data,
    "countries":     countries_data,
    "daily_country": daily_country,
}

with open("bing-data.json", "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

total_clicks = sum(r["clicks"] for r in daily_data)
total_impr   = sum(r["impr"]   for r in daily_data)
print(f"\n✅ bing-data.json 저장 완료")
print(f"   기간     : {fmt(start_date)} ~ {fmt(end_date)} ({len(daily_data)}일)")
print(f"   총 클릭  : {total_clicks:,}  |  총 노출: {total_impr:,}")
if total_impr: print(f"   평균 CTR : {total_clicks/total_impr*100:.1f}%")
print(f"   검색어   : {len(queries_data)}개")
print(f"   페이지   : {len(pages_data)}개")
print(f"   국가     : {len(countries_data)}개")
