# 门店网络台账管理后台（第一期）· 后端最小实现

登录鉴权、角色数据域、按域查询接口。第二期前端（地图选区、KPI 六卡、台账列表、筛选、详情抽屉、导出）不在本期。

## 环境与运行

纯 **Python 3 标准库**（3.9+），零第三方依赖：SQLite（`sqlite3`）、`http.server`、
`hashlib` / `hmac` / `secrets`、`unittest`、`csv` / `json`。
不依赖百度地图、不依赖 AK、不做 GCJ-02→BD-09 转换（NFR-06）。

```bash
python3 manage.py migrate                       # 建库建表 + v_ledger 视图 + 字典/meta
python3 manage.py seed                          # 载入合成 fixture（非真实底表）
python3 manage.py validate-region --out r.json  # region 全量校验清单（NFR-08 / OPEN-07）
python3 manage.py import-ledger <底表.csv>      # 导入真实底表 CSV（含 DQ 物化）
python3 manage.py test -v                       # 运行 unittest（L1~L5 + AC + HTTP 冒烟）
python3 manage.py report                        # 打印合成 fixture 数字自检
python3 manage.py serve --port 8080             # 启动本地 HTTP 服务
```

也可用 `python3 -m unittest discover -s tests -v`。

配置全部通过 `LEDGER_*` 环境变量覆盖，见 `ledger/config.py`：
`LEDGER_DB_PATH`、`LEDGER_SESSION_TTL`、`LEDGER_IDLE_TTL`、`LEDGER_PBKDF2_ITER`、
`LEDGER_REDACT_METRICS`、`LEDGER_EXPORT_ENABLED`、`LEDGER_AUDIT_RETENTION_DAYS`、
`LEDGER_AUDIT_QUERY_PERMISSION`、`LEDGER_DEMO_PASSWORD`、`LEDGER_LOG_TRACEBACKS`。

## 结构

```
manage.py               CLI 入口
ledger/
  config.py             运行时配置（设计默认值，非业务结论）
  errors.py             统一错误码 + 响应信封
  db.py                 DDL、v_ledger 统一 DQ 视图、region_dict（含 ordinal 陷阱）
  domain.py             DomainContext / 域谓词 / 白名单 / 锁定维度 / 筛选签名
  repository.py         ★ 唯一裁决点：构造必须传 DomainContext，无免域重载
  auth.py               口令哈希、不透明令牌、服务端会话、每请求 role_version 比对
  services.py           Meta / Ledger / Kpi / Export / Audit / Admin
  app.py                路由、统一序列化、redact_metrics 脱敏层、负向契约
  server.py             stdlib http.server 适配器
  etl.py                底表 CSV 导入 / DQ 物化 / validate_region / 合成 fixture
tests/                   L1 单元 / L2 契约 / L3 安全 / L4 一致性 / L5 审计 / AC / HTTP
```

**安全不变量**：任何读请求都经 `AuthMiddleware -> DomainContext -> Repository.where()`，
域谓词在参数化 SQL `WHERE` 中，分页 `COUNT`、KPI 聚合、派生集合、导出集合同源；
客户端传入的 `role` / `domain` / `d_scope` / `region_scope` / `brand_scope` 一律忽略。
总部 `1=1` 也走同一构造器，避免「总部分支」成为绕过口。

## 接口（`/api/v1`）

| 方法 / 路径 | 说明 |
| --- | --- |
| `POST /auth/login` | 账号口令 → 不透明令牌 + 角色/域展示快照 |
| `POST /auth/logout` | 吊销会话，204 |
| `GET /me/domain` | 域元数据（省域/城市/区块清单、锁定维度、默认视野、竞品口径、YTD） |
| `GET /stores` | 台账分页 + 排序 + 白名单筛选 |
| `GET /stores/{id}` | 单店详情 + 逐年经营；域外/不存在统一 403 `OUT_OF_DOMAIN` |
| `GET /kpi` | 服务端聚合（计数、RevPAR 中位 + 有效样本数、多店加权、覆盖率、竞品） |
| `POST /exports` | CSV（UTF-8 BOM、水印、5 000 行上限、越界拒绝整单） |
| `PATCH /admin/users/{id}` | 角色变更（管理端，`role_version+1`） |
| `GET /admin/audit` | 受控审计查询（管理端） |
| `GET /healthz` | 存活，不含业务数据 |

统一信封 `{data, meta, error, trace_id}`。错误码见 `ledger/errors.py`。

**显式不提供**（负向契约，逐一有测试断言 404）：全量字典 `/dict/*`、无分页全量
`/stores/all`、`/exports/all`、角色切换 `/auth/switch-role`、竞品/商圈明细、地图/AK/坐标转换端点。

## 底表 CSV 格式（`import-ledger`）

必需列：`store_id,name,brand,region,province,city`；
可选：`block,lng_gcj02,lat_gcj02,operate_type,status,rooms,occ,adr,revpar,data_version,year`。
导入时执行 DQ-01 物化（越界指标置空）与 DQ-02 死店标记（非在营且近三年无
`store_yearly` 经营记录）。`v_ledger` 视图再做一次兜底（双保险）。

## 重要限制（务必阅读）

- **真实底表未提供**（OPEN-15）：PRD V1.0、原型 HTML、13 258 行门店数据均未随工作区提供。
  `seed` 载入的是**确定性合成 fixture**，仅用于验证域裁决逻辑、派生集合规则、接口契约与
  DQ 口径。它复现了任务书转录数字（13 258 / 2 767 / 544 / 47 726 等），但**不构成
  AC-01~05 已与真实原型逐角色核对的证据**。基线核对须在补齐附件后用 `import-ledger` 重做。
- **基线口径未确认**（OPEN-14）：转录数字是否已含 DQ 死店剔除/越界置空未知；视图是规则实现，
  不是基线承诺。
- **region 校验清单**（OPEN-07）：`validate-region` 会产出「region 为空或非法」与
  「region 为品牌值」清单，须业务确认归属后方可上线；合成 fixture 故意含 3 行非法
  region 死店以验证清单能产出，故报告 `passed=false` 属预期。
- **六项上线阻断**（OPEN-02/03/07/08/14/15）与管理端模型（OPEN-16）均非本节点可关闭；
  按需求「未确认前按默认推进」实现，默认值不等于业务已确认。
- 管理端账号、脱敏切换依据、审计保留期与查询权限均为**设计默认/配置位**；
  生产部署必须替换合成账号与 `LEDGER_DEMO_PASSWORD`，并关闭上述阻断项。
- 单体分层 + SQLite 是最小实现，未做多进程会话缓存、连接池、速率限制、TLS 终止、
  数据库账号级审计表权限隔离（DR-14）；这些属部署/运维层，需在上线前评估。

完整实现说明、改动清单、验证结果与限制见工作区根目录 `implementation.md`。
