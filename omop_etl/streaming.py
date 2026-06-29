"""스트리밍(청크) 처리 — 초대용량 도메인을 메모리에 통째로 올리지 않고 생성.

소스를 청크로 읽어 → 도메인 변환 → 채번(전역 카운터) → 출력에 **증분 저장** 한다.

핵심: 각 도메인의 `build()` 를 **그대로** 청크에 적용한다(`source_override` 로 청크를
넣고 `id_counter` 로 청크를 넘나드는 채번). 즉 스트리밍 결과는 in-memory 결과와
동일한 로직으로 만들어진다(ID 값만 채번 방식 차이).

- :func:`iter_source_chunks` : DB/sas7bdat/csv/xlsx 를 청크로 읽어 컬럼정규화·옵션적용.
- :class:`OutputSink`        : DB(append) 또는 파일(csv append) 로 증분 저장.
- :func:`build_event_stream` : 이벤트 도메인 스트리밍 빌드(공통).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .config import PipelineConfig
from .io import (
    downcast_integers, get_engine, read_db_chunks, read_sas_chunks, write_db,
)
from .domains._common import (
    SOURCE_COLUMNS, _apply_options, _normalize_columns, _source_usecols,
)

# 도메인 → 생성 CDM 테이블명(증분 저장 대상)
EVENT_TABLE = {
    "condition": "condition_occurrence",
    "drug": "drug_exposure",
    "procedure": "procedure_occurrence",
    "note": "note",
    "measurement": "measurement",
    "observation": "observation",
}


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
            csv_path = cfg.path(src.folder, f"{src.dataset}.csv")
            xlsx_path = cfg.path(src.folder, f"{src.dataset}.xlsx")
            if sas_path.exists():
                chunks = read_sas_chunks(sas_path, encoding=cfg.sas_encoding,
                                         usecols=cols, chunksize=chunksize)
            elif csv_path.exists():
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
            self.path = cfg.output_root / f"{name}.csv"
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


def build_event_stream(
    cfg: PipelineConfig,
    name: str,
    person: pd.DataFrame,
    death: pd.DataFrame,
    visit: pd.DataFrame,
    *,
    person_id_xlsx: str | Path,
    mapper=None,
    used_concept_ids: set | None = None,
    chunksize: int = 500_000,
) -> int:
    """이벤트 도메인을 청크 스트리밍으로 생성해 출력에 증분 저장. 저장 행수 반환.

    각 청크를 해당 도메인 ``build(source_override=chunk, id_counter=counter)`` 로
    처리하므로 in-memory 빌드와 동일한 변환을 거친다.
    """
    from .domains import condition, drug, procedure, note, measurement, observation
    builders = {"condition": condition.build, "drug": drug.build,
                "procedure": procedure.build, "note": note.build,
                "measurement": measurement.build, "observation": observation.build}
    builder = builders[name]
    sink = OutputSink(cfg, EVENT_TABLE[name])
    counter: dict = {}
    total = 0

    if name == "observation":
        # 종검/입원 두 그룹을 각각 청크 스트리밍(채번 카운터는 공유)
        for grp in ("exam", "inpatient"):
            for chunk in iter_source_chunks(cfg, cfg.domains[name], group=grp, chunksize=chunksize):
                res = builder(cfg, person, death, visit, person_id_xlsx=person_id_xlsx,
                              mapper=mapper, used_concept_ids=used_concept_ids,
                              source_override=chunk, group=grp, id_counter=counter)
                total += sink.write(res[0] if isinstance(res, tuple) else res)
        return total

    for chunk in iter_source_chunks(cfg, cfg.domains[name], chunksize=chunksize):
        res = builder(cfg, person, death, visit, person_id_xlsx=person_id_xlsx,
                      mapper=mapper, used_concept_ids=used_concept_ids,
                      source_override=chunk, id_counter=counter)
        df = res[0] if isinstance(res, tuple) else res
        total += sink.write(df)
    return total
