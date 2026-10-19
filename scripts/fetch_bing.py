"""
fetch_bing.py — Bing Webmaster Tools API 데이터 수집 (v2)
수집 항목:
  - daily    : 날짜별 클릭/노출/CTR/순위 (최근 90일)
  - queries  : 인기 검색어 Top 15 (최근 90일 전체 기준 · 폴백용)
  - pages    : 인기 페이지 Top 15 (최근 90일 전체 기준 · 폴백용)
  - query_daily / page_daily : 검색어·페이지 "일자별" 원본 행 → 대시보드가 선택한 기간으로
                               직접 합산해서 Top 15를 다시 계산함 (날짜 필터 연동)
  - query_page_daily / page_query_daily : 드릴다운도 일자별 행으로 저장 (기간 연동)
  - countries / daily_country : Bing API 미지원으로 항상 빈 배열 (아래 설명 참고)

── v2에서 바뀐 점 (중요) ─────────────────────────────────────
Bing Webmaster API 공식 WSDL(https://ssl.bing.com/webmasterapi/api.svc?singleWsdl)
기준으로 실제 존재하는 메소드와 응답 필드명을 다시 확인해서 아래 버그를 고침:

  1. 인기 검색어가 안 보이던 문제
     → GetKeywordStats는 사이트의 검색어 실적 API가 아니라 "키워드 리서치" API로,
       필수 파라미터가 siteUrl이 아니라 q(키워드)/country/language 임.
       사이트 자체 검색어 실적은 GetQueryStats(siteUrl)를 써야 함.

  2. 인기 페이지 링크가 비어있던 문제
     → GetPageStats 응답에는 "Url" 필드가 없음. 페이지 URL은 "Query" 필드에 담겨서 옴
       (GetQueryStats와 응답 타입 자체가 동일한 QueryStats 클래스라서 그럼).

  3. 평균 순위가 항상 0.0위였던 문제
     → 응답 필드명이 "AvgRank"가 아니라 "AvgClickPosition" / "AvgImpressionPosition" 임.

  4. 국가별 비교에서 Bing 데이터가 전혀 안 보이던 문제
     → "GetCountryStats"는 Bing Webmaster API에 존재하지 않는 엔드포인트입니다.
       공식 API는 국가별 트래픽 통계를 전혀 제공하지 않습니다(Bing 포털 화면에서만
       수동 확인 가능). 그래서 이 스크립트는 countries/daily_country를 항상 빈
       배열로 저장하고, output json에 "country_supported": false 플래그를 남깁니다.
       (프론트엔드에서 이 플래그를 보고 "Bing 국가 데이터 미지원" 안내를 표시하도록
       index.html도 같이 수정했습니다.)

  5. GetQueryStats / GetPageStats / GetRankAndTrafficStats는 파라미터가 siteUrl
     하나뿐이라 startDate/endDate를 넘겨도 무시됩니다. Bing이 보유한 전체 이력을
     한 번에 받아온 뒤, 우리가 원하는 최근 90일만 클라이언트에서 걸러냅니다.
     (매일 1건씩 90번 호출하던 기존 방식보다 API 호출 수도 훨씬 적어짐)
"""

import os
import re
import json
import time
import requests
from collections import defaultdict
from datetime import datetime, timedelta

# ── 환경변수 (GitHub Secrets) ──────────────────────────────
BING_API_KEY = os.getenv("BING_API_KEY")
SITE_URL     = "https://myhubon.com/"   # Bing WMT에 등록된 URL 그대로

if not BING_API_KEY:
    raise ValueError("GitHub Secrets에 BING_API_KEY 가 없습니다.")

BASE_URL = "https://ssl.bing.com/webmaster/api.svc/json"
HEADERS  = {"Content-Type": "application/json; charset=utf-8"}

TOP_N        = 15   # 대시보드 표시 개수
DRILL_QUERIES = 150 # 드릴다운(검색어→페이지)을 받아둘 검색어 수 (90일 클릭 상위, 클릭 0 제외)
DRILL_PAGES   = 150 # 드릴다운(페이지→검색어)을 받아둘 페이지 수 (90일 클릭 상위, 클릭 0 제외)
DRILL_SLEEP   = 0.25 # 드릴다운 호출 사이 대기(초) — 레이트리밋으로 빈 응답이 오는 것 방지

