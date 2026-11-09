# 计算机软件著作权登记材料（LaTeX）

本目录存放《码极客具身导航多模态流式评测与诊断平台 V1.0》的三份登记材料，全部用 XeLaTeX 编译：

| 材料 | 编译入口 | 输出 | 说明 |
| --- | --- | --- | --- |
| 计算机软件著作权登记申请表 | `copyright.tex` | `copyright.pdf`（3 页） | 沿用原有 `tongjithesis` 表单模板，已按本项目预填 |
| 设计说明书 | `design.tex` | `design.pdf`（约 45 页） | 十二章正文 + 48 处插图位置 + 插图清单 |
| 源程序 | `source_code.tex` | `source_code.pdf`（60 页） | 前 30 页 + 后 30 页，每页 50 行，合计 3000 行 |

## 编译

在 `docs/software/` 目录下执行（需要 TeX Live 2021+，本机已验证 TeX Live 2026）：

```bash
make                 # 三份一起编译
make copyright       # 申请表
make design          # 设计说明书
make source          # 源程序
make excerpt         # 代码冻结后重新抽取 3000 行源码
make clean           # 清理中间文件
```

也可单独执行 `latexmk -xelatex design.tex`。若系统 `python3` 版本过旧，用
`make excerpt PYTHON=/home/zjr/miniconda3/envs/streamvln-kb/bin/python` 指定解释器。

## 文件组织

```
copyright.tex                      申请表编译入口（原有模板）
chapters/copyright_body.tex        申请表正文与预填数据
design.tex                         设计说明书编译入口（封面/目录/附录开关）
chapters/design_body.tex           设计说明书十二章正文
chapters/figure_spec.tex           附录 A 插图清单 + 附录 B 全部 PlantUML 语法与截图要求
source_code.tex                    源程序文档编译入口
chapters/source_excerpt.txt        从真实源码拼接的 3000 行代码（脚本生成）
chapters/source_body.tex           60 个 \sourcepage 分页指令（脚本生成）
tools/gen_source.py                源程序摘录生成脚本
figures/                           图片目录（按插图清单命名放入）
style/tongjicopyright.sty          申请表版式
style/tongjidesign.sty             说明书版式、\figph 占位/自动替换命令
style/tongjisource.sty             源程序版式（60 页口径）
style/navmeta.tex                  设计说明书与源程序共用的软件名称/版本
style/tongjithesis.cls 等           申请表依赖的最小文档类副本
```

名称与版本统一在 `style/navmeta.tex`；申请表是独立表单，改名时需同步核对
`chapters/copyright_body.tex`。三处口径当前均为「码极客具身导航多模态流式评测与诊断平台 / V1.0」，
源程序量 25600 行（后端约 13750 行 + 前端约 11860 行），开发完成日期 2026-11-09。

## 申请表

模板与填写方式未改动，字段说明见原模板（`\tjcrchk` / `\tjcrunchk` / `\tjcrcont` 等）。
已复核：软件全称、简称、版本号、源程序量、开发/运行环境、主要功能（约 580 字，符合 500–1300 字要求）、
技术特点与另两份材料一致；提交前请复核著作权人、日期与证明材料。

## 设计说明书

正文按《设计说明书目录.md》的十二章组织：项目背景、软件功能介绍、软件特性介绍、运行环境、
系统总结构、各子系统、关键机制、接口设计、人机接口、测试计划、出错处理、系统维护。
内容取自 `docs/01`~`docs/10`、`README.md` 与真实源码，未虚构功能。

### 插图如何补齐（重要）

正文每处插图都用 `\figph{键}{文件名}{图题}{占位提示}` 排版：

- **当前状态**：`figures/` 里没有图片，PDF 中对应位置是带虚线的占位框，框内写明该图的
  文件名与内容提示，图号与交叉引用均已自动生成，不影响排版。
- **补齐方式**：按 `chapters/figure_spec.tex` 附录 A 清单给出的**确切文件名**出图，
  放进 `figures/` 后重新 `make design`（该目标会强制完整重编译），`\figph` 会自动用
  `\includegraphics` 替换占位框，**不需要修改正文任何一行 LaTeX**。
  单独编译时请用 `latexmk -g -xelatex design.tex`，否则增量编译不会检测到新增图片。
- **图怎么画**：附录 B 给出全部 20 张结构图的可编译 PlantUML 源码
  （组件图 1、部署图 1、ER 图 1、类图 1、活动图 13、状态图 1、时序图 2），
  以及 28 张界面截图的取图步骤、画面要素和 28 段 `salt` 线框语法（可作临时占位）。
  附录 B 默认不编入 PDF（`design.tex` 中 `\figspecinpdffalse`），需要校对语法时改为
  `\figspecinpdftrue` 重新编译即可；语法本身始终保留在模板文件中。

图片命名规则：截图 `ui_NN_名称.png`，结构图 `arch_NN_*` / `flow_NN_*` / `state_NN_*` / `seq_NN_*`；
全小写英文与下划线，扩展名 `.png`（矢量图可用 `.pdf`）。渲染结构图示例：

```bash
# 复制 figure_spec.tex 中对应 @startuml ... @enduml 保存为同名 .puml 后
plantuml -tpng figures/flow_01_eval_task.puml     # 生成 flow_01_eval_task.png
```

清单中优先级 A 为软著材料必需的 14 张，B 为建议，C 为可选增强；时间有限时先完成 A 类。

## 源程序

按软著口径组织为 60 页：第 1–30 页为源程序前部，第 31–60 页为源程序后部，
每页严格 50 行，行号 1–3000 连续，页眉为软件全称 + 版本号，页脚为当前源码文件与页码。

`tools/gen_source.py` 从项目真实源码按固定清单顺序抽取 3000 行
（后端/入口约 2040 行、前端约 960 行），覆盖启动入口、应用工厂、配置、鉴权、数据库模型、
调度器、适配器、指标分析，以及前端入口、路由、API 封装、状态管理和主要视图组件。
摘录文件是纯代码拼接，不含额外说明行；代码冻结后运行 `make excerpt` 即可同步。
若要调整选段或前后端配比，修改脚本顶部的 `FRONT_SPEC` / `BACK_SPEC` 即可，
`TARGET_PART` 与 `LINES_PER_PAGE` 决定页数口径（当前 1500 + 1500 行）。

## 提交前检查

1. `make` 三份 PDF 均可编译，`design.pdf` 中不再出现「待补插图」占位框。
2. 附录 A 的图号与正文图题一一对应；若不需要绘制语法，保持 `\figspecinpdffalse`。
3. 申请表、设计说明书封面、源程序页眉三处的软件全称与版本号一致。
4. 源程序量为 3000 行（60 页 × 50 行），与申请表「源程序量 25600 行」不矛盾：
   前者是提交的页面代码，后者是项目源码总量。
