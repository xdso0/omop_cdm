"""전체 OMOP CDM ETL 파이프라인 실행기.

의존 순서대로 도메인을 빌드하고 산출물을 저장한다::

    person → care_site/provider → death → visit
           → condition / drug / procedure / observation / note / measurement

사용법::

    python -m scripts.run_pipeline --config config/pipeline.yaml
    python -m scripts.run_pipeline --domains person visit condition
    python -m scripts.run_pipeline --provider-xlsx <provider>.xlsx

원본 데이터(.sas7bdat/.xlsx)는 mapping_root 아래에 있어야 한다.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 패키지 루트를 path 에 추가 (scripts/ 에서 직접 실행 대비)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from omop_etl.config import PipelineConfig, load_config  # noqa: E402
from omop_etl.io import write_cdm, write_db, get_engine  # noqa: E402
from omop_etl.vocabulary import VocabStore, export_used_vocab  # noqa: E402
from omop_etl.streaming import EVENT_TABLE  # noqa: E402
from omop_etl.domains import (  # noqa: E402
    care_site,
    condition,
    death,
    drug,
    measurement,
    note,
    observation,
    person,
    procedure,
    provider,
    visit,
)

# 도메인 → mapping_root 하위 폴더(여기에 person_id.xlsx 가 있음)
_FOLDER = {
    "person": "person",
    "death": "death",
    "visit": "visit",
    "condition": "condition",
    "drug": "drug",
    "procedure": "procedure",
    "observation": "observation",
    "note": "note",
    "measurement": "measurement",
}


def _pid_xlsx(cfg: PipelineConfig, domain: str) -> Path:
    # 제외/보정 대상자 목록은 모든 도메인이 중앙 PERSON/person_id.xlsx(Sheet2)에서 읽는다.
    # (각 도메인 폴더의 person_id.xlsx 는 검증결과 출력용일 뿐 입력 아님)
    return cfg.path(_FOLDER["person"], "person_id.xlsx")


def _save(cfg: PipelineConfig, df, name: str) -> None:
    from omop_etl.cdm_schema import dedupe, CDM_COLUMNS
    if name in CDM_COLUMNS:
        df = dedupe(df, name)          # 자연키 중복 제거(id만 다른 동일 사건 1건으로)
    if cfg.output_db:
        # 같은 CDM 테이블을 재실행 시 교체(replace), 그 외 도메인 산출은 append
        write_db(df, name, get_engine(cfg.output_db), schema=cfg.output_schema,
                 if_exists="replace")
        print(f"  저장(DB): {name}  ({len(df):,} rows) → {cfg.output_schema or ''}.{name}")
    else:
        out = write_cdm(df, cfg.output_root / name, fmt=cfg.output_format)
        print(f"  저장: {name}  ({len(df):,} rows) → {out}")


def run(cfg: PipelineConfig, domains: list[str], provider_xlsx: str | None,
        pseudo_id_path: str | None, use_vocab: bool = True) -> None:
    cache: dict = {}

    # Athena vocabulary 매핑 준비
    mapper = None
    used_concept_ids: set = set()
    if use_vocab and cfg.vocab_root is not None and cfg.vocab_mappings:
        mapper = VocabStore(
            vocab_root=cfg.vocab_root,
            release=cfg.athena_release,
            cache_root=cfg.vocab_cache_root,
        )
        print(f"[vocab] Athena release={cfg.athena_release}  root={cfg.vocab_root}")

    def need(dep: str):
        if dep not in cache:
            raise RuntimeError(f"'{dep}' 가 먼저 빌드돼야 합니다. --domains 순서를 확인하세요.")
        return cache[dep]

    for dom in domains:
        print(f"[빌드] {dom}")
        if dom == "person":
            res = person.build(cfg, person_id_xlsx=_pid_xlsx(cfg, "person"),
                               pseudo_id_path=pseudo_id_path)
            # 다운스트림 조인은 PERSON_ID(대문자) 키를 사용한다.
            cache["person"] = res["person"].rename(columns={"person_id": "PERSON_ID"})
            _save(cfg, res["person"], "person")
            if res["person_m"] is not None:
                _save(cfg, res["person_m"], "person_m")

        elif dom == "care_site":
            _save(cfg, care_site.build(provider_xlsx), "care_site")

        elif dom == "provider":
            _save(cfg, provider.build(provider_xlsx), "provider")

        elif dom == "death":
            df, _inv = death.build(cfg, need("person"), person_id_xlsx=_pid_xlsx(cfg, "death"))
            cache["death"] = df.rename(columns={"person_id": "PERSON_ID"})
            _save(cfg, df, "death")

        elif dom == "visit":
            res = visit.build(cfg, need("person"), need("death"),
                              person_id_xlsx=_pid_xlsx(cfg, "visit"))
            cache["visit"] = res["visit_occurrence"].rename(columns={"person_id": "PERSON_ID"})
            _save(cfg, res["visit_occurrence"], "visit_occurrence")
            _save(cfg, res["payer_plan_period"], "payer_plan_period")
            _save(cfg, res["cost"], "cost")

        elif dom in EVENT_TABLE:
            # 이벤트 도메인: stream_domains 에 있으면 청크 스트리밍, 아니면 in-memory
            if dom in cfg.stream_domains:
                from omop_etl.streaming import build_event_stream
                n = build_event_stream(
                    cfg, dom, need("person"), need("death"), need("visit"),
                    person_id_xlsx=_pid_xlsx(cfg, dom),
                    mapper=mapper, used_concept_ids=used_concept_ids, chunksize=cfg.chunksize)
                print(f"  저장(스트리밍): {EVENT_TABLE[dom]}  ({n:,} rows)")
                if cfg.output_db:   # 청크 경계 넘는 중복을 DB 에서 정리
                    from omop_etl.dedupe import dedupe_db_table
                    d = dedupe_db_table(get_engine(cfg.output_db), EVENT_TABLE[dom],
                                        schema=cfg.output_schema)
                    print(f"    중복 제거: {d:,} 행 삭제")
            else:
                builder = {"condition": condition.build, "drug": drug.build,
                           "procedure": procedure.build, "note": note.build,
                           "measurement": measurement.build,
                           "observation": observation.build}[dom]
                df, _ = builder(cfg, need("person"), need("death"), need("visit"),
                                person_id_xlsx=_pid_xlsx(cfg, dom),
                                mapper=mapper, used_concept_ids=used_concept_ids)
                _save(cfg, df, EVENT_TABLE[dom])

        else:
            print(f"  (알 수 없는 도메인: {dom} — 건너뜀)")

    # 사용한 vocabulary 정리 (DB 적재용 서브셋)
    if mapper is not None and used_concept_ids:
        print(f"[vocab] 사용 concept {len(used_concept_ids):,}건 → vocab 서브셋 저장")
        paths = export_used_vocab(cfg.vocab_root, used_concept_ids, cfg.used_vocab_root)
        for k, v in paths.items():
            print(f"  {k}: {v}")


ALL_DOMAINS = [
    "person", "care_site", "provider", "death", "visit",
    "condition", "drug", "procedure", "observation", "note", "measurement",
]


def main() -> None:
    ap = argparse.ArgumentParser(description="OMOP CDM ETL")
    ap.add_argument("--config", default=None, help="pipeline.yaml 경로")
    ap.add_argument("--domains", nargs="*", default=ALL_DOMAINS,
                    help="빌드할 도메인 (의존 순서 유지). 기본: 전체")
    ap.add_argument("--provider-xlsx", default=None,
                    help="care_site/provider 빌드용 provider 엑셀")
    ap.add_argument("--pseudo-id", default=None, help="가명 ID 매핑(PID) 파일 경로")
    ap.add_argument("--no-vocab", action="store_true",
                    help="Athena 표준 매핑 비활성화(원천 concept_id 그대로 사용)")
    args = ap.parse_args()

    cfg = load_config(args.config)
    print(f"mapping_root = {cfg.mapping_root}")
    print(f"output_root  = {cfg.output_root}  (format={cfg.output_format})")
    run(cfg, args.domains, args.provider_xlsx, args.pseudo_id, use_vocab=not args.no_vocab)
    print("완료.")


if __name__ == "__main__":
    main()
