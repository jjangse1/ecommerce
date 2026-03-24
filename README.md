# 📦 상품 업로드 트렌드 대시보드

이커머스 상품 업로드 현황을 시각화하는 분석 대시보드입니다.

## 📁 폴더 구조

```
📁 repository
├── index.html      ← 대시보드 (수정 불필요)
├── data.xlsx       ← 매일 이 파일만 교체
└── README.md
```

---

## 🚀 최초 GitHub Pages 세팅 (1회만)

1. GitHub에서 새 Repository 생성
2. `index.html`, `data.xlsx`, `README.md` 업로드
3. Repository → **Settings** → **Pages**
4. Source: `Deploy from a branch` → Branch: `main` / `/ (root)` → **Save**
5. 잠시 후 `https://[계정명].github.io/[레포이름]/` 접속 확인

---

## 🔄 매일 데이터 업데이트 방법

```bash
# data.xlsx 파일을 새 파일로 교체 후:
git add data.xlsx
git commit -m "데이터 업데이트: $(date +%Y-%m-%d)"
git push
```

> Push 후 **약 1~2분** 뒤 링크 새로고침하면 최신 데이터 반영됩니다.

---

## ✅ 동작 방식

| 상황 | 동작 |
|------|------|
| `data.xlsx` 있음 | 페이지 열면 **자동으로 데이터 로드** |
| `data.xlsx` 없음 | 오류 안내 + **수동 파일 선택** 버튼 표시 |

---

## 📊 데이터 파일 형식

`data.xlsx` 파일에 반드시 **`created_at`** 컬럼이 있어야 합니다.

| created_at | 기타 컬럼... |
|------------|-------------|
| 2026-01-05 09:23:00 | ... |
| 2026-01-05 11:45:00 | ... |

- 날짜 형식: `YYYY-MM-DD HH:MM:SS` 또는 엑셀 날짜 형식 모두 지원
- 파일명은 반드시 `data.xlsx` (소문자)
