"""방문(visit_occurrence) 매칭.

각 도메인의 사건(진단/약물/노트/관찰/검사)을 방문에 연결한다.
두 가지 매칭 방식을 쓴다.

**2단계 매칭** (condition / drug / note / measurement)
  1) 1차: 같은 환자 + 날짜구간 포함 + ``provider_id`` 일치
  2) 2차: 1차에서 못 붙은 행만 provider 무시하고 날짜구간만으로 매칭
  - 후보가 여럿이면 ``visit_concept_id`` 오름차순(필요시 종료일까지 거리)으로 1건 선택

**1단계 매칭** (observation)
  - provider 조건 없이 날짜구간만으로 매칭, ``visit_concept_id`` 최솟값 선택

두 방식 모두 ``visit_concept_id == 9203`` (응급) 매칭은 NULL 처리하는 옵션이 있다.

도메인별 파라미터
------------------
==============  ===============  =============  =================
domain          window_pre_days  order_by_diff  null_9203
==============  ===============  =============  =================
condition       0                False          (없음)
drug            0                False          2차 매칭
note            7                True           2차 매칭
measurement     7                True           2차(provider 불일치)
observation     0 (1단계)        False          매칭 전체
==============  ===============  =============  =================
"""
from __future__ import annotations

import numpy as np
import pandas as pd

_VISIT_COLS = [
    "visit_occurrence_id",
    "visit_concept_id",
    "visit_start_date",
    "visit_end_date",
    "provider_id",
]


def _dedup_visits(visits: pd.DataFrame, *, person_col: str, with_provider: bool) -> pd.DataFrame:
    """방문 룩업을 (person, start, end[, provider]) 기준으로 중복 제거.

    같은 (person, start, end[, provider]) 조합의 첫 행만 남긴다.
    """
    keys = [person_col, "visit_start_date", "visit_end_date"]
    if with_provider:
        keys.append("provider_id")
    cols = [c for c in [person_col, *_VISIT_COLS] if c in visits.columns]
    v = visits[list(dict.fromkeys(cols))].copy()
    return v.drop_duplicates(subset=keys, keep="first")


# 이벤트를 이 크기로 나눠 처리(방문 3천만 건 규모에서 전체 병합 메모리 폭발 방지)
CHUNK_SIZE = 200_000


def _best_per_event(
    ev_chunk: pd.DataFrame,
    vis: pd.DataFrame,
    *,
    date_col: str,
    person_col: str,
    provider_col: str | None,
    window_pre_days: int,
    order_by_diff: bool,
    use_provider: bool,
) -> pd.DataFrame:
    """청크 내 각 이벤트의 최적 방문 1건 선택. 청크 환자의 방문만 병합한다."""
    persons = ev_chunk[person_col].unique()
    vsub = vis[vis[person_col].isin(persons)]
    if vsub.empty:
        return pd.DataFrame(columns=["_ev", "visit_occurrence_id", "visit_concept_id", "_provider_match"])

    cols = ["_ev", person_col, date_col] + ([provider_col] if use_provider else [])
    cand = ev_chunk[cols].merge(vsub, on=person_col, how="inner")
    if cand.empty:
        return pd.DataFrame(columns=["_ev", "visit_occurrence_id", "visit_concept_id", "_provider_match"])

    d = pd.to_datetime(cand[date_col], errors="coerce")
    vstart = pd.to_datetime(cand["visit_start_date"], errors="coerce")
    vend = pd.to_datetime(cand["visit_end_date"], errors="coerce")
    cand = cand[(vstart - pd.to_timedelta(window_pre_days, unit="D") <= d) & (d <= vend)].copy()
    if cand.empty:
        return pd.DataFrame(columns=["_ev", "visit_occurrence_id", "visit_concept_id", "_provider_match"])

    d = pd.to_datetime(cand[date_col]); vend = pd.to_datetime(cand["visit_end_date"])
    if use_provider:
        cand["_provider_match"] = cand[provider_col].eq(cand["_v_provider"])
    else:
        cand["_provider_match"] = False
    cand["_diff"] = (vend - d).dt.days

    sort_cols, asc = ["_ev"], [True]
    if use_provider:
        sort_cols.append("_provider_match"); asc.append(False)
    sort_cols.append("visit_concept_id"); asc.append(True)
    if order_by_diff:
        sort_cols.append("_diff"); asc.append(True)
    cand = cand.sort_values(sort_cols, ascending=asc)
    return cand.drop_duplicates("_ev", keep="first")[
        ["_ev", "visit_occurrence_id", "visit_concept_id", "_provider_match"]
    ]


def _match_chunked(ev, vis, *, date_col, person_col, provider_col, window_pre_days,
                   order_by_diff, use_provider):
    parts = []
    for s in range(0, len(ev), CHUNK_SIZE):
        parts.append(_best_per_event(
            ev.iloc[s:s + CHUNK_SIZE], vis,
            date_col=date_col, person_col=person_col, provider_col=provider_col,
            window_pre_days=window_pre_days, order_by_diff=order_by_diff,
            use_provider=use_provider,
        ))
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(
        columns=["_ev", "visit_occurrence_id", "visit_concept_id", "_provider_match"])


def match_visit_two_pass(
    events: pd.DataFrame,
    visits: pd.DataFrame,
    *,
    date_col: str,
    person_col: str = "PERSON_ID",
    provider_col: str = "provider_id",
    window_pre_days: int = 0,
    order_by_diff: bool = False,
    null_9203_pass2: bool = False,
) -> pd.DataFrame:
    """2단계 방문 매칭. ``visit_occurrence_id``, ``visit_concept_id`` 컬럼을 붙여 반환.

    메모리 보호를 위해 이벤트를 청크로 나눠 처리한다(결과는 동일).
    """
    ev = events.reset_index(drop=True).copy()
    ev["_ev"] = np.arange(len(ev))

    vis = _dedup_visits(visits, person_col=person_col, with_provider=True)
    vis = vis.rename(columns={provider_col: "_v_provider"})

    best = _match_chunked(
        ev, vis, date_col=date_col, person_col=person_col, provider_col=provider_col,
        window_pre_days=window_pre_days, order_by_diff=order_by_diff, use_provider=True,
    )

    # 2차(provider 불일치) 매칭에서 9203 은 NULL 처리
    if null_9203_pass2 and len(best):
        mask = (~best["_provider_match"]) & best["visit_concept_id"].eq(9203)
        best.loc[mask, "visit_occurrence_id"] = np.nan

    result = ev.merge(
        best[["_ev", "visit_occurrence_id", "visit_concept_id"]], on="_ev", how="left"
    )
    return result.drop(columns="_ev")


def match_visit_single(
    events: pd.DataFrame,
    visits: pd.DataFrame,
    *,
    date_col: str,
    person_col: str = "PERSON_ID",
    null_9203: bool = True,
) -> pd.DataFrame:
    """1단계 방문 매칭 (observation 용). provider 무시, 날짜구간만 사용."""
    ev = events.reset_index(drop=True).copy()
    ev["_ev"] = np.arange(len(ev))

    vis = _dedup_visits(visits, person_col=person_col, with_provider=True)

    best = _match_chunked(
        ev, vis, date_col=date_col, person_col=person_col, provider_col=None,
        window_pre_days=0, order_by_diff=False, use_provider=False,
    )

    if null_9203 and len(best):
        best.loc[best["visit_concept_id"].eq(9203), "visit_occurrence_id"] = np.nan

    result = ev.merge(
        best[["_ev", "visit_occurrence_id", "visit_concept_id"]], on="_ev", how="left"
    )
    return result.drop(columns="_ev")
