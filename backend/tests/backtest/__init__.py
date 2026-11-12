"""回测域的测试包。

本目录有 `__init__.py`，与 `tests/api/`、`tests/opportunity/` 一致：测试目录做成包之后，
同名测试模块（`test_metrics` / `test_service`）按包路径区分，不会与 `tests/market`、
`tests/relations` 里的同名文件在 pytest 收集阶段撞成同一个顶层模块。
"""
