"""PROCEDURE_OCCURRENCE 도메인.

원본: ``procedure/procedure_join.sas``.
visit 매칭을 하지 않고(미연결 NULL), (PERSON_ID, datetime, source_value) 기준으로
중복 제거하는 점이 다르다.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..cdm_schema import select_columns
from ..config import PipelineConfig
from ..ids import assign_occurrence_id, filter_person_id_length
from ..person_filter import (
    apply_cutoff,
    exclude_persons,
    keep_in_person_master,
    load_excluded_persons,
    remove_after_death,
    validate_against_person,
)
from ._common import load_sources, maybe_map_standard


def build(
    cfg: PipelineConfig,
    person: pd.DataFrame,
    death: pd.DataFrame,
    *,
    person_id_xlsx: str | Path,
    mapper=None,
    used_concept_ids: set | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    dom = cfg.domains["procedure"]
    a = load_sources(dom, cfg)

    # 중복 제거: PERSON_ID + procedure_datetime + procedure_source_value
    a = a[a["procedure_datetime"].notna()]
    a = a.drop_duplicates(subset=["PERSON_ID", "procedure_datetime", "procedure_source_value"])

    # Athena 표준 매핑
    a = maybe_map_standard(a, cfg, "procedure", mapper, used_concept_ids)
    a["procedure_concept_id"] = a["procedure_concept_id"].fillna(0)
    a = assign_occurrence_id(
        a,
        id_col="procedure_occurrence_id",
        datetime_col="procedure_datetime",
        date_col="procedure_date",
        domain_code=dom.domain_code,
        seq_width=dom.seq_width,
    )
    a["modifier_concept_id"] = 0
    a["modifier_source_value"] = ""
    a["visit_occurrence_id"] = pd.NA   # 시술은 visit 연결 안 함
    a["visit_detail_id"] = pd.NA

    a = apply_cutoff(a, date_col="procedure_date", cutoff_year=dom.cutoff_year)
    a = remove_after_death(a, death, date_col="procedure_date")
    a = filter_person_id_length(a)

    excluded = load_excluded_persons(person_id_xlsx)
    a = exclude_persons(a, excluded)
    invalid = validate_against_person(a, person, date_col="procedure_date")
    a = keep_in_person_master(a, person)

    a = a.rename(columns={"PERSON_ID": "person_id"})
    return select_columns(a, "procedure_occurrence").drop_duplicates(), invalid
