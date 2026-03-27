import os
import requests
import subprocess
from datetime import datetime

# GitHub Actions 환경에서는 REPO_PATH가 현재 작업 디렉토리
os.chdir(os.getenv('GITHUB_WORKSPACE', '.'))

URL = "https://api.myhubon.com/admin/product/manage/excel-download"
BEARER_TOKEN = os.getenv('MYHUBON_BEARER_TOKEN')   # ← GitHub Secrets에 등록할 값

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

print("📥 엑셀 다운로드 시작...")
response = requests.post(URL, headers=headers, json={})

if response.status_code != 200:
    print(f"❌ 다운로드 실패: {response.status_code}")
    print(response.text)
    exit(1)

# 파일 저장
with open("temp.xlsx", "wb") as f:
    f.write(response.content)

# 기존 파일 삭제 후 이름 변경
if os.path.exists("data.xlsx"):
    os.remove("data.xlsx")
os.rename("temp.xlsx", "data.xlsx")

print("✅ data.xlsx 다운로드 및 교체 완료")

# Git 설정 및 push
today = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
subprocess.run(["git", "config", "user.name", "Data Updater Bot"], check=True)
subprocess.run(["git", "config", "user.email", "bot@jjangse1.github.io"], check=True)

subprocess.run(["git", "add", "data.xlsx"], check=True)

# 변경사항이 있을 때만 커밋
result = subprocess.run(["git", "diff", "--cached", "--quiet"], capture_output=True)
if result.returncode != 0:   # 변경사항 있음
    subprocess.run(["git", "commit", "-m", f"auto: data.xlsx 업데이트 ({today})"], check=True)
    subprocess.run(["git", "push"], check=True)
    print("✅ Git push 완료")
else:
    print("ℹ️ 변경사항 없음 → push 생략")
