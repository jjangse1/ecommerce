import os
import requests
import subprocess
from datetime import datetime

# ====================== 설정 ======================
# GitHub Actions 환경에서 작업 디렉토리 이동
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

# 디렉토리 생성 (scripts 폴더가 없으면 자동 생성)
os.makedirs(DATA_DIR, exist_ok=True)

print("📥 엑셀 다운로드 시작...")

response = requests.post(URL, headers=headers, json={}, timeout=60)

if response.status_code != 200:
    print(f"❌ 다운로드 실패: {response.status_code}")
    print(response.text[:500])   # 에러 메시지 일부 출력
    exit(1)

# temp 파일로 저장
with open(TEMP_FILE, "wb") as f:
    f.write(response.content)

# 기존 파일 삭제 후 이름 변경
if os.path.exists(DATA_FILE):
    os.remove(DATA_FILE)

os.rename(TEMP_FILE, DATA_FILE)

print(f"✅ {DATA_FILE} 다운로드 및 교체 완료")

# ====================== Git Push ======================
today = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

subprocess.run(["git", "config", "user.name", "Data Updater Bot"], check=True)
subprocess.run(["git", "config", "user.email", "bot@jjangse1.github.io"], check=True)

subprocess.run(["git", "add", DATA_FILE], check=True)

# 변경사항 확인
result = subprocess.run(["git", "diff", "--cached", "--quiet"], capture_output=True)

if result.returncode != 0:  # 변경사항 있음
    subprocess.run(["git", "commit", "-m", f"auto: data.xlsx 업데이트 ({today})"], check=True)
    subprocess.run(["git", "push"], check=True)
    print("✅ Git commit & push 완료")
else:
    print("ℹ️ 변경사항 없음 → push 생략")
