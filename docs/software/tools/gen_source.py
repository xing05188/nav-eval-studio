# -*- coding: utf-8 -*-
"""生成软著《源程序》文档所需的两个文件。

从项目真实源码中按固定顺序收录**完整源文件**，不做任何截断：

    chapters/source_excerpt.txt   约 3200 行真实代码（不含任何额外说明行）
    chapters/source_body.tex      每页 50 行的 \\sourcepage 分页指令

总行数由清单中所有文件的实际行数决定，不凑整、不切文件；最后一个文件
完整写完即结束。分页按每页 50 行连续排，最后一页不足 50 行时自然收尾，
总页数由脚本计算后写入 source_body.tex。

用法（在 docs/software 目录下或任意目录均可）：
    python tools/gen_source.py
需要增减行数时，在 SPEC 末尾增删**完整文件**即可，不要对单个文件做行数限制。
"""
from __future__ import print_function

import io
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOFTWARE_DIR = HERE.parent
ROOT = SOFTWARE_DIR.parent.parent          # 仓库根目录 nav-eval-studio/
OUT = SOFTWARE_DIR / 'chapters'
LINES_PER_PAGE = 50

# 按源程序从前到后的自然顺序排列；全部为完整文件，不截断。
# 后端：启动入口、应用工厂、配置、鉴权、数据库、ORM 模型、适配器协议与实现、调度器；
# 前端：入口、根组件、路由、接口封装、状态管理、工具函数与主要可视化组件。
SPEC = [
    'run.py',
    'backend/app/main.py',
    'backend/app/core/config.py',
    'backend/app/core/security.py',
    'backend/app/core/response.py',
    'backend/app/core/events.py',
    'backend/app/db/session.py',
    'backend/app/models/__init__.py',
    'backend/app/models/task.py',
    'backend/app/models/dataset.py',
    'backend/app/models/user.py',
    'backend/app/models/backup.py',
    'backend/app/adapters/base.py',
    'backend/app/adapters/streamvln_adapter.py',
    'backend/app/services/scheduler.py',
    'frontend/src/main.js',
    'frontend/src/App.vue',
    'frontend/src/router/index.js',
    'frontend/src/api/index.js',
    'frontend/src/store/auth.js',
    'frontend/src/utils/format.js',
    'frontend/src/components/BaseChart.vue',
    'frontend/src/components/LineChart.vue',
    'frontend/src/components/MemoryTimeline.vue',
    'frontend/src/components/FrameViewer.vue',
]


def main():
    lines, owners, used = [], [], []
    for rel in SPEC:
        path = ROOT / rel
        if not path.is_file():
            raise IOError('源码文件不存在: %s' % path)
        raw = io.open(str(path), 'r', encoding='utf-8').read().splitlines()
        lines.extend(raw)
        owners.extend([rel] * len(raw))
        used.append((rel, len(raw)))

    total = len(lines)
    pages = (total + LINES_PER_PAGE - 1) // LINES_PER_PAGE
    last_page_lines = total - (pages - 1) * LINES_PER_PAGE

    excerpt = OUT / 'source_excerpt.txt'
    with io.open(str(excerpt), 'w', encoding='utf-8', newline='\n') as fh:
        for line in lines:
            fh.write(line + u'\n')

    body = [
        '% 由 tools/gen_source.py 自动生成，请勿手工编辑。',
        '%% 清单内每个源文件均完整收录，未做任何截断；合计 %d 行。' % total,
        '%% 每页 %d 行，共 %d 页，最后一页 %d 行自然收尾；'
        % (LINES_PER_PAGE, pages, last_page_lines),
        '%% 行号在整册中连续编号 1--%d。' % total,
        '%',
        '% 收录文件（按出现顺序，全部完整）：',
    ]
    for rel, n in used:
        body.append('%%   %-52s %4d 行' % (rel, n))
    body.extend([
        '%',
        '\\setsourcetotalpages{%d}' % pages,
        '%',
    ])
    for page in range(pages):
        first = page * LINES_PER_PAGE + 1
        last = min(first + LINES_PER_PAGE - 1, total)
        hint = owners[page * LINES_PER_PAGE]
        body.append('\\sourcepage{%d}{%s}{%d}{%d}'
                    % (page + 1, hint, first, last))
    with io.open(str(OUT / 'source_body.tex'), 'w', encoding='utf-8',
                 newline='\n') as fh:
        fh.write(u'\n'.join(body) + u'\n')

    backend = sum(1 for o in owners if o.startswith('backend/') or o == 'run.py')
    frontend = sum(1 for o in owners if o.startswith('frontend/'))
    print('source_excerpt.txt: %d 行（后端/入口 %d 行，前端 %d 行）'
          % (total, backend, frontend))
    print('source_body.tex:    %d 页，每页 %d 行，最后一页 %d 行'
          % (pages, LINES_PER_PAGE, last_page_lines))


if __name__ == '__main__':
    main()
