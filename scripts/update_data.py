import os
import requests
import subprocess
import time
from datetime import datetime, timezone, timedelta

# ====================== 설정 ======================
os.chdir(os.getenv('GITHUB_WORKSPACE', '.'))

DATA_DIR  = "scripts"
DATA_FILE = os.path.join(DATA_DIR, "data.xlsx")
TEMP_FILE = os.path.join(DATA_DIR, "temp_new.xlsx")

EMAIL    = os.getenv('MYHUBON_EMAIL')
PASSWORD = os.getenv('MYHUBON_PASSWORD')

if not EMAIL or not PASSWORD:
    print("❌ MYHUBON_EMAIL 또는 MYHUBON_PASSWORD secret이 설정되지 않았습니다.")
    exit(1)

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

# ====================== STEP 2: 최근 7일 ISO 형식으로 엑셀 다운로드 ======================
# 서버 504 타임아웃 방지: 전체 기간 대신 최근 7일만 요청
now_utc = datetime.now(timezone.utc)
to_dt   = now_utc.replace(hour=14, minute=59, second=59, microsecond=999000)
from_dt = (now_utc - timedelta(days=7)).replace(hour=15, minute=0, second=0, microsecond=0)

from_date_iso = from_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
to_date_iso   = to_dt.strftime("%Y-%m-%dT%H:%M:%S.999Z")

print(f"📅 조회 기간: {from_date_iso}  ~  {to_date_iso}")
print("📥 최근 7일 엑셀 다운로드 시작...")

download_headers = {**BASE_HEADERS, "Authorization": f"Bearer {token}"}
payload = {
    "from_date": from_date_iso,
    "to_date":   to_date_iso,
}

os.makedirs(DATA_DIR, exist_ok=True)

dl_resp = None
for attempt in range(1, 4):
    try:
        print(f"📡 시도 {attempt}/3...")
        dl_resp = requests.post(
            "https://api.myhubon.com/admin/product/manage/excel-download",
            headers=download_headers,
            json=payload,
            timeout=120   # 7일치 → 120초로 단축
        )
        if dl_resp.status_code == 200:
            break
        print(f"⚠️ {dl_resp.status_code} 응답 → {'재시도' if attempt < 3 else '최종 실패'}")
        print("응답 앞 500자:", dl_resp.text[:500])
    except requests.exceptions.Timeout:
        print(f"⏱️ Timeout → {'재시도' if attempt < 3 else '최종 실패'}")

    if attempt < 3:
        wait = 30 * attempt   # 7일치라 대기 단축
        print(f"⏳ {wait}초 대기...")
        time.sleep(wait)

if dl_resp is None or dl_resp.status_code != 200:
    print("❌ 다운로드 최종 실패")
    if dl_resp:
        print("응답:", dl_resp.text[:500])
    exit(1)

# ====================== STEP 3: 임시 파일에 저장 ======================
with open(TEMP_FILE, "wb") as f:
    f.write(dl_resp.content)

new_size = os.path.getsize(TEMP_FILE) / 1024
print(f"✅ 신규 데이터 수신 완료 ({new_size:.1f} KB)")

# ====================== STEP 4: 기존 엑셀과 병합 (Upsert) ======================
try:
    import openpyxl
except ImportError:
    print("📦 openpyxl 설치 중...")
    import subprocess as sp
    sp.run(["pip", "install", "openpyxl", "--break-system-packages", "-q"], check=True)
    import openpyxl

def merge_excel(existing_path, new_path, output_path):
    """기존 엑셀에 새 데이터를 Upsert 병합. 키: 첫 번째 열 값."""
    wb_new = openpyxl.load_workbook(new_path)
    ws_new = wb_new.active
    new_rows = list(ws_new.iter_rows(values_only=True))
    if not new_rows:
        print("⚠️ 신규 데이터 시트가 비어 있습니다. 병합 스킵.")
        return False

    header = new_rows[0]
    data_rows = new_rows[1:]
    print(f"  신규 데이터: 헤더 {len(header)}열, 데이터 {len(data_rows)}행")

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

    # 기존 행을 키(첫 번째 열) 기준으로 dict에 로드
    ex_data = {}
    for row in ex_rows[1:]:
        key = row[0]
        if key is not None:
            ex_data[key] = row

    # 신규 데이터 upsert
    added = updated = 0
    for row in data_rows:
        key = row[0]
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

    # 결과 워크북 생성
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


MERGED_FILE = os.path.join(DATA_DIR, "merged.xlsx")
success = merge_excel(DATA_FILE, TEMP_FILE, MERGED_FILE)

if not success:
    print("❌ 병합 실패 → 기존 파일 유지, 종료")
    if os.path.exists(TEMP_FILE):
        os.remove(TEMP_FILE)
    exit(1)

# 병합 파일로 교체
if os.path.exists(DATA_FILE):
    os.remove(DATA_FILE)
os.rename(MERGED_FILE, DATA_FILE)
if os.path.exists(TEMP_FILE):
    os.remove(TEMP_FILE)

final_size = os.path.getsize(DATA_FILE) / (1024 * 1024)
print(f"✅ {DATA_FILE} 저장 완료 ({final_size:.2f} MB)")

# ====================== STEP 5: Git Push ======================
today = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

subprocess.run(["git", "config", "user.name",  "Data Updater Bot"],       check=True)
subprocess.run(["git", "config", "user.email", "bot@jjangse1.github.io"], check=True)
subprocess.run(["git", "add", DATA_FILE], check=True)

result = subprocess.run(["git", "diff", "--cached", "--quiet"], capture_output=True)

if result.returncode != 0:
    subprocess.run(["git", "commit", "-m", f"auto: data.xlsx 업데이트 ({today})"], check=True)
    subprocess.run(["git", "push"], check=True)
    print("✅ Git commit & push 완료")
else:
    print("ℹ️ 변경사항 없음 → push 생략")
