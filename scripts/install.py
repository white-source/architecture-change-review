#!/usr/bin/env python3
"""Install a standard Agent Skill for Codex, Claude Code, ZCode, DeepSeek Harness.

Project-only by default. Optional hooks and instructions need explicit CLI flags.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import sys

SKILL = 'architecture-change-review'
ROOT = Path(__file__).resolve().parent.parent
PLATFORMS = ['codex', 'claude', 'zcode', 'deepseek']


def same(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return False


def put_json(path: Path, doc: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def merge_hooks(path: Path, event_hooks: dict, wrapper='hooks', enabled=False):
    data = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    if wrapper == 'hooks':
        events = data.setdefault('hooks', {})
    else:
        hooks = data.setdefault('hooks', {})
        if enabled:
            hooks['enabled'] = True
        events = hooks.setdefault('events', {})
    for evt, item in event_hooks.items():
        dest = events.setdefault(evt, [])
        token = 'architecture-change-review/scripts/hook_adapter.py'
        positions = [i for i,x in enumerate(dest) if token in json.dumps(x, ensure_ascii=False)]
        if positions:
            # Refresh the command path but keep other users' unrelated hooks.
            dest[positions[0]] = item
            for pos in reversed(positions[1:]):
                del dest[pos]
            continue
        dest.append(item)
    put_json(path, data)


def bash_command(path: Path, client: str, event: str) -> str:
    # Use absolute paths for predictable behavior from nested working dirs.
    return f'{shlex.quote(sys.executable)} {shlex.quote(str(path))} --platform {client} --event {event}'


def hook_item(client: str, event: str, script: Path):
    if client == 'codex':
        h = {'type': 'command', 'command': bash_command(script,client,event),
             'timeout': 20, 'statusMessage': 'Checking architecture changes'}
        if event == 'post':
            return {'matcher': 'Bash|apply_patch|Write|Edit', 'hooks': [h]}
        return {'hooks': [h]}
    if client == 'claude':
        h = {'type': 'command', 'command': bash_command(script,client,event),
             'timeout': 20}
        if event == 'post':
            return {'matcher': 'Write|Edit|MultiEdit|Bash|NotebookEdit', 'hooks': [h]}
        return {'hooks': [h]}
    if client == 'zcode':
        h = {'type': 'process', 'command': sys.executable,
             'args': [str(script), '--platform',client,'--event',event],
             'enabled': True, 'timeoutMs': 20000}
        if event == 'post':
            return {'matcher': 'Write|Edit|Bash', 'hooks': [h]}
        return {'hooks': [h]}
    raise ValueError(client)


def merge_instruction(path: Path):
    start = '<!-- architecture-change-review:start -->'
    end = '<!-- architecture-change-review:end -->'
    content = (ROOT / 'integrations' / 'AGENTS-snippet.md').read_text(encoding='utf-8').strip()
    old = path.read_text(encoding='utf-8') if path.exists() else ''
    if start in old:
        left = old.split(start)[0]
        right = old.split(end, 1)[1] if end in old else ''
        updated = left + start + '\n' + content + '\n' + end + right
    else:
        updated = old.rstrip() + ('\n\n' if old.strip() else '') + start + '\n' + content + '\n' + end + '\n'
    path.write_text(updated, encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description='Install architecture-change-review Skill')
    parser.add_argument('--repo', default='.', help='项目根目录')
    parser.add_argument('--clients', default='all', help='all 或逗号分隔 codex,claude,zcode,deepseek')
    parser.add_argument('--hooks', action='store_true', help='安装 Codex / Claude 项目 Hook')
    parser.add_argument('--rules', action='store_true', help='向 AGENTS.md / CLAUDE.md 追加触发规则')
    parser.add_argument('--zcode-user-hooks', action='store_true', help='明确授权写入 ZCode 用户级 Hook（全局配置）')
    parser.add_argument('--update', action='store_true', help='覆盖已安装的同名 Skill 目录')
    args = parser.parse_args()
    repo = Path(args.repo).expanduser().resolve()
    if not (repo / '.git').exists():
        parser.error('--repo 必须指向 Git 仓库根目录（含 .git 文件或目录）')
    clients = PLATFORMS if args.clients == 'all' else [x.strip() for x in args.clients.split(',') if x.strip()]
    if any(x not in PLATFORMS for x in clients):
        parser.error('未知 client；可选：' + ','.join(PLATFORMS))
    canonical = repo / '.agents' / 'skills' / SKILL
    canonical.parent.mkdir(parents=True, exist_ok=True)
    if same(canonical, ROOT):
        print('Source Skill 已在 .agents/skills，无需复制')
    elif canonical.exists() or canonical.is_symlink():
        if not args.update:
            print('Already installed (kept):', canonical, '— use --update to replace')
        else:
            if canonical.is_symlink() or canonical.is_file():
                canonical.unlink()
            else:
                shutil.rmtree(canonical)
            shutil.copytree(ROOT, canonical, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.DS_Store'))
    else:
        shutil.copytree(ROOT, canonical, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.DS_Store'))
    print('Installed:',canonical)
    aliases = {
        'claude': repo / '.claude' / 'skills' / SKILL,
        'zcode': repo / '.zcode' / 'skills' / SKILL,
        'deepseek': repo / '.dsh' / 'skills' / SKILL,
    }
    for client in clients:
        if client not in aliases:
            continue
        alias = aliases[client]
        alias.parent.mkdir(parents=True, exist_ok=True)
        if same(alias, canonical):
            continue
        if alias.exists() or alias.is_symlink():
            if not args.update:
                print('Already exists (skipped):',alias)
                continue
            if alias.is_symlink() or alias.is_file():
                alias.unlink()
            else:
                shutil.rmtree(alias)
        try:
            alias.symlink_to(os.path.relpath(canonical, alias.parent), target_is_directory=True)
        except (OSError, NotImplementedError):
            shutil.copytree(canonical,alias)
        print(client + ':',alias)
    script = canonical / 'scripts' / 'hook_adapter.py'
    if args.hooks:
        if 'codex' in clients:
            merge_hooks(repo / '.codex' / 'hooks.json', {
                'PostToolUse':hook_item('codex','post',script),
                'Stop':hook_item('codex','stop',script),
            })
            print('Codex hooks: .codex/hooks.json (需要在 Codex /hooks 审核信任)')
        if 'claude' in clients:
            merge_hooks(repo / '.claude' / 'settings.json', {
                'PostToolUse':hook_item('claude','post',script),
                'Stop':hook_item('claude','stop',script),
            })
            print('Claude hooks: .claude/settings.json')
    if args.zcode_user_hooks:
        if 'zcode' not in clients:
            parser.error('--zcode-user-hooks 需要 --clients 包含 zcode')
        # User hooks run across every workspace, so the script must not depend
        # on the lifetime of any specific project directory.
        global_skill = Path.home() / '.zcode' / 'skills' / SKILL
        global_skill.parent.mkdir(parents=True, exist_ok=True)
        if global_skill.exists() or global_skill.is_symlink():
            if args.update:
                if global_skill.is_symlink() or global_skill.is_file():
                    global_skill.unlink()
                else:
                    shutil.rmtree(global_skill)
                shutil.copytree(ROOT,global_skill,ignore=shutil.ignore_patterns('__pycache__','*.pyc','.DS_Store'))
        else:
            shutil.copytree(ROOT,global_skill,ignore=shutil.ignore_patterns('__pycache__','*.pyc','.DS_Store'))
        user_script = global_skill / 'scripts' / 'hook_adapter.py'
        user_config = Path.home() / '.zcode' / 'cli' / 'config.json'
        merge_hooks(user_config, {
            'PostToolUse':hook_item('zcode','post',user_script),
            'Stop':hook_item('zcode','stop',user_script),
        }, wrapper='events', enabled=True)
        print('ZCode global user hooks:',user_config, '(重启新会话生效)')
    if args.rules:
        merge_instruction(repo / 'AGENTS.md')
        if 'claude' in clients:
            merge_instruction(repo / 'CLAUDE.md')
        print('Added rules: AGENTS.md' + (' + CLAUDE.md' if 'claude' in clients else ''))
    print('验证: python3',canonical / 'scripts' / 'change_review.py','--repo',repo,'status')


if __name__ == '__main__':
    main()