# ── 조회 기간: 최근 90일 ───────────────────────────────────
end_date   = datetime.utcnow().date() - timedelta(days=2)
start_date = end_date - timedelta(days=89)

def fmt(d): return d.strftime("%Y-%m-%d")

print(f"📅 조회 기간: {fmt(start_date)} ~ {fmt(end_date)}")

# ── 응답에서 결과 리스트 안전하게 추출 ──────────────────────
# Bing WMT API는 엔드포인트에 따라 응답 형태가 제각각임:
#   {"d": {"Results": [...]}}  ← 일부
#   {"d": [...]}               ← 다른 엔드포인트 (Results 래핑 없음)
#   {"Results": [...]}         ← "d" 자체가 없는 경우
#   [...]                      ← 최상위가 바로 리스트인 경우
def extract_rows(data):
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    if "d" in data:
        d_val = data["d"]
        if isinstance(d_val, list):
            return d_val
        if isinstance(d_val, dict):
            return d_val.get("Results", [])
        return []
    return data.get("Results", [])

# ── 공통 GET 헬퍼 (재시도 포함) ───────────────────────────
# 마지막 호출 결과 상태: "ok" / "empty" / "error"  (드릴다운 누락 원인 진단용)
last_status = "ok"

def bing_get(endpoint, params=None, retries=3):
    global last_status
    p = {"apikey": BING_API_KEY}
    if params:
        p.update(params)
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(f"{BASE_URL}/{endpoint}", headers=HEADERS, params=p, timeout=30)
        except requests.RequestException as e:
            print(f"  ⚠ {endpoint} 요청 실패({attempt}/{retries}): {e}")
            time.sleep(1.5 * attempt)
            continue
        if resp.status_code in (429, 500, 502, 503, 504):
            print(f"  ⚠ {endpoint} 일시 오류 {resp.status_code} ({attempt}/{retries}) → 재시도")
            time.sleep(1.5 * attempt)
            continue
        if resp.status_code != 200:
            print(f"  ⚠ {endpoint} 실패 ({resp.status_code}): {resp.text[:200]}")
            last_status = "error"
            return []
        try:
            data = resp.json()
        except ValueError:
            print(f"  ⚠ {endpoint} JSON 파싱 실패: {resp.text[:200]}")
            last_status = "error"
            return []
        rows = extract_rows(data)
        last_status = "ok" if rows else "empty"
        return rows
    last_status = "error"
    return []

# ── Bing의 "/Date(1699999999000)/" 형식 파싱 ────────────────
_DATE_RE = re.compile(r"/Date\((-?\d+)")
def parse_bing_date(raw):
    if not raw:
        return None
    m = _DATE_RE.search(raw)
    if not m:
        return None
    ms = int(m.group(1))
    return datetime.utcfromtimestamp(ms / 1000).strftime("%Y-%m-%d")

def in_range(d):
    return d is not None and fmt(start_date) <= d <= fmt(end_date)

# ════════════════════════════════════════════════════════════
# 1. 날짜별 사이트 전체 트래픽 (GetRankAndTrafficStats)
#    필드: Clicks, Date, Impressions  (순위/포지션 필드는 없음)
# ════════════════════════════════════════════════════════════
print("📡 [1/6] 날짜별 사이트 트래픽 (GetRankAndTrafficStats)...")
raw_traffic = bing_get("GetRankAndTrafficStats", {"siteUrl": SITE_URL})
traffic_by_date = {}
for r in raw_traffic:
    d = parse_bing_date(r.get("Date"))
    if not in_range(d):
        continue
    traffic_by_date[d] = {
        "clicks": int(r.get("Clicks", 0) or 0),
        "impr":   int(r.get("Impressions", 0) or 0),
    }

