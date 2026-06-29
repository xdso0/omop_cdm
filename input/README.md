# input — 입력 데이터 구조 / 실행 예시

코드를 어떤 입력 형식으로 실행하는지 보여준다.

## 1. 입력 구조

`config/pipeline.yaml` 의 `paths.mapping_root` 아래에, 도메인별 `sources` 에
지정한 폴더/데이터셋이 있어야 한다. 원천은 `.sas7bdat` 가 기본이며 같은 이름의
`.csv` 도 자동 인식한다(`<dataset>.sas7bdat` 없으면 `<dataset>.csv`).

```
<mapping_root>/
├── person/   <batch>/person.sas7bdat                 + person_id.xlsx
├── death/    <batch>/death.sas7bdat                   + person_id.xlsx
├── visit/    <batch>/visit_occurrence_full.sas7bdat   + person_id.xlsx
├── condition/<batch>/condition_occurrence.sas7bdat    + person_id.xlsx
├── drug/     <batch>/step01.sas7bdat                  + person_id.xlsx
├── procedure/<batch>/procedure.sas7bdat               + person_id.xlsx
├── observation/<batch>/observation.sas7bdat           + person_id.xlsx
├── note/     <batch>/note.sas7bdat                    + person_id.xlsx
└── measurement/<batch>/measurement.sas7bdat           + person_id.xlsx

<vocab_root>/                # Athena 추출본 (탭 구분 CSV)
├── CONCEPT.csv
├── CONCEPT_RELATIONSHIP.csv
└── VOCABULARY.csv
```

`person_id.xlsx` 의 **Sheet2** 컬럼: `PERSON_ID, sex, name, year_of_birth, month_of_birth`.

각 도메인 원천이 가져야 할 컬럼은 `omop_etl/domains/<domain>.py` 와
`docs/mapping_logic.md` 참조.

## 2. 실행 예시 — `input/sample/`

`scripts/make_sample.py` 가 생성한 작동 예시(구조 동일, CSV/소형 vocab).

```bash
python scripts/make_sample.py
python scripts/run_pipeline.py \
       --config input/sample/pipeline.sample.yaml \
       --domains person death visit condition procedure
```

결과는 [`../output_example/`](../output_example/) 에 생성된다:
표준 매핑된 CDM 테이블, 미매핑 코드(`unmapped/`), 사용한 vocab 서브셋(`used_vocab/`).
