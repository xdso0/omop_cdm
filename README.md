# omop-cdm-etl

EMR/OCS 원천 데이터를 **OMOP CDM (v5.x)** 으로 변환·생성하는 ETL 패키지.

원천 데이터(`mapping_root`)와 Athena vocabulary 를 입력으로 받아, 도메인별 CDM
테이블을 생성한다. 데이터 생성의 모든 규칙은 이 코드(`omop_etl/`)에 정의돼 있다.

## 1. 디렉터리 구조

```
omop-cdm-etl/
├── README.md
├── requirements.txt
├── config/
│   └── pipeline.yaml          # 경로 / 버전목록 / 채번코드 / 컷오프 설정
├── omop_etl/
│   ├── io.py                  # 원천(sas7bdat)·Excel·CSV 입출력
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
│       └── measurement_lab.py # 검사항목 raw 엑셀 → measurement 변환
├── scripts/
│   ├── run_pipeline.py        # 전체 파이프라인 실행기
│   └── make_sample.py         # 실행 가능한 입력 예시 생성기
├── input/                     # 입력 구조 설명 + 실행 가능한 예시(input/sample)
├── output_example/            # 예시 입력으로 생성한 산출물(표준매핑/미매핑/used vocab)
└── docs/
    └── mapping_logic.md       # 데이터 생성 로직 상세 설명
```

## 2. 설치

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
```

## 3. 사용법

`config/pipeline.yaml` 의 `paths.mapping_root` 를 원천 데이터 폴더로 지정한 뒤:

```bash
# 전체 파이프라인
python scripts/run_pipeline.py --config config/pipeline.yaml \
       --provider-xlsx D:/g/mappingTable/care_site/provider260202.xlsx

# 일부 도메인만 (의존 순서 유지: person → death → visit → 나머지)
python scripts/run_pipeline.py --domains person death visit condition
```

산출물은 `paths.output_root`(기본 `D:/g/cdm_output`)에 parquet 으로 저장된다.

### 신규 연도(추출 배치) 추가

신규 배치는 `config/pipeline.yaml` 의 해당 도메인 `sources` 에 항목 한 줄만 추가하고
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
  - condition → `KCD7`(`A020|...`→`A02.0` 변환 후 SNOMED 표준), measurement → `LOINC`.
  - procedure·drug 의 수가/EDI 코드는 대응 표준 vocabulary 가 없어 자동 매핑하지 않는다(9절 참조).
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

모든 도메인이 동일한 골격을 따른다:

1. **버전 통합** — 추출 배치별 원천 데이터셋을 union (`hosp`, rename/drop 적용)
2. **방문 매칭** — 사건을 `visit_occurrence` 에 연결 (도메인별 규칙, `visit_match.py`)
3. **채번** — `occurrence_id = {hosp}{YY}{MM}{DD}{도메인코드}{일련번호}` (`ids.py`)
4. **컷오프** — 기준 연도/기간 이후 제거
5. **사망후 제거** — 사망일 이후 발생 사건 제거
6. **대상자 필터** — PERSON_ID 8자리 + `person_id.xlsx`(Sheet2) '삭제' 대상 제외
7. **person 정합성 검증** — 마스터에 없거나 출생연월이 사건일보다 늦은 ID 추출
8. **마스터 유지 후 저장** — `person` 에 존재하는 행만 최종 CDM 테이블로 저장

도메인별 채번 코드 / 방문 매칭 규칙은 [`docs/mapping_logic.md`](docs/mapping_logic.md) 참조.

## 7. 도메인 ↔ 모듈 ↔ 생성 테이블

| 도메인 | Python 모듈 | 생성 CDM 테이블 |
|--------|-------------|-----------------|
| person | `domains/person.py` | person (+ person_m) |
| death | `domains/death.py` | death |
| care_site | `domains/care_site.py` | care_site |
| provider | `domains/provider.py` | provider |
| visit | `domains/visit.py` | visit_occurrence, payer_plan_period, visit_cost |
| condition | `domains/condition.py` | condition_occurrence |
| drug | `domains/drug.py` | drug_exposure |
| procedure | `domains/procedure.py` | procedure_occurrence |
| observation | `domains/observation.py` | observation |
| note | `domains/note.py` | note |
| measurement | `domains/measurement.py` | measurement |
| (검사 raw 전처리) | `preprocessing/measurement_lab.py` | measurement 입력 생성 |

## 8. 검증 (결과가 잘 만들어졌는지 확인)

세 가지 방법으로 확인한다.

**(1) 데이터 품질(QC) 검증** — 산출물이 OMOP 규칙을 지키는지

```bash
python scripts/validate_cdm.py --config config/pipeline.yaml
```
점검: PK 유일성·결측, person/visit 외래키 정합성, 표준 concept 매핑률,
날짜 범위·사망일 이후 사건, 시작≤종료. ERROR 가 있으면 종료코드 1.

**(2) 기존 산출물과 대조 (선택)** — 비교 기준이 될 기존 CDM 산출물(`.sas7bdat`/csv)이
있으면 행 수·키·concept 분포·날짜 범위를 대조해 차이를 점검할 수 있다.

```bash
python scripts/compare_with_sas.py \
    --python output/condition_occurrence.parquet \
    --sas    <기존산출물>/condition_occurrence.sas7bdat \
    --keys person_id condition_occurrence_id \
    --concept condition_concept_id --date condition_start_date
