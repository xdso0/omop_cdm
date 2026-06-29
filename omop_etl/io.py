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
# 한글 SAS 파일 인코딩 폴백 순서. 파일마다 euc-kr/cp949 가 섞여 있고
# 일부는 잘못된 바이트가 있어, 주어진 인코딩 → cp949(상위호환) → 자동(None)
# → latin1(최후, 무손실 바이트 매핑) 순으로 시도한다.
def _encoding_candidates(encoding: str | None) -> list:
    seq = [encoding, "cp949", "ms949", None, "latin1"]
    seen, out = set(), []
    for e in seq:
        key = e or "__auto__"
        if key not in seen:
            seen.add(key); out.append(e)
    return out


# --------------------------------------------------------------------- #
def read_sas(path: str | Path, *, encoding: str = "euc-kr") -> pd.DataFrame:
    """SAS `.sas7bdat` 파일을 DataFrame 으로 읽는다.

    한글이 포함된 데이터셋은 보통 ``euc-kr``/``cp949`` 로 저장돼 있다. 지정 인코딩이
    실패하면 자동으로 다른 인코딩으로 재시도한다.
    """
    if pyreadstat is None:
        raise ImportError("pyreadstat 가 필요합니다: pip install pyreadstat")
    last = None
    for enc in _encoding_candidates(encoding):
        try:
            kw = {} if enc is None else {"encoding": enc}
            df, _meta = pyreadstat.read_sas7bdat(str(path), **kw)
            return df
        except Exception as e:  # 인코딩 오류 시 다음 후보로
            last = e
    raise last


def read_sas_chunks(
    path: str | Path, *, chunksize: int = 500_000, encoding: str = "euc-kr"
) -> Iterator[pd.DataFrame]:
    """대용량 `.sas7bdat`(수십 GB) 를 청크 단위로 읽는다."""
    if pyreadstat is None:
        raise ImportError("pyreadstat 가 필요합니다: pip install pyreadstat")
    # 인코딩 후보를 순서대로 시도(첫 청크에서 실패하면 다음 후보)
    last = None
    for enc in _encoding_candidates(encoding):
        try:
            kw = {} if enc is None else {"encoding": enc}
            reader = pyreadstat.read_file_in_chunks(
                pyreadstat.read_sas7bdat, str(path), chunksize=chunksize, **kw
            )
            for df, _meta in reader:
                yield df
            return
        except Exception as e:
            last = e
    raise last


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
