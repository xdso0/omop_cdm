# omop-cdm-etl

EMR/OCS 원천 데이터를 **OMOP CDM (v5.x)** 으로 변환하는 ETL.

SAS(`*_join.sas` 통합 + 버전별 `step01.sas` 등 전처리) 로직을 재사용 가능한
**Python 패키지**로 구조화했다.

## 1. 디렉터리 구조

```
omop-cdm-etl/
├── README.md
├── requirements.txt
├── config/
│   └── pipeline.yaml          # 경로 / 버전목록 / 채번코드 / 컷오프 설정
├── omop_etl/
│   ├── io.py                  # SAS·Excel·CSV 입출력
│   ├── ids.py                 # OMOP occurrence_id 채번
│   ├── visit_match.py         # 방문(visit) 매칭 (2단계 / 1단계)
│   ├── person_filter.py       # 사망일/대상자 필터, person 마스터 검증
│   ├── vocabulary.py          # Athena vocabulary 로딩·표준매핑·used vocab 정리
│   ├── mapping.py             # 도메인에 표준매핑 적용 + 미매핑 보관
│   ├── cdm_schema.py          # OMOP CDM 테이블 컬럼 정의
│   ├── config.py              # 설정 로딩
│   ├── domains/               # 도메인별 ETL
│   │   ├── person.py  care_site.py  provider.py  death.py  visit.py
│   │   ├── condition.py  drug.py  procedure.py
│   │   └── observation.py  note.py  measurement.py
│   └── preprocessing/
│       └── measurement_lab.py # 검사항목 raw→measurement (SAS 수백 개 템플릿 대체)
├── scripts/
│   ├── run_pipeline.py        # 전체 파이프라인 실행기
│   └── make_sample.py         # 실행 가능한 입력 예시 생성기
├── input/                     # 입력 구조 설명 + 실행 가능한 예시(input/sample)
├── output_example/            # 예시 입력으로 생성한 산출물(표준매핑/미매핑/used vocab)
└── docs/
    └── mapping_logic.md       # SAS → Python 매핑 상세 설명
```

## 2. 설치

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
```

## 3. 사용법

`config/pipeline.yaml` 의 `paths.mapping_root` 를 원본 `mappingTable` 폴더로 지정한 뒤:

```bash
# 전체 파이프라인
python scripts/run_pipeline.py --config config/pipeline.yaml \
       --provider-xlsx D:/g/mappingTable/care_site/provider260202.xlsx

# 일부 도메인만 (의존 순서 유지: person → death → visit → 나머지)
python scripts/run_pipeline.py --domains person death visit condition
```

산출물은 `paths.output_root`(기본 `D:/g/cdm_output`)에 parquet 으로 저장된다.

### 신규 연도(추출 배치) 추가

원본 SAS 에서 `libname` 한 줄을 추가하던 것과 동일하게,
`config/pipeline.yaml` 의 해당 도메인 `sources` 에 항목 한 줄만 추가하고
`cutoff_year` 를 갱신하면 된다.

```yaml
  condition:
    cutoff_year: 2027            # 갱신
    sources:
      - {folder: "condition/b04", dataset: "condition_occurrence"}   # 추가
