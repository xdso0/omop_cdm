# SAS → Python 매핑 상세

원본 SAS ETL 의 핵심 규칙을 Python 패키지로 옮긴 내용을 정리한다.

## 1. occurrence_id 채번 (`omop_etl/ids.py`)

```
정렬: <date>_datetime 오름차순
일련번호 n: 같은 <date> 안에서 1부터 증가, 날짜가 바뀌면 1로 리셋 (SAS lag)
id = int( {hosp}{YY}{MM}{DD}{도메인코드}{n:zero-pad} )
     YY = year - 2000
```

| 테이블 | 도메인코드 | 일련번호 자리수 | 비고 |
|--------|:---:|:---:|------|
| visit_occurrence | `01` | 5 | |
| condition_occurrence | `02` | 5 | |
| drug_exposure | `03` | 5 | |
| procedure_occurrence | `04` | 6 | |
| measurement | `05` | 6 | |
| observation | `06` | 5 | |
| payer_plan_period | `07` | 5 | visit 의 nn 재사용 |
| visit_cost | `08` | 5 | **순서 다름**: `{YY}{MM}{DD}08{hosp}{nn}` |
| note | `09` | 6 | |

## 2. 방문 매칭 (`omop_etl/visit_match.py`)

### 2단계 매칭 — condition / drug / note / measurement
1. **1차**: 같은 PERSON_ID + `visit_start - window` ≤ event_date ≤ `visit_end` + `provider_id` 일치
2. **2차**: 1차 실패 행을 provider 무시하고 날짜구간만으로 매칭
3. 후보 다수면 `visit_concept_id` 오름차순(필요시 `visit_end - date` 거리)으로 1건 선택

구현은 후보를 한 번에 모아 `provider 일치 우선 → visit_concept_id → 거리` 순으로
정렬·선택하여 위 2단계와 동일한 결과를 낸다.

| 도메인 | window_pre_days | order_by_diff | 9203 NULL |
|--------|:---:|:---:|---|
| condition | 0 | ✗ | (없음) |
| drug | 0 | ✗ | 2차 매칭 |
| note | 7 | ✓ | 2차 매칭 |
| measurement | 7 | ✓ | provider 불일치(=2차) |
| observation | — (1단계) | ✗ | 매칭 전체 |

### 1단계 매칭 — observation
provider 조건 없이 날짜구간만으로 매칭, `visit_concept_id` 최솟값 선택,
`visit_concept_id=9203` 이면 NULL.

> `9203` = 응급(ER) 방문. 일부 도메인은 응급 방문으로의 연결을 끊어 둔다.

## 3. 대상자 필터·검증 (`omop_etl/person_filter.py`)

- **PERSON_ID 8자리**: 유효 환자번호만 (`ids.filter_person_id_length`)
  - observation 만 예외적으로 "자리수 > 1" 사용
- **대상자 제외**: `person_id.xlsx` Sheet2 에서 `name` 에 '삭제' 포함 &
  `year_of_birth < 1900` 인 ID 제거
- **사망후 제거**: death 를 left join, `death_date` 이후 사건 제거
- **정합성 검증**: person 마스터에 없거나, 출생연월 > 사건일(미래 출생)인 ID 를
  검증 리스트로 추출 (원본은 `person_id.xlsx` 로 export)
- **마스터 유지**: person 에 존재하는 PERSON_ID 행만 inner join 후 저장

## 4. 도메인별 특이사항

- **person**: 버전 통합 시 먼저 등장한 PERSON_ID 우선(+ location_id 큰 값 우선).
  보정 엑셀(Sheet2)로 gender/출생연월 덮어쓰기, '삭제' 제외, 상수 컬럼 설정,
  (선택) 가명 ID(PID) 매핑 → `person_m`.
- **visit**: 입원(9202) 이 아니면 `admitting_source_concept_id=38004515`.
  채번 시 만든 `nn` 으로 `payer_plan_period`, `visit_cost` id 동시 생성.
  `preceding_visit_occurrence_id` = 직전 방문 종료일 ≤ 현재 시작일이면 그 방문 id.
- **drug**: `quantity = quantity_days * days_supply`, `drug_concept_id = conceptid`.
- **procedure**: visit 미연결(NULL). (PERSON_ID, datetime, source_value) 중복 제거.
- **measurement**: 구간 `[2001-01-01, 2025-12-31]`, concept_id=0 보정
  (`MCV`→3023599, `Clostridium difficile cytotoxin A/B`→3032068).
  값 파싱은 `preprocessing/measurement_lab.py` 에서 raw 단계에 수행.
- **note**: 날짜구간 컷오프, 텍스트 정제(`$$$$` 제거 후 큰따옴표 래핑).
- **observation**: 종검(exam, 매칭 없음) / 입원(inpatient, 1단계 매칭) 그룹 분리.

## 5. 검사 raw 전처리 (`preprocessing/measurement_lab.py`)

원본 `measurement/<버전>/script/<code>.sas` 는 검사 코드마다 자동 생성된 동일
템플릿이었다(코드값만 다름). raw 엑셀의 위치 기반 컬럼을 읽어 값 파싱 규칙
(`<`,`>`,`-`,`Negative`,`Positive`, 괄호 제거, `No WBC`→0)을 적용한다.
자세한 컬럼 위치/규칙은 모듈 docstring 참조.
