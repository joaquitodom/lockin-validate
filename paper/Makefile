# Build the working paper.
# Requirements: a TeX distribution with pdflatex + bibtex (TeX Live, MiKTeX) and
# Python 3 with matplotlib for the figures. Alternative: `tectonic main.tex`.
# Compiled with MiKTeX pdflatex + bibtex on 2026-10-27 (19 pages, 0 errors).

PY ?= python

all: main.pdf

figures: figures/fig_is_vs_oos.pdf figures/fig_gap_cascade.pdf

figures/fig_is_vs_oos.pdf figures/fig_gap_cascade.pdf: figures/make_figures.py
	$(PY) -I figures/make_figures.py

main.pdf: main.tex refs.bib figures
	pdflatex -interaction=nonstopmode main.tex
	bibtex main
	pdflatex -interaction=nonstopmode main.tex
	pdflatex -interaction=nonstopmode main.tex

clean:
	rm -f main.aux main.bbl main.blg main.log main.out main.toc

.PHONY: all figures clean