```

## 4. Athena vocabulary 기반 표준 매핑

모든 개념 매핑은 **Athena(OHDSI) vocabulary** 를 따르며, **표준(standard_concept='S')
concept 만** 사용한다 (`omop_etl/vocabulary.py`).

- 원천 코드(`*_source_value`) → CONCEPT 에서 source concept 조회 →
  이미 표준이면 그대로, 아니면 `CONCEPT_RELATIONSHIP`의 `Maps to` 로 표준 변환.
- 도메인별 규칙은 `config/pipeline.yaml` 의 `vocabulary.mappings` 에 정의
  (`source_col`, `source_vocabulary`, `concept_col`, `source_concept_col`).
  - condition → `KCD7`, procedure → `Korean Revenue Code`, measurement → `LOINC` …
- **미매핑 코드**는 후속 작업용으로 `paths.unmapped_root` 에 저장
  (`<domain>_unmapped.csv`: 코드 / source_concept_id / 건수).
- **사용한 vocabulary** 는 `paths.used_vocab_root` 에 CONCEPT/CONCEPT_RELATIONSHIP/
  VOCABULARY 서브셋으로 정리 → 그대로 **DB 에 적재**해 CDM 과 조인.

### Athena 갱신 / 지속 업데이트

새 Athena 추출본을 받으면 `paths.vocab_root` 와 `vocabulary.athena_release` 값만
바꾸면 전체 파이프라인이 새 vocabulary 를 따른다. release 별로 매핑 캐시가
분리 저장되어 재실행이 빠르다. 신규 연도(추출 배치)는 도메인 `sources` 에 한 줄
추가하면 되므로, 데이터·vocabulary 양쪽 모두 지속적으로 확장 가능하다.

표준 매핑을 끄고 원천 concept_id 를 그대로 쓰려면 `--no-vocab` 옵션 사용.

## 5. 입력/출력 예시

- [`input/`](input/) — 입력 폴더 구조 설명 + **바로 실행되는 미니 예시**(`input/sample/`)
- [`output_example/`](output_example/) — 그 예시를 변환한 산출물

```bash
python scripts/make_sample.py
python scripts/run_pipeline.py --config input/sample/pipeline.sample.yaml \
       --domains person death visit condition procedure
```

## 6. 공통 ETL 패턴

모든 도메인이 동일한 골격을 따른다 (SAS·Python 공통):

1. **버전 통합** — 추출 배치별 원천 데이터셋을 union (`hosp`, rename/drop 적용)
2. **방문 매칭** — 사건을 `visit_occurrence` 에 연결 (도메인별 규칙, `visit_match.py`)
3. **채번** — `occurrence_id = {hosp}{YY}{MM}{DD}{도메인코드}{일련번호}` (`ids.py`)
4. **컷오프** — 기준 연도/기간 이후 제거
5. **사망후 제거** — 사망일 이후 발생 사건 제거
6. **대상자 필터** — PERSON_ID 8자리 + `person_id.xlsx`(Sheet2) '삭제' 대상 제외
7. **person 정합성 검증** — 마스터에 없거나 출생연월이 사건일보다 늦은 ID 추출
8. **마스터 유지 후 저장** — `person` 에 존재하는 행만 최종 CDM 테이블로 저장

도메인별 채번 코드 / 방문 매칭 규칙은 [`docs/mapping_logic.md`](docs/mapping_logic.md) 참조.

## 7. 도메인 ↔ 원본 SAS 대응

| 도메인 | Python 모듈 | 원본 SAS |
|--------|-------------|----------|
| person | `domains/person.py` | `person/person_join.sas` |
| death | `domains/death.py` | `death/death_join.sas` |
| care_site | `domains/care_site.py` | `care_site/step02_care_site.sas` |
| provider | `domains/provider.py` | `provider/provider.sas` |
| visit (+payer_plan_period, +visit_cost) | `domains/visit.py` | `visit/visit_join.sas` |
| condition_occurrence | `domains/condition.py` | `condition/condition_join.sas` |
| drug_exposure | `domains/drug.py` | `drug/drug_join.sas` |
| procedure_occurrence | `domains/procedure.py` | `procedure/procedure_join.sas` |
| observation | `domains/observation.py` | `observation/observation_join.sas` |
| note | `domains/note.py` | `note/script.sas` |
| measurement | `domains/measurement.py` | `measurement/measurement_join.sas` |
| (검사 raw 전처리) | `preprocessing/measurement_lab.py` | `measurement/<버전>/script/*.sas` 수백 개 |

## 8. 비고 / 한계

- 원본의 검사항목 전처리(`measurement/<버전>/script/`)는 코드값만 다른 동일
  템플릿 수백 개였다. 이를 **단일 함수 + 코드 리스트**(`preprocessing/measurement_lab.py`)로
  대체했다.
- `measurement_join.sas` 는 성능을 위해 SAS hash join 을 쓰지만, 로직은 다른
  도메인과 동일하여 동일한 공통 헬퍼로 구현했다.
- 가명화(PID) 매핑 테이블은 외부 경로(`D:\가명화` 등)에 있어 선택 입력으로 처리한다.
- 본 코드는 원본 SAS 로직을 충실히 옮긴 것이며, 실제 데이터로 산출물 동등성
  검증(행 수/키 비교)을 거쳐 운영에 적용할 것을 권장한다.
