"""业务域的只读适配器：把域 service 的结果转成 `app.ports.ai_reads` 的成型数据。

只有这一层可以 import 各业务域；`app.ai` 只认端口协议。
"""
