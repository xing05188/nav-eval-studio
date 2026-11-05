# 具身导航多模态流式评测与诊断软件 V1.0

面向连续环境视觉语言导航（VLN-CE）模型的**评测、诊断与回放**一体化平台。

本仓库为软件著作权登记主体，配套毕业设计课题《基于多模态流式感知与时空记忆的视觉语言导航研究》。

## 快速运行

### 环境要求

| 组件 | 要求 | 本机可用路径 |
| --- | --- | --- |
| Python | 3.9+（建议 3.10+，已验证 3.9.23 可运行） | `/home/zjr/miniconda3/envs/streamvln-kb/bin/python` |
| Node.js | 18+（用于构建/开发前端） | `/home/zjr/StreamingVLA/tools/node-v20.18.0-linux-x64/bin` |
| GPU | 仅真实 StreamVLN 评测需要；离线 Mock 演示无需 GPU | — |

> 本机系统默认 `python3` 是 3.4.3，**不能**用于本项目；请使用上表中的解释器。
> Node 不在默认 `PATH`，构建前端前需先 `export PATH=/home/zjr/StreamingVLA/tools/node-v20.18.0-linux-x64/bin:$PATH`。

### 安装依赖

```bash
cd /home/zjr/nav-eval-studio

# 后端（本机 conda 环境已安装，可跳过）
/home/zjr/miniconda3/envs/streamvln-kb/bin/python -m pip install -r requirements.txt

# 前端（若 frontend/node_modules 已存在，只需执行 build）
export PATH=/home/zjr/StreamingVLA/tools/node-v20.18.0-linux-x64/bin:$PATH
cd frontend && npm install && npm run build && cd ..
```

`npm run build` 会生成 `frontend/dist`，后端会自动托管它，无需额外 Web 服务器。

### 启动服务

```bash
cd /home/zjr/nav-eval-studio
/home/zjr/miniconda3/envs/streamvln-kb/bin/python run.py --no-browser
```

默认监听 `0.0.0.0:8080`（见 `config/default.yaml`）。启动后：

| 入口 | 地址 |
| --- | --- |
| 应用首页 | `http://127.0.0.1:8080/` |
| 接口文档（Swagger） | `http://127.0.0.1:8080/docs` |
| 健康检查 | `http://127.0.0.1:8080/health` |

默认账号：`admin / admin123`（管理员）、`operator / operator123`（算法工程师）、`viewer / viewer123`（只读）。

首次启动会自动建库 `storage/eval.db`、执行表迁移、写入种子数据，并**自动同步一次备份库**；
之后后台守护按配置间隔监视备份目录变化做增量导入。VS Code 远程开发时在「端口」面板转发 `8080` 即可访问。

后台常驻与停止：

```bash
nohup /home/zjr/miniconda3/envs/streamvln-kb/bin/python run.py --no-browser \
  > storage/server.log 2>&1 &
pgrep -af "run.py --no-browser"          # 查看进程
pkill -f "run.py --no-browser"           # 停止
```

### 启动参数与环境变量

| 参数 | 说明 |
| --- | --- |
| `--host` / `--port` | 覆盖监听地址 / 端口，默认取配置文件 |
| `--config <path>` | 指定 YAML 配置文件 |
| `--no-browser` | 启动后不自动打开浏览器（服务器建议加上） |
| `--reload` | 后端代码热重载，开发时使用 |

| 环境变量 | 说明 |
| --- | --- |
| `NAVEVAL_CONFIG` | 配置文件路径（等价于 `--config`） |
| `NAVEVAL_HOST` / `NAVEVAL_PORT` | 覆盖监听地址 / 端口 |
| `NAVEVAL_WORK_DIR` | 覆盖工作目录 |
| `NAVEVAL_IMPORT_ROOT` | 覆盖备份库绑定目录 |

配置优先级：**环境变量 > `config/default.yaml` > 内置默认值**。修改 YAML 后需重启服务；
「系统 → 备份库导入」页面里的自动同步开关保存在 `setting` 表，修改后立即生效。

### 前端开发模式（可选）

需同时开两个终端：

```bash
# 终端 1：后端
cd /home/zjr/nav-eval-studio && \
  /home/zjr/miniconda3/envs/streamvln-kb/bin/python run.py --no-browser

# 终端 2：Vite 开发服务器（/api 代理到 127.0.0.1:8080）
export PATH=/home/zjr/StreamingVLA/tools/node-v20.18.0-linux-x64/bin:$PATH
cd /home/zjr/nav-eval-studio/frontend && npm run dev      # 0.0.0.0:5173
```

改前端源码后：开发模式自动热更新；生产模式执行 `npm run build` 后刷新即可，
**静态资源由后端运行时读取，不需要重启后端**；改后端代码才需要重启。
若 `frontend/dist` 不存在，首页会显示含构建提示的占位页。

