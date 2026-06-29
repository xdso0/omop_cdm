"""DEATH 도메인.

원본: ``death/death_join.sas``.
버전 통합 → 컷오프 → 환자별 최초 사망일 1건 → 대상자 제외 →
person 마스터 정합성 검증 → 최종 저장.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..cdm_schema import select_columns
from ..config import PipelineConfig
from ..person_filter import (
    apply_cutoff,
    exclude_persons,
    keep_in_person_master,
    load_excluded_persons,
    validate_against_person,
)
from ._common import load_sources


def build(
    cfg: PipelineConfig,
    person: pd.DataFrame,
    *,
    person_id_xlsx: str | Path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """returns (death_cdm, 검증위반_person_id)."""
    dom = cfg.domains["death"]
    a = load_sources(dom, cfg)

    # 컷오프
    a = apply_cutoff(a, date_col="death_date", cutoff_year=dom.cutoff_year)

    # 환자별 최초 사망일 1건
    a = a.sort_values(["PERSON_ID", "death_date"]).drop_duplicates("PERSON_ID", keep="first")

    cols = [
        "PERSON_ID", "death_date", "death_datetime", "death_type_concept_id",
        "cause_concept_id", "cause_source_value", "cause_source_concept_id",
    ]
    a = a[[c for c in cols if c in a.columns]].copy()

    # 대상자 제외
    excluded = load_excluded_persons(person_id_xlsx)
    a = exclude_persons(a, excluded)

    # person 마스터 정합성 검증
    invalid = validate_against_person(a, person, date_col="death_date")

    # 마스터에 있는 행만
    a = keep_in_person_master(a, person)

    # 결측 concept 0 처리
    for c in ["cause_concept_id", "cause_source_concept_id"]:
        if c in a.columns:
            a[c] = a[c].fillna(0)

    a = a.rename(columns={"PERSON_ID": "person_id"})
    return select_columns(a, "death"), invalid
