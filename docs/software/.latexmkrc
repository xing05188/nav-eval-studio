# latexmk configuration for the software copyright application form.
# Run: latexmk -xelatex copyright.tex  (or `make`)
$pdf_mode = 5;  # XeLaTeX
set_tex_cmds('-synctex=1 -interaction=nonstopmode %O %S');
$xdvipdfmx = 'xdvipdfmx -E -o %D %S';
$max_repeat = 5;

# The document class and its font/def files live in ./style, while the form
# content lives in ./chapters.
ensure_path('TEXINPUTS', './style//');
ensure_path('TEXINPUTS', './chapters//');

$clean_ext = 'aux bbl blg fdb_latexmk fls log out synctex.gz toc xdv';