### 运行检查与常见问题

```bash
curl -s http://127.0.0.1:8080/health     # {"status":"ok","version":"1.0.0"}
tail -f storage/logs/app.log             # 应用日志（后台启动时看 storage/server.log）
ss -ltnp | grep 8080                    # 端口占用
```

| 现象 | 处理 |
| --- | --- |
| `command not found: npm/node` | 按上文 `export PATH=...` |
| 语法报错 / `from __future__ import annotations` 失败 | 用了系统 `python3`(3.4)，改用表中 conda 解释器 |
| 端口被占用 | `python run.py --port 9000`，或先停掉旧进程 |
| 页面空白或仍是旧界面 | 执行 `npm run build` 后强制刷新（Ctrl+Shift+R）清缓存 |
| 接口 404 / 新功能不生效 | 后端代码有更新，重启服务 |
| 数据库被锁 | 检查是否有多个服务进程；SQLite 为单写 WAL 模式，勿在运行时直接删 `eval.db` |

## 定位

把"跑一次 VLN 评测"从命令行脚本变成可视化、可复现、可追溯的工程流程：

1. **数据与配置**：登记数据集、生成 smoke/subset 切分、多源观测对齐检查、严格因果切片导出。
2. **评测调度**：配置模板化、任务队列、实时日志、断点续跑、资源采样。
3. **推理与回放**：模型适配层、逐步单帧推理、轨迹回放、记忆窗口与空间裁剪可视化。
4. **分析与诊断**：多任务指标对比、配对 bootstrap 显著性、失败归因、报告导出。
5. **资产同步**：备份库中的数据集、场景、模型、历史结果与资料文件自动导入平台并持续增量同步。

## 功能一览

| 模块 | 主要能力 |
| --- | --- |
| 数据资产 | 数据集登记/扫描、Episode 检索、观测时间轴、质量校验、三类切分、因果切片导出 |
| 模型档案 | 登记/编辑、可用性探测、配置模板；「自动配置」从 `checkpoints` 补齐代码/权重路径与 `torchrun` 启动器 |
| 评测执行 | 任务创建与配置快照、队列/并发/GPU 互斥、SSE 实时监控、暂停/恢复/取消/重跑、Mock 与 StreamVLN 双适配器 |
| 历史结果 | 把 `results/<实验>/streamvln/result.json` 还原为可回放任务；结果仍在写入时保持「运行中」并增量刷新进度 |
| 备份库导入 | 五类数据自动同步、扫描预览、强制覆盖、运行时开关、资料索引检索 |
| 分析诊断 | 指标对比、消融矩阵、配对 bootstrap、失败归因、报告中心 |
| 轨迹回放 | 第一视角帧、观测时间轴、记忆窗口与俯视轨迹四区联动 |
| 系统 | 用户管理、操作审计、系统设置与 GPU 状态、统一应用图标与设计系统 |

## 界面与交互约定

- **评测任务列表**：含「创建时间」列，默认按时间**最新在前**排列，点击列头可切换为最早在前。
- **运行中状态**：备份库导入的外部评测，结果文件在 `running_grace_s`（默认 600 秒）内仍有写入时显示「运行中」并按实际条数显示进度；停止写入后自动转为「已完成」。
- **模型档案页**：「自动配置」按钮可扫描预览并配置模型；服务启动时也会自动配置。
- **系统 → 备份库导入**：查看绑定目录与各类别数量、扫描预览、立即导入、开关自动同步（无需重启）。
- **图标**：`frontend/public/favicon.png` / `favicon.ico`，同时用于浏览器标签、侧边栏与登录页。

## 设计约束

| 约束 | 说明 |
| --- | --- |
| 离线可演示 | 无 GPU、无数据集时，通过 `MockAdapter` 读取已有结果目录，全流程可跑通并截图 |
| 不含数据与权重 | 软件只登记本地路径，不随包分发数据集或模型权重 |
| 因果性可验证 | 输入白名单 + 运行时断言，禁止访问 t 之后观测 |
| 单机可交付 | SQLite + 单进程 `python run.py`，前端 dist 由 FastAPI 托管 |
| 模型无关 | 通过 Adapter 协议对接 StreamVLN 等外部推理后端，不内嵌其源码 |

## 技术栈

- 后端：Python 3.9+ / FastAPI / SQLAlchemy 2.0 / SQLite(WAL) / Uvicorn / Pydantic v2 / PyYAML
- 前端：Vue 3 / Vite 5 / Pinia / Vue Router 4 / Element Plus / ECharts / Canvas
- 调度：自研轻量队列（asyncio + 子进程），不依赖 Redis、Celery
- 打包：`python run.py` 单入口，前端 dist 由 FastAPI 托管

## 目录结构

