"""OBSERVATION 도메인.

원천이 두 그룹으로 나뉜다.
  - exam(종검)     : visit 매칭 안 함
  - inpatient(입원): visit 1단계 매칭(9203 NULL)
두 그룹을 합친 뒤 채번/필터를 적용한다.
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
    remove_after_death,
    validate_against_person,
)
from ..ids import assign_id
from ..visit_match import match_visit_single
from ._common import load_sources


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
    group: str | None = None,
    id_counter: dict | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    dom = cfg.domains["observation"]

    if source_override is not None:
        # 스트리밍: 한 그룹의 청크. inpatient 만 visit 단일 매칭.
        if group == "inpatient":
            a = match_visit_single(source_override, visit, date_col="observation_date", null_9203=True)
        else:
            a = source_override.copy()
            if "visit_occurrence_id" not in a.columns:
                a["visit_occurrence_id"] = pd.NA
    else:
        exam = load_sources(dom, cfg, group="exam")
        inpatient = load_sources(dom, cfg, group="inpatient")
        inpatient = match_visit_single(inpatient, visit, date_col="observation_date", null_9203=True)
        if "visit_occurrence_id" not in exam.columns:
            exam["visit_occurrence_id"] = pd.NA
        a = pd.concat([inpatient, exam], ignore_index=True)

    a = apply_cutoff(a, date_col="observation_date", cutoff_year=dom.cutoff_year)
    a = a[a["PERSON_ID"].notna()]

    a = assign_id(
        a, id_counter,
        id_col="observation_id",
        datetime_col="observation_time",
        date_col="observation_date",
        domain_code=dom.domain_code,
        seq_width=dom.seq_width,
    )
    a["visit_detail_id"] = a["visit_occurrence_id"]
    a = a.rename(columns={"observation_time": "observation_datetime"})

    a = remove_after_death(a, death, date_col="observation_date")
    # PERSON_ID 자리수 > 1 만 유지
    a = a[a["PERSON_ID"].astype("Int64").astype(str).str.len() > 1]
    a["observation_concept_id"] = a["observation_concept_id"].fillna(0)

    excluded = load_excluded_persons(person_id_xlsx)
    a = exclude_persons(a, excluded)
    invalid = validate_against_person(a, person, date_col="observation_date")
    a = keep_in_person_master(a, person)

    a = a.rename(columns={"PERSON_ID": "person_id"})
    return select_columns(a, "observation").drop_duplicates(), invalid
