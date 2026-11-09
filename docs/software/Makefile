# 软件著作权登记三份材料的编译入口
#   make              编译全部（copyright.pdf / design.pdf / source_code.pdf）
#   make copyright    仅申请表
#   make design       仅设计说明书
#   make source       仅源程序
#   make excerpt      重新从项目源码生成源程序摘录（完整文件、不截断）
ENGINE  ?= -xelatex
PYTHON  ?= python3

.PHONY: all copyright design source excerpt clean cleanall

all: copyright.pdf design.pdf source_code.pdf

copyright: copyright.pdf
design: design.pdf
source: source_code.pdf

copyright.pdf: copyright.tex chapters/copyright_body.tex \
               style/tongjicopyright.sty style/tongjithesis.cls
	latexmk $(ENGINE) copyright.tex

# 把 figures/ 下的图片列为依赖；-g 强制 latexmk 重新编译，
# 这样「新增图片 → make design」才会重新求值 \IfFileExists 并把占位框换成真图。
FIGURES := $(wildcard figures/*)
design.pdf: design.tex chapters/design_body.tex \
            style/tongjidesign.sty style/navmeta.tex $(FIGURES)
	latexmk -g $(ENGINE) design.tex

# 代码冻结后运行 `make excerpt` 重新抽取源码；随后 make source 重新编译
excerpt:
	$(PYTHON) tools/gen_source.py

source_code.pdf: source_code.tex chapters/source_body.tex \
                 chapters/source_excerpt.txt style/tongjisource.sty style/navmeta.tex
	latexmk $(ENGINE) source_code.tex

clean:
	latexmk -c copyright.tex
	latexmk -c design.tex
	latexmk -c source_code.tex

cleanall: clean
	latexmk -C copyright.tex
	latexmk -C design.tex
	latexmk -C source_code.tex
