import os
import json
from datetime import datetime, timedelta
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# GitHub Secrets에서 불러오기
CLIENT_ID = os.getenv('GSC_CLIENT_ID')
CLIENT_SECRET = os.getenv('GSC_CLIENT_SECRET')
REFRESH_TOKEN = os.getenv('GSC_REFRESH_TOKEN')
SITE_URL = "https://myhubon.com"          # ← 당신 사이트 URL로 변경하세요!

if not all([CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN]):
    raise ValueError("GitHub Secrets에 GSC_ 관련 값이 제대로 등록되지 않았습니다.")

creds = Credentials(
    None,
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    refresh_token=REFRESH_TOKEN,
    token_uri="https://oauth2.googleapis.com/token"
)

service = build('webmasters', 'v3', credentials=creds)

# 최근 90일 데이터 가져오기
end_date = datetime.now().date()
start_date = end_date - timedelta(days=89)

request = {
    'startDate': start_date.strftime('%Y-%m-%d'),
    'endDate': end_date.strftime('%Y-%m-%d'),
    # 'date'와 'query'를 함께 넣으면 "언제 어떤 단어가" 데이터가 나옵니다.
    'dimensions': ['date', 'query', 'page'], 
    'rowLimit': 25000  # 상세 데이터이므로 행 제한을 넉넉히 잡습니다.
}

response = service.searchanalytics().query(siteUrl=SITE_URL, body=request).execute()

daily_data = []
for row in response.get('rows', []):
    daily_data.append({
        'date': row['keys'][0],
        'clicks': int(row.get('clicks', 0)),
        'impr': int(row.get('impressions', 0)),
        'ctr': round(row.get('ctr', 0), 4),
        'pos': round(row.get('position', 0), 1)
    })

output = {
    'updated': datetime.now().strftime('%Y-%m-%d'),
    'daily': daily_data[:500]   # 너무 많으면 기존 fallback 형식에 맞게 제한
}

with open('gsc-data.json', 'w', encoding='utf-8') as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print(f"✅ GSC 데이터 업데이트 완료: {len(daily_data)}일 데이터 → gsc-data.json 저장")
