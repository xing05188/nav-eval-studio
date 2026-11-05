DOC = copyright
ENGINE ?= -xelatex

.PHONY: all clean cleanall

all: $(DOC).pdf

$(DOC).pdf: $(DOC).tex chapters/copyright_body.tex style/tongjicopyright.sty
	latexmk $(ENGINE) $(DOC).tex

clean:
	latexmk -c $(DOC).tex

cleanall:
	latexmk -C $(DOC).tex
