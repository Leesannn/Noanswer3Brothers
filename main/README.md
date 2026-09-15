# 스포츠 데이터 분석 MVP

기존 지도자 자격·기관 프로그램 데이터와 시연용 신청 현황을 보여주는 Django 프로젝트입니다. 권장 Python 버전은 **3.13**입니다.

> 정원 및 신청 현황은 서비스 기능 시연을 위해 생성한 합성 데이터이며, 실제 기관의 운영 실적이 아닙니다.

## Windows

```bash
py -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py generate_demo_data
python manage.py runserver
```

## macOS/Linux

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py generate_demo_data
python manage.py runserver
```

실행 후 [http://127.0.0.1:8000/](http://127.0.0.1:8000/)에 접속합니다. 기본 DB는 프로젝트 내부의 `db.sqlite3`이며 별도 DB 서버가 필요하지 않습니다.

## 지도자 맞춤 추천

로그인 없이 [http://127.0.0.1:8000/recommendations/](http://127.0.0.1:8000/recommendations/)에서 사용할 수 있습니다.

- 자격증 보유자: 보유 자격·지도 종목·희망 지역을 입력해 활동 기회를 살펴볼 기관을 최대 5곳 안내합니다.
- 자격증 미보유자: 관심 종목·지역을 입력해 취득을 고려할 자격 방향을 최대 5개 안내합니다.
- 개인정보와 추천 결과는 별도 모델에 저장하지 않습니다. 새로고침을 위한 최소 입력값만 Django 세션에 보관합니다.
- 추천은 `ProgramCleanup`에서 운영 중이며 사용 가능하고 기준 종목이 연결된 프로그램만 사용합니다. 신청률과 대기 인원은 `ApplicationStatus.is_synthetic` 여부를 화면에 명시합니다.

기관 추천은 종목 40점, 지역 25점, 대상 10점, 신청률 15점, 대기자 10점으로 계산합니다. 자격 방향 추천은 관심 종목 35점, 지역 20점, 신청률 20점, 공급 부족도 15점, 대상 10점으로 계산합니다.

## 합성 데이터

`python manage.py generate_demo_data`는 고정 난수 시드 `2026`으로 프로그램별 최근 6개월 현황을 생성합니다. 이미 생성되었다면 중복을 만들지 않습니다. 다시 생성하려면 다음을 실행합니다.

```bash
python manage.py generate_demo_data --refresh
```

`--refresh`는 `is_synthetic=True`인 합성 현황만 교체하며, 업로드한 실제 신청 데이터는 수정하거나 삭제하지 않습니다.

## 원본 데이터

원본 CSV/XLSX는 프로젝트의 `data/` 폴더에 복사한 뒤 웹의 **데이터 업로드** 화면에서 불러오거나 다음 명령을 사용할 수 있습니다.

```bash
python manage.py import_sports_file data/programs.csv --type auto --allow-invalid
```

CSV의 UTF-8, UTF-8-SIG, CP949, EUC-KR 인코딩과 XLSX를 지원합니다.

새 데이터베이스에서 실제 프로그램 자료부터 준비하는 정확한 순서는 다음과 같습니다.

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py import_sports_file data/qualifications.csv --type qualification --allow-invalid
python manage.py import_sports_file data/programs.csv --type program --allow-invalid
python manage.py match_program_sports
python manage.py clean_program_data
python manage.py generate_demo_data
python manage.py runserver
```

파일명은 복사한 실제 파일명에 맞게 바꿉니다. 이미 데이터가 포함된 `db.sqlite3`을 함께 복사했다면 업로드·매칭·정리 단계는 생략하고 아래 순서만 실행하면 됩니다.

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py generate_demo_data
python manage.py runserver
```

## 다른 컴퓨터로 옮기기

프로젝트 폴더 전체를 복사하되 `venv`, `.venv`, `__pycache__`는 제외합니다. 기존 SQLite 데이터까지 그대로 옮기려면 `db.sqlite3`도 함께 복사합니다. 처음부터 새로 만들려면 `db.sqlite3`을 제외하고, 새 컴퓨터에서 `migrate` 후 `generate_demo_data`를 실행합니다. 단, 합성 현황을 생성할 기존 프로그램 데이터는 먼저 업로드해야 합니다.

복사 대상은 소스 코드, `requirements.txt`, 생성된 `app/migrations/`, `app/templates/`, `app/static/`, 필요한 경우 `data/`와 `db.sqlite3`입니다.

## 검증

```bash
python manage.py check
python manage.py test
```

## 프로그램 종목 매칭

자격 종목 데이터를 기준 taxonomy로 동기화하고 프로그램 전체를 다시 매칭하려면 다음을 실행합니다.

```bash
python manage.py match_program_sports
```

매칭 규칙은 `app/sport_matching_rules.json`에서 관리합니다. `synonyms`에는 신뢰할 수 있는
동의어, `parent_mappings`에는 세부 프로그램과 상위 자격 종목, `context_rules`에는 시설
유형 같은 보조 문맥 규칙을 추가합니다. 각 규칙의 `targets`는 우선순위 목록이며 실제 자격
taxonomy에 존재하는 첫 종목만 사용됩니다. 존재하지 않는 종목은 자동 생성하거나 강제로
연결하지 않습니다. 규칙 변경 후 테스트와 `match_program_sports`를 다시 실행합니다.

관리자가 Django 관리자 화면에서 매칭을 수정하거나 “수동 확정” 처리한 프로그램은 이후
자동 재매칭에서 제외됩니다.

## 현재 운영 프로그램 정리

원본 `Program` 데이터와 기존 지역·기관·자격증 통계는 수정하지 않고,
`ProgramCleanup` 테이블에 프로그램별 정리 결과를 1:1로 생성합니다. 기본 기준일은
`2026-07-31`이며 `main/settings.py`의 `PROGRAM_CLEANUP_REFERENCE_DATE`에서 변경할 수 있습니다.

```bash
python manage.py clean_program_data
python manage.py clean_program_data --reference-date 2026-07-31
```

명령을 반복 실행해도 같은 프로그램의 결과가 갱신될 뿐 중복 행은 생기지 않습니다.
정리 규칙은 `app/program_cleanup_rules.json`에서 관리합니다. 실행 후 `/current-programs/`에서
원본명·정리명·운영 상태·제외 사유·판정 근거를 확인할 수 있고, `/demand-supply/`에서
기존 정규화 지역과 자격증 집계값을 이용한 지역별 프로그램·자격증 비교를 볼 수 있습니다.
