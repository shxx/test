"""门店网络台账管理后台（第一期）· 服务端最小实现。

纯 Python 标准库（Python 3.9+）：sqlite3 / http.server / hashlib / secrets / unittest。
不依赖百度地图、不依赖 AK、不做坐标转换（NFR-06）。

分层：
    config.py     运行时配置（全部为运维/设计默认值，非业务结论）
    errors.py     统一错误码 + 统一响应信封
    db.py         DDL + v_ledger 统一 DQ 视图 + 连接
    domain.py     DomainContext / 域谓词 / 白名单 / 筛选签名（唯一裁决点的输入）
    repository.py 唯一裁决点：scope() 强制接收 DomainContext，无免域重载
    auth.py       口令哈希、会话、每请求鉴权中间件（role_version）
    services.py   Meta/Ledger/Kpi/Export/Audit/Admin 应用服务
    app.py        HTTP 路由 + 统一序列化 + 脱敏层
    etl.py        底表导入 / DQ 物化 / region 全量校验 / 合成 fixture
"""
