# 计算机软件著作权登记材料（LaTeX）

本目录存放《码极客具身导航评测与诊断软件 V1.0》的三份登记材料，全部用 XeLaTeX 编译：

| 材料 | 编译入口 | 输出 | 说明 |
| --- | --- | --- | --- |
| 计算机软件著作权登记申请表 | `copyright.tex` | `copyright.pdf`（3 页） | 沿用原有 `tongjithesis` 表单模板，已按本项目预填 |
| 设计说明书 | `design.tex` | `design.pdf`（31 页） | 十二章正文 + 18 幅插图，无附录 |
| 源程序 | `source_code.tex` | `source_code.pdf`（60 多页） | 完整源文件顺序、每页 50 行，最后一页自然收尾，合计 3000 多行 |

## 编译

在 `docs/software/` 目录下执行（需要 TeX Live 2021+，本机已验证 TeX Live 2026）：

```bash
make                 # 三份一起编译
make copyright       # 申请表
make design          # 设计说明书
make source          # 源程序
make excerpt         # 代码冻结后重新抽取源码（完整文件、不截断）
make clean           # 清理中间文件
```

也可单独执行 `latexmk -xelatex design.tex`。若系统 `python3` 版本过旧，用
`make excerpt PYTHON=/home/zjr/miniconda3/envs/streamvln-kb/bin/python` 指定解释器。

## 文件组织

```
copyright.tex                      申请表编译入口（原有模板）
chapters/copyright_body.tex        申请表正文与预填数据
design.tex                         设计说明书编译入口（封面/目录/十二章正文）
chapters/design_body.tex           设计说明书十二章正文
chapters/figure_spec.tex           插图绘制参考（PlantUML 语法与取图步骤，不编入 PDF）
source_code.tex                    源程序文档编译入口
chapters/source_excerpt.txt        从真实源码拼接的 3000 多行完整代码（脚本生成）
chapters/source_body.tex           \sourcepage 分页指令与总页数（脚本生成）
tools/gen_source.py                源程序摘录生成脚本
figures/                           图片目录（按命名规则放入）
style/tongjicopyright.sty          申请表版式
style/tongjidesign.sty             说明书版式、\figph 占位/自动替换命令
style/tongjisource.sty             源程序版式（每页 50 行、总页数动态）
style/navmeta.tex                  设计说明书与源程序共用的软件名称/版本
style/tongjithesis.cls 等           申请表依赖的最小文档类副本
```

名称与版本统一在 `style/navmeta.tex`；申请表是独立表单，改名时需同步核对
`chapters/copyright_body.tex`。三处口径当前均为「码极客具身导航评测与诊断软件 / V1.0」，
源程序量 25600 行（后端约 13750 行 + 前端约 11860 行），开发完成日期 2026-11-09。

## 申请表

模板与填写方式未改动，字段说明见原模板（`\tjcrchk` / `\tjcrunchk` / `\tjcrcont` 等）。
已复核：软件全称、简称、版本号、源程序量、开发/运行环境、主要功能（约 580 字，符合 500–1300 字要求）、
技术特点与另两份材料一致；提交前请复核著作权人、日期与证明材料。

## 设计说明书

正文按《设计说明书目录.md》的十二章组织：项目背景、软件功能介绍、软件特性介绍、运行环境、
系统总结构、各子系统、关键机制、接口设计、人机接口、测试计划、出错处理、系统维护。
内容取自 `docs/01`~`docs/10`、`README.md` 与真实源码，未虚构功能。

### 插图状态

正文已按 `figures/` 中实际出图的图片精简，**共 18 幅，图号 1–18 连续**：

- 界面截图 10 张：`ui_01`、`ui_02`、`ui_03`、`ui_06`、`ui_07`、`ui_12`、`ui_14`、`ui_18`、`ui_19`、`ui_23`；
- 结构图 8 张：`arch_01_system_overview` 与 `flow_01`–`flow_07`。

未截图的界面截图与次要结构图（部署图、ER 图、类图、状态图、时序图，以及测试、维护、出错处理等流程）的图位已删除，正文引用同步清理；原附录已删除，PDF 中不再有附录。

插图仍用 `\figph{键}{文件名}{图题}{占位提示}` 排版：文件存在时直接嵌入，缺失时画虚线占位框，图号由 LaTeX 自动连续编号。后续如需补图，把 PNG 按命名规则放进 `figures/`，在正文相应位置加一行 `\figph` 后执行 `make design`（该目标强制完整重编译）即可，图号自动重排。

绘图参考保留在 `chapters/figure_spec.tex`（不编入 PDF）：8 张结构图的可编译 PlantUML 源码与 10 张截图的取图步骤。如确需把该参考编入 PDF，在 `design.tex` 的 `\end{document}` 前加 `\appendix` 与 `\input{chapters/figure_spec}`。

图片命名规则：截图 `ui_NN_名称.png`，结构图 `arch_NN_*` / `flow_NN_*`；全小写英文与下划线，扩展名 `.png`（矢量图可用 `.pdf`）。渲染结构图示例：

```bash
# 复制 figure_spec.tex 中对应 @startuml ... @enduml 保存为同名 .puml 后
plantuml -tpng figures/flow_01_eval_task.puml     # 生成 flow_01_eval_task.png
```

## 源程序

按完整源文件顺序连续排版：每页 50 行，最后一页不足 50 行时自然收尾，
不凑固定页数、不截断任何文件；行号从 1 连续编到实际总行数。
页眉为软件全称 + 版本号，页脚为当前源码文件与「第 X 页 / 共 N 页」，
N 由生成脚本按实际行数写入。

`tools/gen_source.py` 按固定清单从项目真实源码收录**完整文件**
（当前 3000 多行、60 多页，后端/入口约 2300 行、前端约 950 行），
覆盖启动入口、应用工厂、配置、鉴权、数据库会话与 ORM 模型、适配器协议与
StreamVLN / Mock 实现、任务调度器，以及前端入口、路由、API 封装、状态管理、
工具函数与主要可视化组件。最后一个文件完整写完即结束，不存在半截代码。

摘录文件是纯代码拼接，不含额外说明行；代码冻结后运行 `make excerpt` 即可同步。
需要增减行数时，在脚本的 `SPEC` 末尾增删完整文件即可，不要对单个文件设行数上限；
`LINES_PER_PAGE`（当前 50）决定每页行数，总页数自动计算。

## 提交前检查

1. `make` 三份 PDF 均可编译，`design.pdf` 的 18 幅插图全部嵌入、图号 1–18 连续、无占位框。
2. 设计说明书无附录；绘图参考独立保存在 `chapters/figure_spec.tex`，不随 PDF 提交。
3. 申请表、设计说明书封面、源程序页眉三处的软件全称与版本号一致。
4. 源程序量为 3000 多行（60 多页 × 50 行，最后一页自然收尾），与申请表
   「源程序量 25600 行」不矛盾：前者是提交的页面代码，后者是项目源码总量。
