"""CONDITION_OCCURRENCE 도메인.

버전 통합 → visit 2단계 매칭 → 컷오프 → 채번 → 사망후 제거 →
대상자 필터 → person 정합성 검증 → 저장.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..cdm_schema import select_columns
from ..config import PipelineConfig
from ..ids import assign_id, filter_person_id_length
from ..person_filter import (
    apply_cutoff,
    exclude_persons,
    keep_in_person_master,
    load_excluded_persons,
    remove_after_death,
    validate_against_person,
)
from ..visit_match import match_visit_two_pass
from ._common import load_sources, maybe_map_standard


def build(
    cfg: PipelineConfig,
    person: pd.DataFrame,
    death: pd.DataFrame,
    visit: pd.DataFrame,
    *,
    person_id_xlsx: str | Path,
    mapper=None,
    used_concept_ids: set | None = None,
    source_override: pd.DataFrame | None = None,
    id_counter: dict | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    dom = cfg.domains["condition"]
    a = source_override if source_override is not None else load_sources(dom, cfg)
    a = a[a["PERSON_ID"].notna()]
    if "visit_occurrence_id" in a.columns:
        a = a.drop(columns="visit_occurrence_id")

    # Athena 표준 매핑 (config 에 정의된 경우)
    a = maybe_map_standard(a, cfg, "condition", mapper, used_concept_ids)

    # visit 매칭
    a = match_visit_two_pass(a, visit, date_col="condition_start_date", **dom.visit_match)

    # 컷오프
    a = apply_cutoff(a, date_col="condition_start_date", cutoff_year=dom.cutoff_year)

    # 채번
    a = assign_id(
        a, id_counter,
        id_col="condition_occurrence_id",
        datetime_col="condition_start_datetime",
        date_col="condition_start_date",
        domain_code=dom.domain_code,
        seq_width=dom.seq_width,
    )
    a["condition_status_concept_id"] = 0
    a["condition_status_source_value"] = ""
    a["visit_detail_id"] = a["visit_occurrence_id"]

    # 사망후 제거 + PERSON_ID 8자리
    a = remove_after_death(a, death, date_col="condition_start_date")
    a = filter_person_id_length(a)
    a["condition_concept_id"] = a["condition_concept_id"].fillna(0)

    # 대상자 필터/검증
    excluded = load_excluded_persons(person_id_xlsx)
    a = exclude_persons(a, excluded)
    invalid = validate_against_person(a, person, date_col="condition_start_date")
    a = keep_in_person_master(a, person)

    a = a.rename(columns={"PERSON_ID": "person_id"})
    return select_columns(a, "condition_occurrence").drop_duplicates(), invalid