```

**(3) 핵심 로직 단위 테스트**

```bash
python tests/test_core.py        # 또는: pytest
```
채번·방문매칭·사망/마스터 필터·표준매핑이 기대값을 내는지 검증.

> 권장 순서: 단위 테스트 → 샘플(`input/sample`)로 파이프라인+QC 통과 확인 →
> 실제 데이터로 도메인 빌드 후 QC → (있으면) 기존 산출물과 대조.

## 9. 데이터 생성 한계

이 코드로 CDM 데이터를 **생성할 때** 본질적으로 존재하는 한계다. 결과를 해석·활용할
때 아래를 감안해야 한다.

### 표준 매핑(vocabulary)
- **미매핑 발생**: 원천 코드가 Athena 표준 concept 로 매핑되지 않으면 `*_concept_id = 0`
  으로 남는다(폐지·오타·표준 개념 없음 등). 미매핑 코드는 `unmapped/` 에 적재되며,
  후속 수기 매핑이 필요하다. 매핑률은 vocabulary 버전과 코드 정제 수준에 좌우된다.
- **한국 고유 코드의 표준화 부재**: 수가/EDI(procedure·drug) 코드는 대응하는 Athena
  표준 vocabulary 가 없어 자동 표준 매핑이 불가하다. 현재는 원천 concept_id 를 그대로
  쓰며(표준성 미보장), 별도의 EDI→표준 매핑 테이블이 있어야 정식 표준화가 된다.
- **vocabulary 버전 의존**: Athena release 시점에 따라 같은 코드라도 매핑 결과가
  달라질 수 있다(표준 concept 변경/폐지). `athena_release` 로 버전을 고정·기록한다.

### 방문(visit) 연결
- **휴리스틱 매칭**: 사건(진단/약물/검사/노트)을 방문에 연결할 때 날짜구간(±윈도우)과
  provider 일치로 **1건만** 고른다. 외래/입원/응급 경계나 같은 날 다중 방문에서
  오매칭·미매칭이 생길 수 있고, 못 붙은 사건은 `visit_occurrence_id = NULL` 로 남는다.

### 식별자(occurrence_id)
- **surrogate key**: `{병원}{YYMMDD}{도메인코드}{일련번호}` 로 만든 인공 키다. 원천
  고유키가 아니므로 **재실행하거나 데이터를 추가하면 값이 바뀔 수 있다**(영구 식별자로
  외부 참조 금지). 같은 날짜 행이 매우 많으면 일련번호 자리수가 늘 수 있으나 유일성은 유지된다.

### 대상자·시간 정합성
- **대상자 필터로 인한 누락**: PERSON_ID 8자리 규칙, person 마스터 부재, '삭제' 대상
  제외에 걸리면 해당 레코드는 산출물에서 빠진다. person 마스터에 없는 환자의 사건은 전부 제외된다.
- **시간 이상치**: 사망일 이후 사건·출생 이후 검증으로 일부는 제거하지만, 원천 날짜
  오류(미래/과거 이상치)를 완전히 잡지는 못한다. 날짜가 결측인 행은 채번 불가로 제외된다.

### 값/단위·중복
- **단위·값 표준화 미흡**: measurement 의 단위(unit_concept_id)·값 표준 단위 변환은
  원천에 의존한다. 결과값의 부등호/음양성 등은 규칙 기반 파싱이라 비정형 표기는 누락될 수 있다.
- **중복 가능성**: 여러 추출 배치를 합치므로 동일 사건이 중복될 수 있다. distinct 로
  제거하지만 source_value·시간의 미세 차이로 잔존할 수 있다. (대용량 스트리밍 시 청크
  경계를 넘는 중복은 못 잡을 수 있음.)

### 범위·기타
- **컷오프**: 설정한 연도/기간 이후 데이터는 의도적으로 제외된다(최신 데이터 누락 가능).
- **care_site/provider**: provider 엑셀에 없는 부서·제공자는 매핑되지 않아 0 으로 남는다.
- **가명화 ID**: PID 매핑은 선택 입력이며, 적용하지 않으면 원천 PERSON_ID 가 그대로 쓰인다.
