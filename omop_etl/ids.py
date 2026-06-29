"""OMOP 기본키(occurrence_id) 채번.

각 사건에 다음 규칙으로 정수 surrogate key 를 부여한다::

    ID = {hosp}{YY}{MM}{DD}{domain_code}{seq}
      - hosp        : 병원 구분(1=site1, 2=site2)
      - YY/MM/DD    : 발생일(YY = year-2000)
      - domain_code : 2자리 도메인 코드
      - seq         : 같은 날짜 안에서 1부터 증가하는 일련번호(zero-pad)

도메인별 ``domain_code`` / ``seq_width``:

==============  ============  =========
domain          domain_code   seq_width
==============  ============  =========
visit           "01"          5
condition       "02"          5
drug            "03"          5
procedure       "04"          6
measurement     "05"          6
observation     "06"          6
payer_plan      "07"          5
visit_cost      "08"          5   (※ 순서가 다름, 아래 참조)
note            "09"          6
==============  ============  =========
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def assign_occurrence_id(
    df: pd.DataFrame,
    *,
    id_col: str,
    datetime_col: str,
    date_col: str,
    hosp_col: str = "hosp",
    domain_code: str,
    seq_width: int = 5,
) -> pd.DataFrame:
    """``id_col`` 컬럼에 OMOP occurrence_id 를 채번한다.

    Parameters
    ----------
    datetime_col : 정렬 기준 (예: ``condition_start_datetime``)
    date_col     : 일련번호 리셋 기준 날짜 (예: ``condition_start_date``)
    hosp_col     : 병원 구분 (1=site1, 2=site2)
    domain_code  : 2자리 도메인 코드 (예: ``"02"``)
    seq_width    : 일련번호 zero-pad 자리수
    """
    out = df.sort_values(datetime_col, kind="stable").reset_index(drop=True)

    # 채번 기준 날짜가 결측(NaT)인 행은 유효 ID 를 만들 수 없으므로 제외
    d = pd.to_datetime(out[date_col], errors="coerce")
    if not d.notna().all():
        out = out[d.notna()].reset_index(drop=True)
        d = pd.to_datetime(out[date_col], errors="coerce")

    # 날짜별로 1..N 일련번호 부여(날짜 그룹 직접 사용 → 정렬·결측과 무관하게
    # 같은 날짜 안에서 항상 유일, 따라서 occurrence_id 도 유일).
    seq = out.groupby(d.dt.normalize(), sort=False).cumcount() + 1

    yy = (d.dt.year - 2000).astype(int).map(lambda x: f"{x:02d}")
    mm = d.dt.month.astype(int).map(lambda x: f"{x:02d}")
    dd = d.dt.day.astype(int).map(lambda x: f"{x:02d}")
    hosp = out[hosp_col].astype("Int64").astype(str)
    nn = seq.map(lambda x: f"{x:0{seq_width}d}")

    out[id_col] = (hosp + yy + mm + dd + domain_code + nn).astype("int64")
    return out


def assign_ids_with_counter(
    df: pd.DataFrame,
    counter: dict,
    *,
    id_col: str,
    date_col: str,
    hosp_col: str = "hosp",
    domain_code: str,
    seq_width: int = 6,
) -> pd.DataFrame:
    """스트리밍(청크) 채번. 날짜별 카운터(``counter``)를 청크 사이에 누적해

    청크를 넘나들어도 같은 날짜 안에서 일련번호가 이어지도록(=전역 유일) 한다.
    ``counter`` 는 호출자가 유지하는 dict(날짜→지금까지 발급 수). 제자리 갱신된다.
    """
    out = df.reset_index(drop=True)
    d = pd.to_datetime(out[date_col], errors="coerce")
    keep = d.notna()
    if not keep.all():
        out = out[keep].reset_index(drop=True)
        d = pd.to_datetime(out[date_col], errors="coerce")
    dates = d.dt.normalize()

    base = dates.map(lambda x: counter.get(x, 0))          # 청크 진입 시점의 누적값
    within = out.groupby(dates, sort=False).cumcount() + 1  # 청크 내 순번
    seq = (base.values + within.values)
    for dv, c in dates.value_counts().items():             # 카운터 누적 갱신
        counter[dv] = counter.get(dv, 0) + int(c)

    yy = (d.dt.year - 2000).astype(int).map(lambda x: f"{x:02d}")
    mm = d.dt.month.astype(int).map(lambda x: f"{x:02d}")
    dd = d.dt.day.astype(int).map(lambda x: f"{x:02d}")
    hosp = out[hosp_col].astype("Int64").astype(str)
    nn = pd.Series(seq).map(lambda x: f"{x:0{seq_width}d}")
    out[id_col] = (hosp.values + yy.values + mm.values + dd.values + domain_code + nn.values).astype("int64")
    return out


def assign_id(
    a: pd.DataFrame,
    id_counter: dict | None,
    *,
    id_col: str,
    datetime_col: str,
    date_col: str,
    hosp_col: str = "hosp",
    domain_code: str,
    seq_width: int,
) -> pd.DataFrame:
    """채번 방식 선택: 일반(in-memory) 또는 스트리밍 카운터.

    ``id_counter`` 가 None 이면 전체 채번(:func:`assign_occurrence_id`),
    dict 면 청크 스트리밍 채번(:func:`assign_ids_with_counter`).
    두 방식 모두 같은 형식의 유일한 ID 를 만든다.
    """
    if id_counter is None:
        return assign_occurrence_id(
            a, id_col=id_col, datetime_col=datetime_col, date_col=date_col,
            hosp_col=hosp_col, domain_code=domain_code, seq_width=seq_width)
    return assign_ids_with_counter(
        a, id_counter, id_col=id_col, date_col=date_col,
        hosp_col=hosp_col, domain_code=domain_code, seq_width=seq_width)


def assign_visit_cost_id(
    df: pd.DataFrame,
    *,
    id_col: str = "visit_cost_id",
    nn_series: pd.Series,
    hosp_col: str = "hosp",
    date_col: str = "visit_start_date",
) -> pd.Series:
    """VISIT_COST 전용 ID.

    VISIT_COST 는 ``{YY}{MM}{DD}08{hosp}{nn}`` 으로 **순서가 다르다**
    (hosp 가 코드 뒤에 옴). visit 도메인에서 이미 계산된 ``nn`` 을 재사용한다.
    """
    d = pd.to_datetime(df[date_col])
    yy = (d.dt.year - 2000).map(lambda x: f"{x:02d}")
    mm = d.dt.month.map(lambda x: f"{x:02d}")
    dd = d.dt.day.map(lambda x: f"{x:02d}")
    hosp = df[hosp_col].astype("Int64").astype(str)
    return (yy + mm + dd + "08" + hosp + nn_series.astype(str)).astype("int64")


def filter_person_id_length(
    df: pd.DataFrame, *, person_col: str = "PERSON_ID", length: int = 8
) -> pd.DataFrame:
    """PERSON_ID 자리수 필터.

    유효 환자번호(8자리 정수)만 남긴다.
    """
    pid = pd.to_numeric(df[person_col], errors="coerce")
    keep = pid.notna() & (pid == pid.astype("Int64").astype("float"))
    s = pid.astype("Int64").astype(str)
    keep &= s.str.len().eq(length)
    return df[keep].copy()
