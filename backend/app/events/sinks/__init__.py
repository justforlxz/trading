"""投递通道：把告警送到用户能看见的地方。

`base` 定义协议与投递台账，`registry` 是唯一的通道注册表，`browser` 把告警推给
订阅了 `alerts` 的浏览器连接，`telegram` 与 `webhook` 把告警推出进程；后两者的请求
形状与有界重试共用 `http`，配置读取方式在 `config`。
"""

__all__: list[str] = []