# ════════════════════════════════════════════════════════════
# 2. 검색어별 트래픽 (GetQueryStats)
#    필드: AvgClickPosition, AvgImpressionPosition, Clicks, Date, Impressions, Query
#    → 일자별 순위 계산 + 인기 검색어 Top 20 둘 다 이 데이터에서 뽑아냄
# ════════════════════════════════════════════════════════════
print("📡 [2/6] 검색어별 트래픽 (GetQueryStats)...")
raw_queries_all = bing_get("GetQueryStats", {"siteUrl": SITE_URL})
q_rows = []
for r in raw_queries_all:
    d = parse_bing_date(r.get("Date"))
    if not in_range(d):
        continue
    q_rows.append({
        "date":   d,
        "query":  r.get("Query", "") or "",
        "clicks": int(r.get("Clicks", 0) or 0),
        "impr":   int(r.get("Impressions", 0) or 0),
        "pos":    float(r.get("AvgImpressionPosition", 0) or 0),
    })

# 날짜별 노출 가중평균 순위 계산 (GetRankAndTrafficStats엔 순위가 없어서 여기서 보충)
pos_by_date = defaultdict(lambda: [0.0, 0])  # date -> [sum(pos*impr), sum(impr)]
for q in q_rows:
    if q["impr"] > 0:
        pos_by_date[q["date"]][0] += q["pos"] * q["impr"]
        pos_by_date[q["date"]][1] += q["impr"]

daily_data = []
cur = start_date
while cur <= end_date:
    ds = fmt(cur)
    t = traffic_by_date.get(ds, {"clicks": 0, "impr": 0})
    pa = pos_by_date.get(ds, [0.0, 0])
    pos = round(pa[0] / pa[1], 1) if pa[1] else 0
    daily_data.append({
        "date":   ds,
        "clicks": t["clicks"],
        "impr":   t["impr"],
        "ctr":    round(t["clicks"] / t["impr"], 4) if t["impr"] else 0,
        "pos":    pos,
    })
    cur += timedelta(days=1)

# 인기 검색어 Top 20 (검색어별로 합산)
q_agg = defaultdict(lambda: [0, 0, 0.0, 0])  # clicks, impr, pos*impr합, impr합(pos용)
for q in q_rows:
    if not q["query"]:
        continue
    a = q_agg[q["query"]]
    a[0] += q["clicks"]
    a[1] += q["impr"]
    if q["impr"] > 0:
        a[2] += q["pos"] * q["impr"]
        a[3] += q["impr"]

queries_data = []
for query, (clicks, impr, pos_sum, pos_impr) in q_agg.items():
    queries_data.append({
        "query":  query,
        "clicks": clicks,
        "impr":   impr,
        "ctr":    round(clicks / impr, 4) if impr else 0,
        "pos":    round(pos_sum / pos_impr, 1) if pos_impr else 0,
    })
queries_data.sort(key=lambda r: r["clicks"], reverse=True)
queries_all  = queries_data            # 드릴다운 대상 선정용 (전체)
queries_data = queries_data[:TOP_N]    # 폴백용 Top 15

# 일자별 원본 행 (프론트가 기간 필터로 재합산): [날짜, 검색어, 클릭, 노출, 순위]
query_daily = [[q["date"], q["query"], q["clicks"], q["impr"], round(q["pos"], 1)]
               for q in q_rows if q["query"] and (q["clicks"] or q["impr"])]

# ════════════════════════════════════════════════════════════
# 3. 페이지별 트래픽 (GetPageStats)
#    ⚠ URL은 "Url"이 아니라 "Query" 필드에 담겨서 옴 (GetQueryStats와 동일한 응답 타입)
# ════════════════════════════════════════════════════════════
print("📡 [3/6] 페이지별 트래픽 (GetPageStats)...")
raw_pages_all = bing_get("GetPageStats", {"siteUrl": SITE_URL})
p_agg = defaultdict(lambda: [0, 0, 0.0, 0])
page_daily = []   # [날짜, 페이지URL, 클릭, 노출, 순위]
for r in raw_pages_all:
    d = parse_bing_date(r.get("Date"))
    if not in_range(d):
        continue
    url = r.get("Query", "") or ""  # 페이지 URL이 Query 필드에 옴
    if not url:
        continue
    clicks = int(r.get("Clicks", 0) or 0)
    impr   = int(r.get("Impressions", 0) or 0)
    pos    = float(r.get("AvgImpressionPosition", 0) or 0)
    if clicks or impr:
        page_daily.append([d, url, clicks, impr, round(pos, 1)])
    a = p_agg[url]
    a[0] += clicks
    a[1] += impr
    if impr > 0:
        a[2] += pos * impr
        a[3] += impr

