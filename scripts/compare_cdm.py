"""생성 CDM ↔ 기존 CDM 대조 + 매핑 갭 리포트.

이 코드로 만든 결과와, 기존(예: SAS 로 만들어 DB 에 적재한) CDM 을 비교한다.
occurrence_id 는 surrogate 라 값이 다르므로 **자연키**(person_id+날짜+source_value)로
비교하고, **source_value 별 표준 매핑**을 양쪽 비교해 갭을 찾는다.

사용 예 (둘 다 DB):
    python scripts/compare_cdm.py --config config/pipeline.postgres.local.yaml \
        --domain condition \
        --base-url postgresql+psycopg2://u:p@host:5432/olddb --base-schema sas \
        --base-table condition_occurrence

생성본(gen)은 기본적으로 config 의 output_db / EVENT_TABLE 에서 읽는다(또는 --gen-* 지정).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from omop_etl.config import load_config  # noqa: E402
from omop_etl.io import get_engine, read_db, read_table  # noqa: E402
from omop_etl.streaming import EVENT_TABLE  # noqa: E402

# 도메인별 자연키 / concept / source_value 컬럼
SPEC = {
    "condition":   (["person_id", "condition_start_date", "condition_source_value"],
                    "condition_concept_id", "condition_source_value"),
    "drug":        (["person_id", "drug_exposure_start_date", "drug_source_value"],
                    "drug_concept_id", "drug_source_value"),
    "procedure":   (["person_id", "procedure_date", "procedure_source_value"],
                    "procedure_concept_id", "procedure_source_value"),
    "measurement": (["person_id", "measurement_date", "measurement_source_value"],
                    "measurement_concept_id", "measurement_source_value"),
    "observation": (["person_id", "observation_date", "observation_source_value"],
                    "observation_concept_id", "observation_source_value"),
    "note":        (["person_id", "note_date"], None, None),
}


def _load_side(url, schema, table, file, cfg, default_table):
    if file:
        return read_table(file)
    if url:
        return read_db(table or default_table, get_engine(url), schema=schema)
    # 기본: config 의 output_db
    if cfg and cfg.output_db:
        return read_db(table or default_table, get_engine(cfg.output_db), schema=cfg.output_schema)
    raise SystemExit("gen 소스를 못 찾음: --gen-url/--gen-file 또는 config.output_db 필요")


def _norm_keys(df, keys):
    out = df.copy()
    out.columns = [c.lower() for c in out.columns]
    for k in keys:
        if "date" in k:
            out[k] = pd.to_datetime(out[k], errors="coerce").dt.strftime("%Y-%m-%d")
        else:
            out[k] = out[k].astype(str)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="생성 CDM ↔ 기존 CDM 대조/갭 리포트")
    ap.add_argument("--config", default=None)
    ap.add_argument("--domain", required=True, choices=list(SPEC))
    ap.add_argument("--gen-url"); ap.add_argument("--gen-schema"); ap.add_argument("--gen-table"); ap.add_argument("--gen-file")
    ap.add_argument("--base-url"); ap.add_argument("--base-schema"); ap.add_argument("--base-table"); ap.add_argument("--base-file")
    ap.add_argument("--out", default=None, help="갭 리포트 저장 폴더(기본: <output_root>/gap)")
    args = ap.parse_args()

    cfg = load_config(args.config) if args.config else None
    table = EVENT_TABLE.get(args.domain, args.domain)
    keys, concept, source = SPEC[args.domain]

    gen = _norm_keys(_load_side(args.gen_url, args.gen_schema, args.gen_table, args.gen_file, cfg, table), keys)
    base = _norm_keys(_load_side(args.base_url, args.base_schema, args.base_table, args.base_file, None, table), keys)
    print(f"[{args.domain}] 생성 {len(gen):,} rows / 기존 {len(base):,} rows\n")

    # 1) 자연키 행 매칭
    gk = gen[keys].drop_duplicates(); bk = base[keys].drop_duplicates()
    m = gk.merge(bk, on=keys, how="outer", indicator=True)
    both = (m["_merge"] == "both").sum()
    only_g = (m["_merge"] == "left_only").sum()
    only_b = (m["_merge"] == "right_only").sum()
    print(f"[자연키] 공통 {both:,} / 생성에만 {only_g:,} / 기존에만 {only_b:,}")

    if concept is None:
        print("(note: concept 비교 없음)"); return

    # 2) source_value 별 표준 매핑 비교 (0이 아닌 concept 우선)
    def smap(df):
        d = df[[source, concept]].copy()
        d[concept] = pd.to_numeric(d[concept], errors="coerce").fillna(0).astype("int64")
        d = d.sort_values(concept, ascending=False).drop_duplicates(source)  # 비0 우선
        return d.set_index(source)[concept]
    gm, bm = smap(gen), smap(base)
    comp = pd.DataFrame({"gen": gm, "base": bm}).fillna(0).astype("int64")
    comp["gen_ok"] = comp["gen"] != 0
    comp["base_ok"] = comp["base"] != 0
    agree = ((comp["gen"] == comp["base"]) & comp["gen_ok"]).sum()
    print(f"\n[매핑] source_value {len(comp):,}종 | 양쪽 동일매핑 {agree:,}")
    print(f"  - 기존O·생성X (Python 놓침)  : {((~comp['gen_ok']) & comp['base_ok']).sum():,}")
    print(f"  - 기존X·생성O (Python 개선)  : {(comp['gen_ok'] & (~comp['base_ok'])).sum():,}")
    print(f"  - 양쪽 다름(둘다 매핑)        : {(comp['gen_ok'] & comp['base_ok'] & (comp['gen']!=comp['base'])).sum():,}")
    print(f"  - 공통 미매핑(둘다 0)         : {((~comp['gen_ok']) & (~comp['base_ok'])).sum():,}")

    # 3) 갭 리포트 저장
    outdir = Path(args.out) if args.out else ((cfg.output_root if cfg else Path(".")) / "gap")
    outdir.mkdir(parents=True, exist_ok=True)
    comp.reset_index().to_csv(outdir / f"{args.domain}_mapping_compare.csv", index=False, encoding="utf-8-sig")
    miss = comp[(~comp["gen_ok"]) & comp["base_ok"]].reset_index()
    miss.to_csv(outdir / f"{args.domain}_python_missing.csv", index=False, encoding="utf-8-sig")
    common = comp[(~comp["gen_ok"]) & (~comp["base_ok"])].reset_index()
    common.to_csv(outdir / f"{args.domain}_common_unmapped.csv", index=False, encoding="utf-8-sig")
    print(f"\n갭 리포트 저장: {outdir}")
    print(f"  - {args.domain}_python_missing.csv  ← 기존엔 있는데 Python 이 놓친 코드(보완표 채울 후보)")
    print(f"  - {args.domain}_common_unmapped.csv ← 양쪽 다 미매핑(신규 매핑 필요)")


if __name__ == "__main__":
    main()
