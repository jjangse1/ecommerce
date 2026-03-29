import os
import requests
import subprocess
from datetime import datetime, timedelta

# ====================== 설정 ======================
os.chdir(os.getenv('GITHUB_WORKSPACE', '.'))

DATA_DIR = "scripts"
DATA_FILE = os.path.join(DATA_DIR, "data.xlsx")
TEMP_FILE = os.path.join(DATA_DIR, "temp.xlsx")

URL = "https://api.myhubon.com/admin/product/manage/excel-download"
BEARER_TOKEN = os.getenv('MYHUBON_BEARER_TOKEN')

if not BEARER_TOKEN:
    print("❌ MYHUBON_BEARER_TOKEN secret이 설정되지 않았습니다.")
    exit(1)

headers = {
    "Authorization": f"Bearer {BEARER_TOKEN}",
    "User-Agent": "Mozilla/5.0",
    "X-Client-Type": "ADMIN",
    "Content-Type": "application/json",
    "Origin": "https://seller.myhubon.com",
    "Referer": "https://seller.myhubon.com/"
}

os.makedirs(DATA_DIR, exist_ok=True)

print("📥 엑셀 다운로드 시작...")

# ==================== 요청 payload (전체 데이터 받기 위해 수정) ====================
payload = {
    "startDate": "2024-01-01",                    # 충분히 과거 날짜로 설정 (전체 데이터 원할 경우)
    "endDate": datetime.now().strftime("%Y-%m-%d"),  # 오늘 날짜까지
    # 필요 시 아래 항목 추가 (관리자 페이지 Network 탭에서 확인 후 사용)
    # "status": "ALL",
    # "searchType": "ALL",
    # "page": 1,
    # "limit": 50000
}

response = requests.post(URL, headers=headers, json=payload, timeout=120)

if response.status_code != 200:
    print(f"❌ 다운로드 실패: {response.status_code}")
    print("응답 내용:", response.text[:800])
    exit(1)

# 파일 저장
with open(TEMP_FILE, "wb") as f:
    f.write(response.content)

if os.path.exists(DATA_FILE):
    os.remove(DATA_FILE)

os.rename(TEMP_FILE, DATA_FILE)

print(f"✅ {DATA_FILE} 다운로드 및 교체 완료 (파일 크기: {os.path.getsize(DATA_FILE) / (1024*1024):.2f} MB)")

# ====================== Git Push ======================
today = datetime.now().strftime("%Y-%m-%d %H:%M:%S")   # ← 날짜 변수 여기서 선언

subprocess.run(["git", "config", "user.name", "Data Updater Bot"], check=True)
subprocess.run(["git", "config", "user.email", "bot@jjangse1.github.io"], check=True)

subprocess.run(["git", "add", DATA_FILE], check=True)

# 변경사항 확인
result = subprocess.run(["git", "diff", "--cached", "--quiet"], capture_output=True)

if result.returncode != 0:   # 변경사항 있음
    subprocess.run(["git", "commit", "-m", f"auto: data.xlsx 업데이트 ({today})"], check=True)
    subprocess.run(["git", "push"], check=True)
    print("✅ Git commit & push 완료")
else:
    print("ℹ️ 변경사항 없음 → push 생략")
