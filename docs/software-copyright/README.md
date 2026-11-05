# 计算机软件著作权登记申请表

本目录存放《计算机软件著作权登记申请表》的 LaTeX 版式与填写内容，供本软件申请软著时使用。

## 编译

```bash
make
# 或
latexmk -xelatex copyright.tex
```

输出 `copyright.pdf`。清理中间文件用 `make clean`，清理含 PDF 的全部产物用 `make cleanall`。

## 文件

| 文件                            | 说明                                     |
| ------------------------------- | ---------------------------------------- |
| `copyright.tex`               | 编译入口                                 |
| `chapters/copyright_body.tex` | 表单正文与预填数据                       |
| `style/tongjicopyright.sty`   | 表单页面、表格与填表命令                 |
| `style/tongjithesis.cls` 等   | 从 TongjiThesis 模板带出的最小文档类依赖 |

> `style/tongjithesis.cls` 是独立副本：本表不使用参考文献，为兼容 TeX Live 2021
> 自带的旧版 `gbt7714`，副本中去掉了 `bibpunct=half` 选项并使用
> `gbt7714-numeric.bst`；新版 TeX Live 下同样可编译，不影响本表版式。

## 填写

修改 `chapters/copyright_body.tex` 中每个字段的第二个参数即可。

- `\tjcrchk{...}`：已勾选
- `\tjcrunchk{...}`：未勾选
- `\tjcrblank{3cm}`：打印后手写的空白下划线
- `\tjcrred{...}`：红色字数限制提示
- `\tjcrsection{...}`：跨两列的分节行
- `\tjcrcont{...}` / `\tjcrlastcont{...}`：长文本续行，便于跨页

> 当前内容按《码极客具身智能体能力管理软件 V1.0》的申请表预填；申请本软件时请整体替换为 `nav-eval-studio` 对应的软件名称、功能、技术特点等信息。
