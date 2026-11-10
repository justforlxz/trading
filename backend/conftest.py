"""pytest 根装配：在任何 `app.*` 导入之前补上本地数据库地址。

`app.main` 在导入时就构造配置，缺 `DATABASE_URL` 会直接报错，因此这一步必须发生在
用例导入应用之前。

地址由测试提供（与假 OKX 的约定一致：本地地址归测试），所以跑测试不要求仓库根有
`.env`；要在别的库上跑，显式给环境变量 `DATABASE_URL=...`（已存在的值优先）。
"""

import os

DEFAULT_DATABASE_URL = "postgresql+psycopg://trading:trading@127.0.0.1:5432/trading"

os.environ.setdefault("DATABASE_URL", DEFAULT_DATABASE_URL)
