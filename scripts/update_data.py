import os
import json
import requests
import subprocess
import time
from datetime import datetime, timezone, timedelta

# ====================== 설정 ======================
os.chdir(os.getenv('GITHUB_WORKSPACE', '.'))

DATA_DIR    = "scripts"
DATA_FILE   = os.path.join(DATA_DIR, "data.xlsx")
TEMP_FILE   = os.path.join(DATA_DIR, "temp_new.xlsx")
MERGED_FILE = os.path.join(DATA_DIR, "merged.xlsx")
STATE_FILE  = os.path.join(DATA_DIR, "last_sync.json")

CHUNK_DAYS     = 7   # API 1회 요청당 조회 기간(기존 로직과 동일하게 유지)
BOOTSTRAP_DAYS = 7   # 상태 파일이 전혀 없는 최초 실행 시 조회 기간

EMAIL    = os.getenv('MYHUBON_EMAIL')
PASSWORD = os.getenv('MYHUBON_PASSWORD')

# 수동 백필용: 워크플로우 실행 시 이 값을 'YYYY-MM-DD' 형태로 넣으면
# 마지막 동기화 기록을 무시하고 해당 날짜부터 강제로 다시 수집한다.
# 예) 7~8월 누락분을 한 번에 채우고 싶을 때: BACKFILL_FROM=2026-07-01
BACKFILL_FROM = os.getenv('BACKFILL_FROM')

if not EMAIL or not PASSWORD:
    print("❌ MYHUBON_EMAIL 또는 MYHUBON_PASSWORD secret이 설정되지 않았습니다.")
    exit(1)

os.makedirs(DATA_DIR, exist_ok=True)

# ====================== 공통 헤더 ======================
BASE_HEADERS = {
    "Content-Type":       "application/json",
    "User-Agent":         "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36 Edg/146.0.0.0",
    "sec-ch-ua":          '"Chromium";v="146", "Not-A.Brand";v="24", "Microsoft Edge";v="146"',
    "sec-ch-ua-mobile":   "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Origin":             "https://seller.myhubon.com",
    "Referer":            "https://seller.myhubon.com/",
    "X-Client-Type":      "ADMIN",
    "accept":             "application/json, text/plain, */*",
}

# ====================== STEP 0: 마지막 동기화 지점 로드 ======================
def load_last_sync():
    """이전 실행에서 저장한 마지막 동기화 시점(to_date)을 읽어온다."""
    if not os.path.exists(STATE_FILE):
        return None
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
        last_to = state.get("last_to_date")
        if last_to:
            return datetime.strptime(last_to, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
    except Exception as e:
        print(f"⚠️ 상태 파일({STATE_FILE}) 읽기 실패: {e} → 무시하고 진행")
    return None

def save_last_sync(to_dt):
    """이번에 성공적으로 수집한 마지막 시점을 상태 파일에 기록한다."""
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {
                "last_to_date": to_dt.strftime("%Y-%m-%dT%H:%M:%S.999Z"),
                "saved_at_kst": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            },
            f, ensure_ascii=False, indent=2
        )

now_utc = datetime.now(timezone.utc)
last_sync_dt = load_last_sync()

