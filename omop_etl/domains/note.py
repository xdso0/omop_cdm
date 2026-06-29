"""NOTE 도메인.

특이점: ① 컷오프가 [cutoff_start, cutoff_end] 날짜 구간, ② visit 2단계 매칭
(window 7일, 종료일 거리 우선, 9203 NULL), ③ 텍스트 정제($$$$ 제거 후 따옴표 래핑).
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
from ._common import load_sources


def build(
    cfg: PipelineConfig,
    person: pd.DataFrame,
    death: pd.DataFrame,
    visit: pd.DataFrame,
    *,
    person_id_xlsx: str | Path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    dom = cfg.domains["note"]
    a = load_sources(dom, cfg)

    # 날짜구간 컷오프
    lo = pd.Timestamp(dom.extra.get("cutoff_start", "2001-01-01"))
    hi = pd.Timestamp(dom.extra.get("cutoff_end", "2025-12-31"))
    d = pd.to_datetime(a["note_date"])
    a = a[(d >= lo) & (d <= hi)].copy()

    # 채번
    a = assign_occurrence_id(
        a,
        id_col="note_id",
        datetime_col="note_datetime",
        date_col="note_date",
        domain_code=dom.domain_code,
        seq_width=dom.seq_width,
    )

    # visit 매칭
    a = match_visit_two_pass(a, visit, date_col="note_date", **dom.visit_match)
    a["visit_detail_id"] = a["visit_occurrence_id"]

    # 사망후 제거 + PERSON_ID 8자리
    a = remove_after_death(a, death, date_col="note_date")
    a = filter_person_id_length(a)

    # 텍스트 정제: $$$$ 및 중복 따옴표 제거 후 큰따옴표로 감싸기
    a = _clean_text(a)

    excluded = load_excluded_persons(person_id_xlsx)
    a = exclude_persons(a, excluded)
    invalid = validate_against_person(a, person, date_col="note_date")
    a = keep_in_person_master(a, person)

    a = a.rename(columns={"PERSON_ID": "person_id"})
    return select_columns(a, "note").drop_duplicates(), invalid


def _clean_text(a: pd.DataFrame) -> pd.DataFrame:
    obj_cols = a.select_dtypes(include="object").columns
    for c in obj_cols:
        s = a[c]
        mask = s.notna() & s.ne("")
        cleaned = (
            s[mask].astype(str).str.replace("$$$$", "", regex=False).str.replace('""', "", regex=False)
        )
        a.loc[mask, c] = '"' + cleaned + '"'
    return a
