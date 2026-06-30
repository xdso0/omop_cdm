"""적재된 DB 테이블의 중복 제거(자연키 기준, 한 건만 남김).

스트리밍 적재는 청크 경계를 넘는 중복을 메모리에서 못 잡으므로, 적재 후 DB 에서
한 번 정리한다. PostgreSQL 의 ctid + row_number 로 자연키마다 1행만 남기고 삭제.
"""
from __future__ import annotations

from sqlalchemy import text

from .cdm_schema import CDM_COLUMNS, natural_key


def dedupe_db_table(engine, table: str, *, schema: str | None = None) -> int:
    """DB 테이블에서 자연키 중복을 제거한다. 삭제된 행 수 반환."""
    if table not in CDM_COLUMNS:
        return 0
    keys = natural_key(table)
    fq = f'"{schema}"."{table}"' if schema else f'"{table}"'
    part = ", ".join(f'"{c}"' for c in keys)
    sql = text(f"""
        DELETE FROM {fq} a
        USING (
            SELECT ctid, row_number() OVER (PARTITION BY {part} ORDER BY ctid) AS rn
            FROM {fq}
        ) d
        WHERE a.ctid = d.ctid AND d.rn > 1
    """)
    with engine.begin() as c:
        res = c.execute(sql)
        return res.rowcount or 0
