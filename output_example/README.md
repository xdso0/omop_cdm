# output_example — 산출물 예시

`input/sample/` 데이터를 `scripts/run_pipeline.py` 로 변환한 **실제 결과**다.

## 파일

| 파일 | 설명 |
|------|------|
| `person.csv` | PERSON 테이블 |
| `death.csv` | DEATH 테이블 |
| `visit_occurrence.csv` / `payer_plan_period.csv` / `visit_cost.csv` | VISIT 관련 |
| `condition_occurrence.csv` | CONDITION (KCD7 → SNOMED 표준 매핑) |
| `procedure_occurrence.csv` | PROCEDURE (Korean Revenue Code 표준) |
| `unmapped/<domain>_unmapped.csv` | **매핑 실패 코드** — 후속 작업용 (코드, source_concept_id, 건수) |
| `used_vocab/CONCEPT.csv` 등 | **사용한 vocabulary 서브셋** — DB 적재용 |

## 핵심 확인 포인트

- `condition_occurrence.csv`
  - `F32.9` → `condition_concept_id = 35489007`(SNOMED 표준), `source_concept_id = 100`
  - `Z99.9` → 표준 매핑 없음 → `condition_concept_id = 0`, `source_concept_id = 102`,
    그리고 `unmapped/condition_unmapped.csv` 에 기록
  - `visit_occurrence_id` 가 방문 매칭으로 채워짐
- `used_vocab/` 의 CONCEPT/CONCEPT_RELATIONSHIP/VOCABULARY 는 **이번 변환에서 실제로
  쓰인 concept 만** 추려 둔 것 → 그대로 DB 에 적재해 CDM 과 조인.

> 이 폴더는 `make_sample.py` + `run_pipeline.py` 로 재생성된다.
