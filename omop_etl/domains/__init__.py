"""도메인별 OMOP CDM ETL 모듈.

각 모듈은 ``build(pipeline_cfg) -> pd.DataFrame`` 형태의 함수를 제공한다.
의존 순서: person/care_site/provider → death → visit → 나머지.
"""