if BACKFILL_FROM:
    sync_start = datetime.strptime(BACKFILL_FROM, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    print(f"🛠️ BACKFILL_FROM 지정됨 → {sync_start.date()} 부터 강제로 재수집합니다.")
elif last_sync_dt:
    # 이전 성공 시점보다 1시간 앞에서부터 겹쳐서 조회 (경계값 누락 방지)
    sync_start = last_sync_dt - timedelta(hours=1)
    print(f"🔄 이전 동기화 지점 확인됨 → {sync_start.isoformat()} 부터 이어서 수집합니다.")
else:
    sync_start = now_utc - timedelta(days=BOOTSTRAP_DAYS)
    print(f"ℹ️ 이전 동기화 기록이 없습니다 → 최근 {BOOTSTRAP_DAYS}일 데이터부터 수집을 시작합니다.")

sync_end = now_utc

# 워크플로우가 오랫동안 멈춰 있었어도 데이터가 누락되지 않도록,
# sync_start ~ sync_end 구간을 CHUNK_DAYS 단위로 잘라서 순차적으로 수집한다.
chunks = []
cursor = sync_start
while cursor < sync_end:
    chunk_to = min(cursor + timedelta(days=CHUNK_DAYS), sync_end)
    chunks.append((cursor, chunk_to))
    cursor = chunk_to

print(f"📦 총 {len(chunks)}개 구간으로 나누어 수집합니다. ({sync_start.strftime('%Y-%m-%d')} ~ {sync_end.strftime('%Y-%m-%d')})")

# ====================== STEP 1: 로그인 ======================
print("🔐 로그인 중...")

login_resp = requests.post(
    "https://api.myhubon.com/auth/login",
    headers=BASE_HEADERS,
    json={"email_id": EMAIL, "password": PASSWORD},
    timeout=30
)

if login_resp.status_code != 200:
    print(f"❌ 로그인 실패: {login_resp.status_code}")
    print("응답:", login_resp.text[:800])
    exit(1)

login_data = login_resp.json()

def extract_token(data):
    candidates = [
        data.get("state", {}).get("accessToken")  if isinstance(data.get("state"), dict) else None,
        data.get("state", {}).get("access_token") if isinstance(data.get("state"), dict) else None,
        data.get("accessToken"),
        data.get("access_token"),
        data.get("token"),
        data.get("data", {}).get("accessToken")   if isinstance(data.get("data"), dict) else None,
        data.get("data", {}).get("access_token")  if isinstance(data.get("data"), dict) else None,
    ]
    return next((t for t in candidates if t), None)

token = extract_token(login_data)

if not token:
    print("❌ 응답에서 토큰을 찾을 수 없습니다.")
    print("전체 응답 JSON:", login_resp.text[:1000])
    exit(1)

print(f"✅ 로그인 성공 (토큰 앞 20자: {token[:20]}...)")
download_headers = {**BASE_HEADERS, "Authorization": f"Bearer {token}"}

# ====================== 엑셀 병합 함수 ======================
try:
    import openpyxl
except ImportError:
    print("📦 openpyxl 설치 중...")
    subprocess.run(["pip", "install", "openpyxl", "--break-system-packages", "-q"], check=True)
    import openpyxl

MERGE_KEY_COLUMN = "product_code"  # upsert 기준 키 컬럼명 (고유값이어야 함)

def merge_excel(existing_path, new_path, output_path):
    """기존 엑셀에 새 데이터를 Upsert 병합. 키: MERGE_KEY_COLUMN 열 값 (기본: product_code)."""
    if not os.path.exists(new_path) or os.path.getsize(new_path) == 0:
        print("  ⚠️ 신규 다운로드 파일이 비어 있습니다. (0바이트) → 이 구간은 병합 스킵")
        return False

    try:
        wb_new = openpyxl.load_workbook(new_path)
    except Exception as e:
        print(f"  ❌ 신규 엑셀 파일을 읽을 수 없습니다. (포맷 에러: {e})")
        try:
            with open(new_path, "r", encoding="utf-8", errors="ignore") as f:
                print("  📝 받은 파일 내용 앞부분:", f.read(300))
        except:
            pass
        return False

    ws_new = wb_new.active
    new_rows = list(ws_new.iter_rows(values_only=True))
    if not new_rows or len(new_rows) <= 1:
        print("  ⚠️ 신규 데이터 시트가 비어 있거나 헤더만 존재합니다. → 이 구간은 병합 스킵")
        return False

    header = new_rows[0]
    data_rows = new_rows[1:]
    print(f"  신규 데이터: 헤더 {len(header)}열, 데이터 {len(data_rows)}행")

    if MERGE_KEY_COLUMN not in header:
        print(f"  ❌ 키 컬럼 '{MERGE_KEY_COLUMN}'을 신규 데이터 헤더에서 찾을 수 없습니다. 병합 스킵.")
        return False
    key_idx = header.index(MERGE_KEY_COLUMN)

    if not os.path.exists(existing_path):
        import shutil
        shutil.copy2(new_path, output_path)
        print("  기존 파일 없음 → 신규 데이터 그대로 사용")
        return True

    wb_ex = openpyxl.load_workbook(existing_path)
    ws_ex = wb_ex.active
    ex_rows = list(ws_ex.iter_rows(values_only=True))
    ex_header = ex_rows[0] if ex_rows else None

    if ex_header != header:
        print(f"  ⚠️ 헤더 불일치 (기존: {str(ex_header)[:60]} / 신규: {str(header)[:60]})")
        print("  → 기존 파일을 신규 파일로 교체합니다.")
        import shutil
        shutil.copy2(new_path, output_path)
        return True

    ex_data = {}
    for row in ex_rows[1:]:
        key = row[key_idx] if key_idx < len(row) else None
        if key is not None:
            ex_data[key] = row

    added = updated = 0
    for row in data_rows:
        key = row[key_idx] if key_idx < len(row) else None
        if key is None:
            continue
        if key in ex_data:
            if ex_data[key] != row:
                ex_data[key] = row
                updated += 1
        else:
            ex_data[key] = row
            added += 1

    print(f"  병합 결과: 신규 추가 {added}행 / 업데이트 {updated}행 / 합계 {len(ex_data)}행")

    wb_out = openpyxl.Workbook()
    ws_out = wb_out.active
    ws_out.append(list(header))
    try:
        sorted_keys = sorted(ex_data.keys(), key=lambda k: (str(type(k).__name__), str(k)))
    except TypeError:
        sorted_keys = list(ex_data.keys())
    for key in sorted_keys:
        ws_out.append(list(ex_data[key]))

    wb_out.save(output_path)
    return True

def download_chunk(from_dt, to_dt):
    """지정한 기간의 엑셀을 다운로드해서 TEMP_FILE에 저장. 성공 시 True."""
    from_date_iso = from_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    to_date_iso   = to_dt.strftime("%Y-%m-%dT%H:%M:%S.999Z")
    print(f"📥 구간 다운로드: {from_date_iso} ~ {to_date_iso}")

    payload = {"from_date": from_date_iso, "to_date": to_date_iso}

    dl_resp = None
    for attempt in range(1, 4):
        try:
            print(f"  📡 시도 {attempt}/3...")
            dl_resp = requests.post(
                "https://api.myhubon.com/admin/product/manage/excel-download",
                headers=download_headers,
                json=payload,
                timeout=120
            )
            if dl_resp.status_code == 200:
                break
            print(f"  ⚠️ {dl_resp.status_code} 응답 → {'재시도' if attempt < 3 else '최종 실패'}")
            print("  응답 앞 500자:", dl_resp.text[:500])
        except requests.exceptions.Timeout:
            print(f"  ⏱️ Timeout → {'재시도' if attempt < 3 else '최종 실패'}")

        if attempt < 3:
            wait = 30 * attempt
            print(f"  ⏳ {wait}초 대기...")
            time.sleep(wait)

    if dl_resp is None or dl_resp.status_code != 200:
        print("  ❌ 이 구간 다운로드 최종 실패")
        if dl_resp:
            print("  응답:", dl_resp.text[:500])
        return False

    with open(TEMP_FILE, "wb") as f:
        f.write(dl_resp.content)

    size_kb = os.path.getsize(TEMP_FILE) / 1024
    print(f"  ✅ 신규 데이터 수신 완료 ({size_kb:.1f} KB)")
    return True

# ====================== STEP 2~4: 구간별 다운로드 + 병합 ======================
any_merged = False
last_success_to = None

for i, (chunk_from, chunk_to) in enumerate(chunks, start=1):
    print(f"\n--- 구간 {i}/{len(chunks)} ---")
    ok = download_chunk(chunk_from, chunk_to)

    if not ok:
        print("⛔ 이 구간에서 실패했습니다. 다음 실행 때 같은 지점부터 재시도합니다.")
        break  # 순서를 보장하기 위해 실패한 구간 이후는 진행하지 않는다

    merged = merge_excel(DATA_FILE, TEMP_FILE, MERGED_FILE)
    if merged:
        if os.path.exists(DATA_FILE):
            os.remove(DATA_FILE)
        os.rename(MERGED_FILE, DATA_FILE)
        any_merged = True

    if os.path.exists(TEMP_FILE):
        os.remove(TEMP_FILE)

    # 병합 대상 데이터가 없었더라도(빈 구간) 다운로드 자체는 성공했으므로 체크포인트를 전진시킨다
    last_success_to = chunk_to

if last_success_to:
    save_last_sync(last_success_to)
    print(f"\n💾 동기화 지점 저장: {last_success_to.isoformat()}")

if not any_merged:
    print("ℹ️ 이번 실행에서 새로 병합된 데이터가 없습니다.")

if os.path.exists(DATA_FILE):
    final_size = os.path.getsize(DATA_FILE) / (1024 * 1024)
    print(f"✅ {DATA_FILE} 현재 크기: {final_size:.2f} MB")

# ====================== STEP 5: Git Push ======================
today = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

subprocess.run(["git", "config", "user.name",  "Data Updater Bot"],       check=True)
subprocess.run(["git", "config", "user.email", "bot@jjangse1.github.io"], check=True)
subprocess.run(["git", "add", DATA_FILE, STATE_FILE], check=True)

result = subprocess.run(["git", "diff", "--cached", "--quiet"], capture_output=True)

if result.returncode != 0:
    subprocess.run(["git", "commit", "-m", f"auto: data.xlsx 업데이트 ({today})"], check=True)
    subprocess.run(["git", "push"], check=True)
    print("✅ Git commit & push 완료")
else:
    print("ℹ️ 변경사항 없음 → push 생략")
