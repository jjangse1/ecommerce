import os
import requests
import subprocess
import pandas as pd
from datetime import datetime, timedelta

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

# ====================== STEP 2: 증분 범위 계산 ======================
os.makedirs(DATA_DIR, exist_ok=True)

today_str = datetime.now().strftime("%Y-%m-%d")

# 기존 파일에서 마지막 날짜 추출 (날짜 컬럼명은 실제 엑셀에 맞게 수정 필요)
DATE_COLUMN = "updated_at"  # 수정일 기준 증분 (신규 등록 + 기존 상품 변경 모두 포착)

if os.path.exists(DATA_FILE):
    try:
        df_existing = pd.read_excel(DATA_FILE)
        print(f"📂 기존 파일 로드: {len(df_existing)}행")

        # 날짜 컬럼 자동 감지
        if DATE_COLUMN is None:
            date_cols = df_existing.select_dtypes(include=["datetime64", "object"]).columns.tolist()
            for col in date_cols:
                try:
                    parsed = pd.to_datetime(df_existing[col], errors='coerce')
                    if parsed.notna().sum() > len(df_existing) * 0.5:
                        DATE_COLUMN = col
                        df_existing[col] = parsed
                        break
                except Exception:
                    continue

        if DATE_COLUMN and DATE_COLUMN in df_existing.columns:
            last_date = pd.to_datetime(df_existing[DATE_COLUMN], errors='coerce').max()
            if pd.notna(last_date):
                start_date = (last_date + timedelta(days=1)).strftime("%Y-%m-%d")
                print(f"📅 마지막 데이터 날짜: {last_date.strftime('%Y-%m-%d')} → 시작일: {start_date}")
            else:
                start_date = "2024-01-01"
                print("⚠️ 날짜 파싱 실패 → 전체 다운로드")
        else:
            start_date = "2024-01-01"
            print(f"⚠️ 날짜 컬럼 감지 실패 (컬럼 목록: {list(df_existing.columns)[:10]}) → 전체 다운로드")
            print("💡 DATE_COLUMN 변수를 실제 날짜 컬럼명으로 지정하세요.")

    except Exception as e:
        df_existing = None
        start_date = "2024-01-01"
        print(f"⚠️ 기존 파일 읽기 실패: {e} → 전체 다운로드")
else:
    df_existing = None
    start_date = "2024-01-01"
    print("📭 기존 파일 없음 → 전체 다운로드")

if start_date > today_str:
    print("✅ 이미 최신 상태 → 업데이트 불필요")
    exit(0)

print(f"📥 다운로드 범위: {start_date} ~ {today_str}")

# ====================== STEP 3: 신규 데이터 다운로드 ======================
download_headers = {
    **BASE_HEADERS,
    "Authorization": f"Bearer {token}",
}

payload = {
    "startDate": start_date,
    "endDate":   today_str,
}

dl_resp = requests.post(
    "https://api.myhubon.com/admin/product/manage/excel-download",
    headers=download_headers,
    json=payload,
    timeout=120
)

if dl_resp.status_code != 200:
    print(f"❌ 다운로드 실패: {dl_resp.status_code}")
    print("응답:", dl_resp.text[:500])
    exit(1)

with open(TEMP_FILE, "wb") as f:
    f.write(dl_resp.content)

new_size_mb = os.path.getsize(TEMP_FILE) / (1024 * 1024)
print(f"✅ 신규 데이터 다운로드 완료 ({new_size_mb:.2f} MB)")

# ====================== STEP 4: 기존 데이터와 병합 ======================
try:
    df_new = pd.read_excel(TEMP_FILE)
    print(f"📊 신규 데이터: {len(df_new)}행")

    if df_existing is not None and len(df_new) > 0:
        df_merged = pd.concat([df_existing, df_new], ignore_index=True)

        # product_code 기준 중복 제거 → 최신 updated_at 데이터 우선 유지
        before = len(df_merged)
        if "product_code" in df_merged.columns and "updated_at" in df_merged.columns:
            df_merged["updated_at"] = pd.to_datetime(df_merged["updated_at"], errors="coerce")
            df_merged = (
                df_merged
                .sort_values("updated_at", ascending=True)
                .drop_duplicates(subset=["product_code"], keep="last")
            )
        else:
            df_merged = df_merged.drop_duplicates()
        after = len(df_merged)
        if before != after:
            print(f"🔄 업데이트 처리: {before - after}건 (기존 행을 최신 데이터로 교체)")

        df_merged.to_excel(DATA_FILE, index=False)
        print(f"✅ 병합 완료: 총 {len(df_merged)}행 → {DATA_FILE}")
    elif len(df_new) == 0:
        print("ℹ️ 신규 데이터 없음 → 기존 파일 유지")
        os.remove(TEMP_FILE)
        exit(0)
    else:
        # 기존 파일 없는 경우 신규 데이터를 그대로 저장
        import shutil
        shutil.move(TEMP_FILE, DATA_FILE)
        print(f"✅ 초기 저장 완료: {len(df_new)}행")

except Exception as e:
    print(f"❌ 병합 실패: {e}")
    os.remove(TEMP_FILE)
    exit(1)

# 임시 파일 정리
if os.path.exists(TEMP_FILE):
    os.remove(TEMP_FILE)

final_size_mb = os.path.getsize(DATA_FILE) / (1024 * 1024)
print(f"📦 최종 파일 크기: {final_size_mb:.2f} MB")

# ====================== STEP 5: Git Push ======================
today_label = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

subprocess.run(["git", "config", "user.name",  "Data Updater Bot"],       check=True)
subprocess.run(["git", "config", "user.email", "bot@jjangse1.github.io"], check=True)
subprocess.run(["git", "add", DATA_FILE], check=True)

result = subprocess.run(["git", "diff", "--cached", "--quiet"], capture_output=True)

if result.returncode != 0:
    subprocess.run(["git", "commit", "-m", f"auto: data.xlsx 증분 업데이트 ({today_label})"], check=True)
    subprocess.run(["git", "push"], check=True)
    print("✅ Git commit & push 완료")
else:
    print("ℹ️ 변경사항 없음 → push 생략")