```
backend/app/     FastAPI 应用：api / services / models / schemas / adapters / db / core / utils
config/          default.yaml、models.yaml、metrics.yaml
frontend/        Vue 3 源码 src/、静态图标 public/、构建产物 dist/
docs/            设计文档、软著材料与开发待办
storage/         运行时数据：eval.db、runs/、reports/、logs/、cache/、exports/
run.py           单入口启动脚本
requirements.txt 后端依赖清单
```

`storage/` 与 `frontend/dist/` 由 `.gitignore` 忽略，不属于源码交付内容。

## 备份库自动导入

`config/default.yaml` 的 `import` 段可绑定 StreamVLN 备份仓库（默认 `/home/zjr/StreamVLN-kaggle-backup`）。
服务启动后自动同步一次，并按 `auto_interval_s` 监视目录变化做增量导入；也可在
「系统 → 备份库导入」页面扫描预览、立即导入或运行时开关自动同步（无需重启）。

| 类别 | 来源 | 落库结果 |
| --- | --- | --- |
| 数据集 | `data/datasets/<family>/<split>` | `dataset` + `episode`，大体积训练数据只登记路径 |
| 场景资源 | `data/scene_datasets/**/*.glb` | `backup_asset` 场景索引 |
| 模型档案 | `checkpoints/<权重目录>` | 自动配置 `model_profile` 的代码/权重路径、torchrun 启动器、默认参数并探测可用性；模型档案页也可手动触发 |
| 评测结果 | `results/<实验>/streamvln/result.json` | 复用历史产物导入，生成 `eval_task` 与产物；结果仍在写入时标记为「运行中」并增量同步进度 |
| 其他资料 | `config/`、`scripts/`、`logs/`、`research/`、结果附件等 | `backup_asset` 文件索引（只登记路径，不复制大文件） |

导入以 `source_key + signature` 幂等，重复执行只处理新增或变化的对象，不会覆盖手工登记的数据集。
`dry_run` 预览只扫描不写库；训练/大规模轨迹数据（默认 `scan_exclude: [train, envdrop, scalevln]`）
与超过 `scan_limit_mb` 的目录仅登记，可在数据集页手动扫描。
评测结果文件在 `running_grace_s`（默认 600 秒）内仍有写入时，任务保持「运行中」并按结果条数刷新进度，
停止写入后自动转为「已完成」；这类外部评测不受服务重启的中断标记影响。相关接口：
`GET/POST /api/import/backup`、`PUT /api/import/backup/auto`、`GET /api/import/backup/assets`。
运行时开关保存在 `setting` 表（`backup_auto_enabled` / `backup_auto_interval_s` /
`backup_import_root` / `backup_auto_sections`），也可用环境变量 `NAVEVAL_IMPORT_ROOT` 覆盖绑定目录。

## 文档索引

| 文档 | 内容 |
| --- | --- |
| [docs/01-需求与功能清单.md](docs/01-需求与功能清单.md) | 用户场景、功能清单（F 编号）、非功能需求、边界 |
| [docs/02-数据库设计.md](docs/02-数据库设计.md) | ER 关系、完整 DDL、字段说明、状态机 |
| [docs/03-接口设计.md](docs/03-接口设计.md) | REST 接口清单、SSE 事件、回放数据结构 |
| [docs/04-目录结构与代码规划.md](docs/04-目录结构与代码规划.md) | 目录树、分层职责、行数预算、关键实现要点 |
| [docs/05-软著说明书草稿.md](docs/05-软著说明书草稿.md) | 设计说明书七章草稿、申请表功能简介、截图表 |
| [docs/06-开发计划.md](docs/06-开发计划.md) | 里程碑、验收判据、风险 |
| [docs/todo.md](docs/todo.md) | 收尾事项与测试待办 |
| [docs/software-copyright/](docs/software-copyright/) | 计算机软件著作权登记申请表 LaTeX 模板与编译说明 |

## 当前状态与已知限制

已完成并在本机端到端验证：建库/迁移与登录鉴权、数据集与切分、任务调度与双适配器、
分析与报告、轨迹回放、备份库自动导入（数据集/场景/模型/结果/资料）、历史结果的运行中增量同步、
模型自动配置、任务时间列与默认排序、全站视觉体系与应用图标。

已知限制：

- StreamVLN 适配器按官方脚本整段执行 `eval_split`，数据库切分只用于结果对齐与统计，无法把子集参数透传给上游（上游没有该开关）。
- 断点续跑以 episode 为粒度：服务重启后**由本平台调度**的任务标记失败，可通过「重跑失败项」继续；备份库导入的外部评测不受影响。
- 训练/大规模轨迹数据默认只登记路径不解析 episode，需在数据集页手动扫描。
- 仓库暂无自动化测试（见 [docs/todo.md](docs/todo.md)）。
