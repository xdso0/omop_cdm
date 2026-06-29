"""VISIT 도메인 (visit_occurrence + payer_plan_period + visit_cost).

원본: ``visit/visit_join.sas``.
visit_occurrence_id 채번 시 만든 일련번호(nn)/연월일을 payer_plan_period_id,
visit_cost_id 채번에 재사용한다.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ..cdm_schema import select_columns
from ..config import PipelineConfig
from ..ids import filter_person_id_length
from ..person_filter import (
    apply_cutoff,
    exclude_persons,
    keep_in_person_master,
    load_excluded_persons,
    remove_after_death,
    validate_against_person,
)
from ._common import load_sources


def build(
    cfg: PipelineConfig,
    person: pd.DataFrame,
    death: pd.DataFrame,
    *,
    person_id_xlsx: str | Path,
) -> dict:
    dom = cfg.domains["visit"]
    b1 = load_sources(dom, cfg)

    # ---- 채번: hosp + YYMMDD + '01' + nn(5) ----
    b1 = b1.sort_values("visit_start_time", kind="stable").reset_index(drop=True)
    # 시작일 결측 행은 유효 ID 를 만들 수 없으므로 제외
    _d = pd.to_datetime(b1["visit_start_date"], errors="coerce")
    if not _d.notna().all():
        b1 = b1[_d.notna()].reset_index(drop=True)
    d = pd.to_datetime(b1["visit_start_date"], errors="coerce")
    seq = b1.groupby(d.dt.normalize(), sort=False).cumcount() + 1  # 날짜별 유일 일련번호
    nn = seq.map(lambda x: f"{x:05d}")
    yy = (d.dt.year - 2000).astype(int).map(lambda x: f"{x:02d}")
    mm = d.dt.month.astype(int).map(lambda x: f"{x:02d}")
    dd = d.dt.day.astype(int).map(lambda x: f"{x:02d}")
    hosp = b1["hosp"].astype("Int64").astype(str)
    b1["_nn"], b1["_yy"], b1["_mm"], b1["_dd"] = nn, yy, mm, dd
    b1["visit_occurrence_id"] = (hosp + yy + mm + dd + "01" + nn).astype("int64")

    # ---- 컬럼 설정 ----
    b1["visit_type_concept_id"] = 44818518
    b1["visit_source_concept_id"] = 0
    b1["visit_source_value"] = ""
    # 입원(9202) 이 아니면 admitting_source_concept_id=38004515
    b1["admitting_source_concept_id"] = np.where(
        b1["visit_concept_id"].eq(9202), 0, 38004515
    )
    b1["admitting_source_value"] = ""
    b1["discharge_to_concept_id"] = 0
    b1["discharge_to_source_value"] = ""

    # PERSON_ID 8자리 + 컷오프
    b1 = filter_person_id_length(b1)
    b1 = apply_cutoff(b1, date_col="visit_start_date", cutoff_year=dom.cutoff_year)

    # 사망 후 방문 제거
    b1 = remove_after_death(b1, death, date_col="visit_start_date")

    # 대상자 제외 + 정합성 검증 + 마스터 유지
    excluded = load_excluded_persons(person_id_xlsx)
    b1 = exclude_persons(b1, excluded)
    invalid = validate_against_person(b1, person, date_col="visit_start_date")
    b1 = keep_in_person_master(b1, person)

    # ---- visit_occurrence 본체 ----
    vo = b1.rename(columns={
        "PERSON_ID": "person_id",
        "visit_start_time": "visit_start_datetime",
        "visit_end_time": "visit_end_datetime",
    })
    vo = _add_preceding_visit(vo)
    visit_occurrence = select_columns(vo, "visit_occurrence")

    # ---- payer_plan_period ----
    ppp = pd.DataFrame({
        "person_id": b1["PERSON_ID"].values,
        "payer_plan_period_id": (
            hosp.loc[b1.index] + b1["_yy"] + b1["_mm"] + b1["_dd"] + "07" + b1["_nn"]
        ).astype("int64").values,
        "payer_plan_period_start_date": b1["visit_start_date"].values,
        "payer_plan_period_end_date": b1["visit_end_date"].values,
        "payer_source_value": b1.get("payer_source_value", ""),
        "plan_source_value": b1.get("plan_source_value", ""),
        "family_source_value": "",
    }).drop_duplicates()
    payer_plan_period = select_columns(ppp, "payer_plan_period")

    # ---- visit_cost (id 순서가 다름: YYMMDD 08 hosp nn) ----
    vc = pd.DataFrame({
        "visit_cost_id": (
            b1["_yy"] + b1["_mm"] + b1["_dd"] + "08" + hosp.loc[b1.index] + b1["_nn"]
        ).astype("int64").values,
        "visit_occurrence_id": b1["visit_occurrence_id"].values,
        "payer_plan_period_id": (
            hosp.loc[b1.index] + b1["_yy"] + b1["_mm"] + b1["_dd"] + "07" + b1["_nn"]
        ).astype("int64").values,
    }).drop_duplicates()
    visit_cost = select_columns(vc, "visit_cost")

    return {
        "visit_occurrence": visit_occurrence,
        "payer_plan_period": payer_plan_period,
        "visit_cost": visit_cost,
        "invalid_person_id": invalid,
    }


def _add_preceding_visit(vo: pd.DataFrame) -> pd.DataFrame:
    """preceding_visit_occurrence_id 계산.

    환자별로 visit_start_date 정렬 후, 직전 방문의 종료일이 현재 시작일 이전이면
    그 방문 id 를 직전 방문으로 기록(아니면 0). 원본 SAS retain/lag 로직 대응.
    """
    vo = vo.sort_values(["person_id", "visit_start_date", "visit_end_date"]).reset_index(drop=True)
    prev_id = vo["visit_occurrence_id"].shift()
    prev_end = pd.to_datetime(vo["visit_end_date"].shift())
    same_person = vo["person_id"].eq(vo["person_id"].shift())
    diff = (pd.to_datetime(vo["visit_start_date"]) - prev_end).dt.days
    preceding = np.where(same_person & (diff >= 0), prev_id, 0)
    vo["preceding_visit_occurrence_id"] = pd.Series(preceding).fillna(0).astype("int64")
    return vo.sort_values("visit_occurrence_id").reset_index(drop=True)
