"""입출력 유틸리티.

SAS(`*.sas7bdat`), Excel(`*.xlsx`), CSV 를 pandas DataFrame 으로 읽고,
CDM 산출물을 parquet/csv 로 저장한다.

SAS `libname xx 'dir'; data ...; set xx.tbl; run;` 패턴을
:func:`read_sas` 한 번으로 대체한다.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pandas as pd

try:  # pyreadstat 은 SAS 입출력에만 필요 (없어도 xlsx/csv 는 동작)
    import pyreadstat
except ImportError:  # pragma: no cover
    pyreadstat = None


# --------------------------------------------------------------------- #
# 읽기
# --------------------------------------------------------------------- #
def read_sas(path: str | Path, *, encoding: str = "euc-kr") -> pd.DataFrame:
    """SAS `.sas7bdat` 파일을 DataFrame 으로 읽는다.

    한글이 포함된 데이터셋은 보통 ``euc-kr`` 로 저장돼 있다.
    """
    if pyreadstat is None:
        raise ImportError("pyreadstat 가 필요합니다: pip install pyreadstat")
    df, _meta = pyreadstat.read_sas7bdat(str(path), encoding=encoding)
    return df


def read_sas_chunks(
    path: str | Path, *, chunksize: int = 500_000, encoding: str = "euc-kr"
) -> Iterator[pd.DataFrame]:
    """대용량 `.sas7bdat`(수십 GB) 를 청크 단위로 읽는다."""
    if pyreadstat is None:
        raise ImportError("pyreadstat 가 필요합니다: pip install pyreadstat")
    reader = pyreadstat.read_file_in_chunks(
        pyreadstat.read_sas7bdat, str(path), chunksize=chunksize, encoding=encoding
    )
    for df, _meta in reader:
        yield df


def read_excel(path: str | Path, sheet: str | int = 0, **kw) -> pd.DataFrame:
    """Excel 시트를 DataFrame 으로 읽는다 (SAS `proc import ... dbms=xlsx`)."""
    return pd.read_excel(path, sheet_name=sheet, **kw)


def read_table(path: str | Path, **kw) -> pd.DataFrame:
    """확장자로 포맷을 판별해 읽는다 (sas7bdat / xlsx / csv / parquet)."""
    p = Path(path)
    ext = p.suffix.lower()
    if ext == ".sas7bdat":
        return read_sas(p, **kw)
    if ext in {".xlsx", ".xls"}:
        return read_excel(p, **kw)
    if ext == ".csv":
        return pd.read_csv(p, **kw)
    if ext in {".parquet", ".pq"}:
        return pd.read_parquet(p, **kw)
    raise ValueError(f"지원하지 않는 확장자: {ext}")


# --------------------------------------------------------------------- #
# 쓰기
# --------------------------------------------------------------------- #
def write_cdm(df: pd.DataFrame, path: str | Path, *, fmt: str = "parquet") -> Path:
    """CDM 테이블을 저장한다.

    SAS ``data lib.table; set ...; run;`` 의 최종 저장 단계를 대체한다.
    기본은 parquet (대용량·타입 보존). ``fmt='csv'`` 도 가능.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "parquet":
        out = p.with_suffix(".parquet")
        df.to_parquet(out, index=False)
    elif fmt == "csv":
        out = p.with_suffix(".csv")
        df.to_csv(out, index=False, encoding="utf-8-sig")
    elif fmt == "sas7bdat":
        if pyreadstat is None:
            raise ImportError("pyreadstat 가 필요합니다.")
        out = p.with_suffix(".sas7bdat")
        pyreadstat.write_sas7bdat(df, str(out))
    else:
        raise ValueError(f"지원하지 않는 포맷: {fmt}")
    return out
