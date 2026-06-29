"""MEASUREMENT 도메인.


처리: 버전 통합 → [2001-01-01, 2025-12-31] 구간 + concept 보정 → 중복 제거 →
채번('05', 6자리) → PERSON_ID 8자리/대상자 제외/사망후 제거 → person 검증 →
visit 2단계 매칭(window 7, 거리 우선, 9203 NULL).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..cdm_schema import select_columns
from ..config import PipelineConfig
from ..ids import assign_occurrence_id, filter_person_id_length
from ..person_filter import (
    exclude_persons,
    keep_in_person_master,
    load_excluded_persons,
    remove_after_death,
    validate_against_person,
)
from ..visit_match import match_visit_two_pass
from ._common import load_sources, maybe_map_standard

_KEEP = [
    "PERSON_ID", "measurement_concept_id", "measurement_date", "measurement_time",
    "measurement_type_concept_id", "operator_concept_id", "value_as_number",
    "value_as_concept_id", "unit_concept_id", "range_low", "range_high", "provider_id",
    "measurement_source_value", "measurement_source_concept_id", "unit_source_value",
    "value_source_value", "hosp",
]


def _preprocess(a: pd.DataFrame) -> pd.DataFrame:
    d = pd.to_datetime(a["measurement_date"])
    a = a[(d >= pd.Timestamp("2001-01-01")) & (d <= pd.Timestamp("2025-12-31"))].copy()

    a["measurement_concept_id"] = a["measurement_concept_id"].fillna(0)
    src1 = a["measurement_source_value"].astype(str).str.split("|").str[0]
    a.loc[a["measurement_concept_id"].eq(0) & src1.eq("MCV"), "measurement_concept_id"] = 3023599
    a.loc[
        a["measurement_concept_id"].eq(0) & src1.eq("Clostridium difficile cytotoxin A/B"),
        "measurement_concept_id",
    ] = 3032068
    for c in ["operator_concept_id", "value_as_concept_id"]:
        if c in a.columns:
            a[c] = a[c].fillna(0)

    cols = [c for c in _KEEP if c in a.columns]
    return a[cols].drop_duplicates()


def build(
    cfg: PipelineConfig,
    person: pd.DataFrame,
    death: pd.DataFrame,
    visit: pd.DataFrame,
    *,
    person_id_xlsx: str | Path,
    mapper=None,
    used_concept_ids: set | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    dom = cfg.domains["measurement"]
    a = _preprocess(load_sources(dom, cfg))
    # Athena 표준 매핑 (LOINC 등). _preprocess 의 concept 보정 이후 적용.
    a = maybe_map_standard(a, cfg, "measurement", mapper, used_concept_ids)

    # 전역 중복 제거
    a = a.drop_duplicates(subset=[
        "measurement_date", "measurement_time", "PERSON_ID",
        "measurement_concept_id", "measurement_source_value", "value_as_number",
    ])

    # 채번
    a = assign_occurrence_id(
        a,
        id_col="measurement_id",
        datetime_col="measurement_time",
        date_col="measurement_date",
        domain_code=dom.domain_code,
        seq_width=dom.seq_width,
    )

    # 대상자/사망 필터
    a = filter_person_id_length(a)
    excluded = load_excluded_persons(person_id_xlsx)
    a = exclude_persons(a, excluded)
    a = remove_after_death(a, death, date_col="measurement_date")
    invalid = validate_against_person(a, person, date_col="measurement_date")
    a = keep_in_person_master(a, person)

    # visit 매칭
    a = match_visit_two_pass(a, visit, date_col="measurement_date", **dom.visit_match)
    a["visit_detail_id"] = a["visit_occurrence_id"]

    a = a.rename(columns={"PERSON_ID": "person_id", "measurement_time": "measurement_datetime"})
    return select_columns(a, "measurement").drop_duplicates(), invalid