pages_data = []
for url, (clicks, impr, pos_sum, pos_impr) in p_agg.items():
    pages_data.append({
        "page":   url,
        "clicks": clicks,
        "impr":   impr,
        "ctr":    round(clicks / impr, 4) if impr else 0,
        "pos":    round(pos_sum / pos_impr, 1) if pos_impr else 0,
    })
pages_data.sort(key=lambda r: r["clicks"], reverse=True)
pages_all  = pages_data
pages_data = pages_data[:TOP_N]

# ════════════════════════════════════════════════════════════
# 5. 검색어 → 페이지 드릴다운 (GetQueryPageStats)
#    90일 클릭 상위 DRILL_QUERIES개 검색어에 대해 "일자별" 행을 저장
#    (기간을 바꿔도 프론트에서 해당 기간만 다시 합산할 수 있도록)
#    ⚠ 응답은 GetPageStats와 같은 QueryStats 타입이라 페이지 URL이 "Query" 필드에 담김
# ════════════════════════════════════════════════════════════
print("📡 [4/6] 검색어→페이지 드릴다운 (GetQueryPageStats)...")
query_page_daily = {}
diag_q = {"error": [], "empty": [], "out_of_range": []}
for q in [x for x in queries_all if x["clicks"] > 0][:DRILL_QUERIES]:
    qtext = q["query"]
    rows = bing_get("GetQueryPageStats", {"siteUrl": SITE_URL, "query": qtext})
    status = last_status
    time.sleep(DRILL_SLEEP)
    items = []
    for r in rows:
        d = parse_bing_date(r.get("Date"))
        if not in_range(d):
            continue
        url = r.get("Query", "") or ""  # 페이지 URL이 Query 필드에 옴
        if not url:
            continue
        clicks = int(r.get("Clicks", 0) or 0)
        impr   = int(r.get("Impressions", 0) or 0)
        if clicks or impr:
            items.append([d, url, clicks, impr])
    if items:
        query_page_daily[qtext] = items
    elif status == "error":
        diag_q["error"].append(qtext)
    elif status == "empty":
        diag_q["empty"].append(qtext)      # Bing가 이 검색어의 페이지 상세를 아예 안 줌
    else:
        diag_q["out_of_range"].append(qtext)  # 응답은 있었지만 조회 기간 밖 날짜뿐

# ════════════════════════════════════════════════════════════
# 6. 페이지 → 검색어 드릴다운 (GetPageQueryStats)
#    90일 클릭 상위 DRILL_PAGES개 페이지에 대해 "일자별" 행을 저장
# ════════════════════════════════════════════════════════════
print("📡 [5/6] 페이지→검색어 드릴다운 (GetPageQueryStats)...")
page_query_daily = {}
diag_p = {"error": [], "empty": [], "out_of_range": []}
for p in [x for x in pages_all if x["clicks"] > 0][:DRILL_PAGES]:
    purl = p["page"]
    rows = bing_get("GetPageQueryStats", {"siteUrl": SITE_URL, "page": purl})
    status = last_status
    time.sleep(DRILL_SLEEP)
    items = []
    for r in rows:
        d = parse_bing_date(r.get("Date"))
        if not in_range(d):
            continue
        qtext = r.get("Query", "") or ""
        if not qtext:
            continue
        clicks = int(r.get("Clicks", 0) or 0)
        impr   = int(r.get("Impressions", 0) or 0)
        if clicks or impr:
            items.append([d, qtext, clicks, impr])
    if items:
        page_query_daily[purl] = items
    elif status == "error":
        diag_p["error"].append(purl)
    elif status == "empty":
        diag_p["empty"].append(purl)
    else:
        diag_p["out_of_range"].append(purl)

