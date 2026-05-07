import os
import requests
import subprocess
import time
from datetime import datetime

# ====================== 설정 ======================
os.chdir(os.getenv('GITHUB_WORKSPACE', '.'))

DATA_DIR  = "scripts"
DATA_FILE = os.path.join(DATA_DIR, "data.xlsx")
TEMP_FILE = os.path.join(DATA_DIR, "temp.xlsx")

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

# ====================== STEP 2: 엑셀 다운로드 (최대 3회 재시도) ======================
print("📥 엑셀 다운로드 시작...")

download_headers = {**BASE_HEADERS, "Authorization": f"Bearer {token}"}
payload = {
    "startDate": "2024-01-01",
    "endDate":   datetime.now().strftime("%Y-%m-%d"),
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
            timeout=300
        )
        if dl_resp.status_code == 200:
            break
        print(f"⚠️ {dl_resp.status_code} 응답 → {'재시도' if attempt < 3 else '최종 실패'}")
    except requests.exceptions.Timeout:
        print(f"⏱️ Timeout → {'재시도' if attempt < 3 else '최종 실패'}")

    if attempt < 3:
        wait = 60 * attempt
        print(f"⏳ {wait}초 대기...")
        time.sleep(wait)

if dl_resp is None or dl_resp.status_code != 200:
    print("❌ 다운로드 최종 실패")
    if dl_resp:
        print("응답:", dl_resp.text[:500])
    exit(1)

# ====================== STEP 3: 저장 ======================
with open(TEMP_FILE, "wb") as f:
    f.write(dl_resp.content)

if os.path.exists(DATA_FILE):
    os.remove(DATA_FILE)
os.rename(TEMP_FILE, DATA_FILE)

size_mb = os.path.getsize(DATA_FILE) / (1024 * 1024)
print(f"✅ {DATA_FILE} 저장 완료 ({size_mb:.2f} MB)")

# ====================== STEP 4: Git Push ======================
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
