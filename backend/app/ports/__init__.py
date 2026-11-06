"""端口层：market 与外部世界之间的契约。

只放 Protocol 与 DTO，不 import 任何具体实现；`app/adapters/**` 实现这些端口，
`app/market/**` 只依赖端口。这样替换行情源（OKX / Yahoo / 未来其它）不需要改业务层。
"""
