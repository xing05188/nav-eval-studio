# -*- coding: utf-8 -*-
"""生成软著《源程序》文档所需的两个文件。

从项目真实源码中按固定顺序选取片段，拼成 3000 行，按 60 页 × 50 行分页：

    chapters/source_excerpt.txt   3000 行真实代码（不含任何额外说明行）
    chapters/source_body.tex      60 个 \\sourcepage 分页指令

前 30 页为源程序前部（启动入口、应用工厂、配置、基础设施与数据模型），
后 30 页为源程序后部（核心服务、适配器、前端入口/路由/接口与主要视图组件）。

用法（在 docs/software 目录下或任意目录均可）：
    python tools/gen_source.py
代码冻结、需要重新对齐源程序量时重新执行一次即可。
"""
from __future__ import print_function

import io
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOFTWARE_DIR = HERE.parent
ROOT = SOFTWARE_DIR.parent.parent          # 仓库根目录 nav-eval-studio/
OUT = SOFTWARE_DIR / 'chapters'
TARGET_PART = 1500                          # 前/后各 30 页 × 50 行
LINES_PER_PAGE = 50
PART_LINES = TARGET_PART * 2

# (仓库内相对路径, 该文件最多取多少行)；按顺序填充，凑满即止。
FRONT_SPEC = [
    ('run.py', 10000),
    ('backend/app/main.py', 10000),
    ('backend/app/core/config.py', 10000),
    ('backend/app/core/security.py', 10000),
    ('backend/app/core/response.py', 10000),
    ('backend/app/core/events.py', 10000),
    ('backend/app/core/paths.py', 10000),
    ('backend/app/core/logging.py', 10000),
    ('backend/app/db/session.py', 10000),
    ('backend/app/models/__init__.py', 10000),
    ('backend/app/models/task.py', 10000),
    ('backend/app/models/dataset.py', 10000),
    ('backend/app/models/user.py', 10000),
    ('backend/app/models/backup.py', 10000),
    ('backend/app/schemas/task.py', 10000),
    ('backend/app/adapters/base.py', 10000),
    ('backend/app/api/deps.py', 10000),
    ('backend/app/api/auth.py', 10000),
]

BACK_SPEC = [
    ('backend/app/services/scheduler.py', 260),
    ('backend/app/adapters/streamvln_adapter.py', 160),
    ('backend/app/services/analysis_service.py', 120),
    ('frontend/src/main.js', 10000),
    ('frontend/src/App.vue', 10000),
    ('frontend/src/router/index.js', 10000),
    ('frontend/src/api/index.js', 10000),
    ('frontend/src/store/auth.js', 10000),
    ('frontend/src/views/Overview.vue', 300),
    ('frontend/src/components/TrajectoryCanvas.vue', 200),
    ('frontend/src/components/ObservationTimeline.vue', 150),
    ('frontend/src/views/sim/Workbench.vue', 300),
    ('frontend/src/views/replay/Workbench.vue', 10000),
]


def collect(spec, target):
    """按 spec 顺序取行，返回 (行列表, 每行所属文件列表, 每个文件实取行数)。"""
    lines, owners, used = [], [], []
    for rel, limit in spec:
        path = ROOT / rel
        if not path.is_file():
            raise IOError('源码文件不存在: %s' % path)
        raw = io.open(str(path), 'r', encoding='utf-8').read().splitlines()
        taken = 0
        for line in raw[:limit]:
            if len(lines) >= target:
                break
            lines.append(line)
            owners.append(rel)
            taken += 1
        used.append((rel, taken))
        if len(lines) >= target:
            break
    if len(lines) < target:
        raise RuntimeError('选段不足 %d 行，请扩充 SPEC（当前 %d 行）'
                           % (target, len(lines)))
    return lines, owners, used


def main():
    front, owners_f, used_f = collect(FRONT_SPEC, TARGET_PART)
    back, owners_b, used_b = collect(BACK_SPEC, TARGET_PART)
    lines = front + back
    owners = owners_f + owners_b
    assert len(lines) == PART_LINES, len(lines)

    excerpt = OUT / 'source_excerpt.txt'
    with io.open(str(excerpt), 'w', encoding='utf-8', newline='\n') as fh:
        for line in lines:
            fh.write(line + u'\n')

    body = [
        '% 由 tools/gen_source.py 自动生成，请勿手工编辑。',
        '% 共 60 页，每页 50 行，合计 3000 行；第 1--30 页为源程序前部，',
        '% 第 31--60 页为源程序后部。行号在整册中连续编号 1--3000。',
        '%',
        '% 前 30 页选取：',
    ]
    for rel, n in used_f:
        body.append('%%   %-52s %4d 行' % (rel, n))
    body.append('% 后 30 页选取：')
    for rel, n in used_b:
        body.append('%%   %-52s %4d 行' % (rel, n))
    body.append('%')
    for page in range(PART_LINES // LINES_PER_PAGE):
        first = page * LINES_PER_PAGE + 1
        last = first + LINES_PER_PAGE - 1
        hint = owners[page * LINES_PER_PAGE]
        body.append('\\sourcepage{%d}{%s}{%d}{%d}'
                    % (page + 1, hint, first, last))
    with io.open(str(OUT / 'source_body.tex'), 'w', encoding='utf-8',
                 newline='\n') as fh:
        fh.write(u'\n'.join(body) + u'\n')

    backend = sum(1 for o in owners if o.startswith('backend/') or o == 'run.py')
    frontend = sum(1 for o in owners if o.startswith('frontend/'))
    print('source_excerpt.txt: %d 行（后端/入口 %d 行，前端 %d 行）'
          % (len(lines), backend, frontend))
    print('source_body.tex:    %d 页，每页 %d 行'
          % (PART_LINES // LINES_PER_PAGE, LINES_PER_PAGE))


if __name__ == '__main__':
    main()
