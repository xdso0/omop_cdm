"""스트리밍(청크) 처리 — 초대용량 도메인을 메모리에 통째로 올리지 않고 생성.

소스를 청크로 읽어 → 도메인 변환 → 채번(전역 카운터) → 출력에 **증분 저장** 한다.
measurement 처럼 합치면 RAM 을 넘는 도메인에 사용한다.

핵심
----
- :func:`iter_source_chunks` : DB/sas7bdat/csv/xlsx 를 청크로 읽어 컬럼정규화·옵션적용.
- :class:`OutputSink`        : DB(append) 또는 파일(csv append) 로 증분 저장.
- :func:`build_measurement_stream` : measurement 스트리밍 빌드.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .cdm_schema import select_columns
from .config import PipelineConfig
from .ids import assign_ids_with_counter, filter_person_id_length
from .io import (
    downcast_integers, get_engine, read_db_chunks, read_sas_chunks, write_db,
)
from .person_filter import (
    exclude_persons, keep_in_person_master, load_excluded_persons,
    remove_after_death, validate_against_person,
)
from .visit_match import match_visit_two_pass
from .domains._common import (
    SOURCE_COLUMNS, _apply_options, _normalize_columns, _source_usecols, maybe_map_standard,
)
from .domains.measurement import _preprocess


def iter_source_chunks(cfg: PipelineConfig, domain, *, group=None, chunksize=500_000):
    """도메인의 각 소스를 청크로 읽어 정규화·옵션적용한 DataFrame 을 순차 반환."""
    usecols = SOURCE_COLUMNS.get(domain.name)
    for src in domain.sources:
        opts = src.options or {}
        if group is not None and opts.get("group") != group:
            continue
        cols = _source_usecols(usecols, opts)

        if cfg.source_db:
            chunks = read_db_chunks(src.dataset, get_engine(cfg.source_db),
                                    schema=cfg.source_schema, usecols=cols, chunksize=chunksize)
        else:
            sas_path = cfg.path(src.folder, f"{src.dataset}.sas7bdat")
            if sas_path.exists():
                chunks = read_sas_chunks(sas_path, encoding=cfg.sas_encoding,
                                         usecols=cols, chunksize=chunksize)
            else:
                csv_path = cfg.path(src.folder, f"{src.dataset}.csv")
                xlsx_path = cfg.path(src.folder, f"{src.dataset}.xlsx")
                if csv_path.exists():
                    chunks = pd.read_csv(csv_path, chunksize=chunksize)
                elif xlsx_path.exists():
                    chunks = [pd.read_excel(xlsx_path)]
                else:
                    raise FileNotFoundError(f"원천 없음: {sas_path} (.csv/.xlsx 도 없음)")

        for ch in chunks:
            ch = _normalize_columns(ch)
            ch = _apply_options(ch, src, encoding=cfg.sas_encoding)
            yield downcast_integers(ch)


class OutputSink:
    """CDM 산출물을 증분 저장. DB(첫 청크 replace→이후 append) 또는 CSV append."""

    def __init__(self, cfg: PipelineConfig, name: str):
        self.cfg = cfg
        self.name = name
        self._started = False
        if not cfg.output_db:
            self.path = (cfg.output_root / f"{name}.csv")
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, df: pd.DataFrame) -> int:
        if df is None or len(df) == 0:
            return 0
        if self.cfg.output_db:
            write_db(df, self.name, get_engine(self.cfg.output_db),
                     schema=self.cfg.output_schema,
                     if_exists="replace" if not self._started else "append")
        else:
            df.to_csv(self.path, mode="w" if not self._started else "a",
                      header=not self._started, index=False, encoding="utf-8-sig")
        self._started = True
        return len(df)


def build_measurement_stream(
    cfg: PipelineConfig,
    person: pd.DataFrame,
    death: pd.DataFrame,
    visit: pd.DataFrame,
    *,
    person_id_xlsx: str | Path,
    mapper=None,
    used_concept_ids: set | None = None,
    chunksize: int = 500_000,
) -> int:
    """measurement 를 청크 스트리밍으로 생성해 출력에 증분 저장. 저장 행수 반환."""
    dom = cfg.domains["measurement"]
    excluded = load_excluded_persons(person_id_xlsx)
    sink = OutputSink(cfg, "measurement")
    counter: dict = {}
    total = 0

    for ch in iter_source_chunks(cfg, dom, chunksize=chunksize):
        a = _preprocess(ch)
        if a.empty:
            continue
        a = maybe_map_standard(a, cfg, "measurement", mapper, used_concept_ids)
        a = filter_person_id_length(a)
        a = exclude_persons(a, excluded)
        a = remove_after_death(a, death, date_col="measurement_date")
        a = keep_in_person_master(a, person)
        if a.empty:
            continue
        a = assign_ids_with_counter(a, counter, id_col="measurement_id",
                                    date_col="measurement_date",
                                    domain_code=dom.domain_code, seq_width=dom.seq_width)
        a = match_visit_two_pass(a, visit, date_col="measurement_date", **dom.visit_match)
        a["visit_detail_id"] = a["visit_occurrence_id"]
        a = a.rename(columns={"PERSON_ID": "person_id",
                              "measurement_time": "measurement_datetime"})
        out = select_columns(a, "measurement")
        total += sink.write(out)
    return total
