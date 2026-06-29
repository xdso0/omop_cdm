"""실행 가능한 입력 예시(input/sample) 생성기.

원천 데이터(.sas7bdat) 대신 **동일한 스키마의 작은 CSV** 와 미니 Athena vocab,
도메인별 person_id.xlsx 를 만들어, 누구나 구조를 보고 파이프라인을 돌려볼 수 있게 한다.

    python scripts/make_sample.py
    python scripts/run_pipeline.py --config input/sample/pipeline.sample.yaml \
           --domains person death visit condition procedure

산출물은 output_example/ 에 CSV 로 저장된다(개인정보 아님, 더미 데이터).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "input" / "sample"
MAP = SAMPLE / "mapping"
VOCAB = SAMPLE / "vocab"


def _w(df: pd.DataFrame, path: Path, sep=","):
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, sep=sep, encoding="utf-8-sig" if sep == "," else "utf-8")


def _person_id_xlsx(path: Path, rows: list[dict]):
    """도메인 폴더의 person_id.xlsx (Sheet2 = 보정/제외 대상) 생성."""
    path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows, columns=["PERSON_ID", "sex", "name", "year_of_birth", "month_of_birth"])
    with pd.ExcelWriter(path) as xw:
        df.to_excel(xw, sheet_name="Sheet2", index=False)
        pd.DataFrame(columns=["person_id"]).to_excel(xw, sheet_name="Sheet1", index=False)


def make_vocab():
    """미니 Athena vocab (탭 구분)."""
    concept = pd.DataFrame([
        # KCD7 (source, 비표준) → SNOMED 표준
        [100, "우울에피소드,상세불명", "Condition", "KCD7", "KCD7 code", "", "F32.9", "19700101", "20991231", ""],
        [101, "실신 및 허탈", "Condition", "KCD7", "KCD7 code", "", "R55", "19700101", "20991231", ""],
        [102, "건강상태,상세불명", "Observation", "KCD7", "KCD7 code", "", "Z99.9", "19700101", "20991231", ""],
        # SNOMED 표준 target
        [35489007, "Depressive disorder", "Condition", "SNOMED", "Clinical Finding", "S", "35489007", "19700101", "20991231", ""],
        [271594007, "Syncope", "Condition", "SNOMED", "Clinical Finding", "S", "271594007", "19700101", "20991231", ""],
        # Korean Revenue Code (이미 표준)
        [2000001, "수가-AA100", "Procedure", "Korean Revenue Code", "Revenue Code", "S", "AA100", "19700101", "20991231", ""],
    ], columns=["concept_id", "concept_name", "domain_id", "vocabulary_id", "concept_class_id",
                "standard_concept", "concept_code", "valid_start_date", "valid_end_date", "invalid_reason"])
    _w(concept, VOCAB / "CONCEPT.csv", sep="\t")

    rel = pd.DataFrame([
        [100, 35489007, "Maps to", "19700101", "20991231", ""],
        [101, 271594007, "Maps to", "19700101", "20991231", ""],
        # Z99.9(102) 은 Maps to 없음 → 미매핑 예시
    ], columns=["concept_id_1", "concept_id_2", "relationship_id", "valid_start_date", "valid_end_date", "invalid_reason"])
    _w(rel, VOCAB / "CONCEPT_RELATIONSHIP.csv", sep="\t")

    pd.DataFrame([
        ["KCD7", "KCD7", "", "KCD7-2021", 0],
        ["SNOMED", "SNOMED", "", "2024", 0],
        ["Korean Revenue Code", "HIRA Revenue Code", "", "2024", 0],
    ], columns=["vocabulary_id", "vocabulary_name", "vocabulary_reference",
                "vocabulary_version", "vocabulary_concept_id"]).to_csv(
        VOCAB / "VOCABULARY.csv", sep="\t", index=False)


def make_data():
    P1, P2 = 12345678, 23456789      # 정상 환자(8자리)
    PX = 99999999                    # '삭제' 제외 대상

    # ---- person ----
    _w(pd.DataFrame([
        {"PERSON_ID": P1, "gender_concept_id": 8507, "year_of_birth": 1980, "month_of_birth": 3,
         "day_of_birth": 1, "race_concept_id": 0, "ethnicity_concept_id": 0, "location_id": 0},
        {"PERSON_ID": P2, "gender_concept_id": 8532, "year_of_birth": 1991, "month_of_birth": 7,
         "day_of_birth": 15, "race_concept_id": 0, "ethnicity_concept_id": 0, "location_id": 0},
    ]), MAP / "person/sample/person.csv")
    _person_id_xlsx(MAP / "person/person_id.xlsx",
                    [{"PERSON_ID": PX, "sex": "남", "name": "삭제", "year_of_birth": 1800, "month_of_birth": 1}])

    # ---- death (P2 가 2023-01-01 사망) ----
    _w(pd.DataFrame([
        {"PERSON_ID": P2, "death_date": "2023-01-01", "death_datetime": "2023-01-01 00:00:00",
         "death_type_concept_id": 38003569, "cause_concept_id": 0,
         "cause_source_value": "", "cause_source_concept_id": 0},
    ]), MAP / "death/sample/death.csv")
    _person_id_xlsx(MAP / "death/person_id.xlsx", [])

    # ---- visit ----
    _w(pd.DataFrame([
        {"PERSON_ID": P1, "visit_concept_id": 9201, "visit_start_date": "2020-05-10",
         "visit_start_time": "2020-05-10 09:00:00", "visit_end_date": "2020-05-12",
         "visit_end_time": "2020-05-12 10:00:00", "provider_id": 7, "care_site_id": 7},
        {"PERSON_ID": P2, "visit_concept_id": 9202, "visit_start_date": "2021-08-01",
         "visit_start_time": "2021-08-01 13:00:00", "visit_end_date": "2021-08-01",
         "visit_end_time": "2021-08-01 14:00:00", "provider_id": 9, "care_site_id": 9},
    ]), MAP / "visit/sample/visit_occurrence_full.csv")
    _person_id_xlsx(MAP / "visit/person_id.xlsx", [])

    # ---- condition (KCD7 코드) ----
    _w(pd.DataFrame([
        {"PERSON_ID": P1, "condition_start_date": "2020-05-11", "condition_start_datetime": "2020-05-11 09:30:00",
         "condition_end_date": "", "condition_end_datetime": "", "condition_type_concept_id": 32020,
         "stop_reason": "", "provider_id": 7, "condition_source_value": "F32.9"},
        {"PERSON_ID": P1, "condition_start_date": "2020-05-11", "condition_start_datetime": "2020-05-11 09:31:00",
         "condition_end_date": "", "condition_end_datetime": "", "condition_type_concept_id": 32020,
         "stop_reason": "", "provider_id": 7, "condition_source_value": "Z99.9"},  # 미매핑 예시
        {"PERSON_ID": P2, "condition_start_date": "2021-08-01", "condition_start_datetime": "2021-08-01 13:30:00",
         "condition_end_date": "", "condition_end_datetime": "", "condition_type_concept_id": 32020,
         "stop_reason": "", "provider_id": 9, "condition_source_value": "R55"},
    ]), MAP / "condition/sample/condition_occurrence.csv")
    _person_id_xlsx(MAP / "condition/person_id.xlsx", [])

    # ---- procedure (Korean Revenue Code) ----
    _w(pd.DataFrame([
        {"PERSON_ID": P1, "procedure_date": "2020-05-11", "procedure_datetime": "2020-05-11 10:00:00",
         "procedure_type_concept_id": 38000275, "quantity": 1, "provider_id": 7,
         "EDI_code": "AA100", "procedure_source_value": "AA100"},
        {"PERSON_ID": P1, "procedure_date": "2020-05-11", "procedure_datetime": "2020-05-11 10:05:00",
         "procedure_type_concept_id": 38000275, "quantity": 1, "provider_id": 7,
         "EDI_code": "ZZ999", "procedure_source_value": "ZZ999"},  # 미매핑 예시
    ]), MAP / "procedure/sample/procedure.csv")
    _person_id_xlsx(MAP / "procedure/person_id.xlsx", [])


def make_config():
    # 저장소 루트 기준 상대경로 (repo 루트에서 실행). 절대경로/기관 식별정보 미포함.
    cfg = """# 자동 생성된 실행 예시 설정 (scripts/make_sample.py)