def print_diag(title, diag, total):
    print(f"  ▶ {title}: 대상 {total}개 → 상세 없음 {sum(len(v) for v in diag.values())}개")
    print(f"      API 오류/재시도 실패 : {len(diag['error'])}개  (→ 다시 실행하면 채워질 수 있음)")
    print(f"      Bing 빈 응답         : {len(diag['empty'])}개  (→ Bing이 상세 데이터를 제공하지 않음)")
    print(f"      기간 밖 데이터만     : {len(diag['out_of_range'])}개")
    for k in ("error", "empty"):
        for x in diag[k][:5]:
            print(f"        - [{k}] {x[:80]}")
print("🔎 드릴다운 누락 진단")
print_diag("검색어→페이지", diag_q, min(DRILL_QUERIES, len([x for x in queries_all if x['clicks'] > 0])))
print_diag("페이지→검색어", diag_p, min(DRILL_PAGES, len([x for x in pages_all if x['clicks'] > 0])))

# ════════════════════════════════════════════════════════════
# 4. 국가별 데이터 — Bing Webmaster API 공식 미지원
#    "GetCountryStats"는 실제 존재하는 엔드포인트가 아님(WSDL에 없음).
#    Bing은 국가별 트래픽을 API로 전혀 제공하지 않으므로 빈 배열로 저장하고
#    프론트엔드가 이를 구분할 수 있도록 country_supported 플래그를 남긴다.
# ════════════════════════════════════════════════════════════
print("📡 [6/6] 국가별 데이터...")
print("  ⚠ Bing Webmaster API는 국가별 트래픽 통계 엔드포인트를 제공하지 않습니다.")
print("    (GetCountryStats는 공식 API에 존재하지 않음) → countries/daily_country는 빈 배열로 저장")
countries_data = []
daily_country  = []
country_supported = False

# ════════════════════════════════════════════════════════════
# 저장
# ════════════════════════════════════════════════════════════
output = {
    "updated": datetime.utcnow().strftime("%Y-%m-%d"),
    "period":  {"start": fmt(start_date), "end": fmt(end_date)},
    "daily":                 daily_data,
    "queries":               queries_data,
    "pages":                 pages_data,
    "countries":             countries_data,
    "daily_country":         daily_country,
    "country_supported":     country_supported,
    "query_daily":           query_daily,
    "page_daily":            page_daily,
    "query_page_daily":      query_page_daily,
    "page_query_daily":      page_query_daily,
    "drill_missing": {     # 드릴다운이 비어있는 항목과 사유 (프론트 안내 문구용)
        "queries": {k: v for k, v in diag_q.items()},
        "pages":   {k: v for k, v in diag_p.items()},
    },
}

# 일자별 행이 많아 indent 없이 compact하게 저장 (파일 크기 절약)
with open("bing-data.json", "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, separators=(",", ":"))

total_clicks = sum(r["clicks"] for r in daily_data)
total_impr   = sum(r["impr"]   for r in daily_data)
print(f"\n✅ bing-data.json 저장 완료")
print(f"   기간     : {fmt(start_date)} ~ {fmt(end_date)} ({len(daily_data)}일)")
print(f"   총 클릭  : {total_clicks:,}  |  총 노출: {total_impr:,}")
if total_impr: print(f"   평균 CTR : {total_clicks/total_impr*100:.1f}%")
print(f"   검색어   : {len(queries_data)}개")
print(f"   페이지   : {len(pages_data)}개")
print(f"   검색어 일자별 행 : {len(query_daily)}건 / 페이지 일자별 행 : {len(page_daily)}건")
print(f"   검색어→페이지 드릴다운 : {len(query_page_daily)}개 검색어")
print(f"   페이지→검색어 드릴다운 : {len(page_query_daily)}개 페이지")
print(f"   국가     : 미지원 (Bing API 자체 미제공)")