paths:
  mapping_root: "input/sample/mapping"
  output_root: "output_example"
  output_format: "csv"
  vocab_root: "input/sample/vocab"
  unmapped_root: "output_example/unmapped"
  used_vocab_root: "output_example/used_vocab"
  vocab_cache_root: "output_example/_vocab_cache"

sas_encoding: "euc-kr"
cutoff_year: 2026

vocabulary:
  athena_release: "sample"
  mappings:
    condition:
      source_col: "condition_source_value"
      source_vocabulary: "KCD7"
      concept_col: "condition_concept_id"
      source_concept_col: "condition_source_concept_id"
    procedure:
      source_col: "procedure_source_value"
      source_vocabulary: "Korean Revenue Code"
      concept_col: "procedure_concept_id"
      source_concept_col: "procedure_source_concept_id"

domains:
  person:
    domain_code: "00"
    sources:
      - {folder: "person/sample", dataset: "person"}
  death:
    domain_code: "-"
    sources:
      - {folder: "death/sample", dataset: "death"}
  visit:
    domain_code: "01"
    seq_width: 5
    sources:
      - {folder: "visit/sample", dataset: "visit_occurrence_full", hosp: 1}
  condition:
    domain_code: "02"
    seq_width: 5
    visit_match: {window_pre_days: 0, order_by_diff: false, null_9203_pass2: false}
    sources:
      - {folder: "condition/sample", dataset: "condition_occurrence", hosp: 1}
  procedure:
    domain_code: "04"
    seq_width: 6
    sources:
      - {folder: "procedure/sample", dataset: "procedure", hosp: 1}
"""
    (SAMPLE / "pipeline.sample.yaml").write_text(cfg, encoding="utf-8")


def main():
    make_vocab()
    make_data()
    make_config()
    print(f"샘플 생성 완료: {SAMPLE}")
    print(f"설정: {SAMPLE / 'pipeline.sample.yaml'}")


if __name__ == "__main__":
    main()
