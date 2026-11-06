#!/usr/bin/env python3
"""Agent Skill: architecture-change-review. Git-based milestone snapshots and HTML reports.

Requires only Python 3.9+ and Git. Never modifies the real Git index.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import html
import json
import os
import shutil
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any, Dict, List, Optional

SKILL_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = '.agent-change-review'
VERSION = 2
SOURCE_EXTS = {
    '.go', '.py', '.pyi', '.js', '.jsx', '.mjs', '.cjs', '.ts', '.tsx', '.vue',
    '.svelte', '.dart', '.swift', '.kt', '.kts', '.java', '.groovy', '.gradle',
    '.rs', '.c', '.cc', '.cpp', '.h', '.hpp', '.m', '.mm', '.cs', '.rb', '.php',
    '.sql', '.proto', '.graphql', '.gql', '.sh', '.bash', '.zsh', '.ps1',
    '.yaml', '.yml', '.toml', '.json', '.xml', '.html', '.css', '.scss', '.less',
    '.vue', '.config', '.properties', '.tf', '.hcl', '.mk', '.gradle.kts',
}
NOISE_NAMES = {
    'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml', 'bun.lockb',
    'poetry.lock', 'uv.lock', 'pipfile.lock', 'cargo.lock', 'composer.lock',
    'gemfile.lock', 'pubspec.lock', 'go.sum', 'gradle.lockfile',
    '.ds_store', 'thumbs.db', 'changelog.md',
}
SENSITIVE_SUFFIXES = {'.pem', '.p12', '.pfx', '.p8', '.key', '.crt', '.cer', '.keystore', '.jks'}
OMIT_DIRS = {
    '.git', '.agent-change-review', 'node_modules', '.next', 'build', 'dist',
    'coverage', '.venv', 'venv', '__pycache__', '.gradle', '.idea',
    '.dart_tool', 'target', 'pods', 'deriveddata', '.terraform',
}
MAX_NEW_FILE_BYTES = 2 * 1024 * 1024
CRITICAL_PARTS = ('migration', 'migrations', 'schema', 'openapi', 'swagger', 'auth',
                  'permission', 'permissions', 'routes', 'contract', 'contracts')


def run_git(root: Path, *args: str, env: Optional[dict] = None, check: bool = True) -> bytes:
    proc = subprocess.run(['git', '-C', str(root), *args], capture_output=True,
                          input=b'', env=env, check=False)
    if check and proc.returncode:
        raise RuntimeError('git ' + ' '.join(args[:3]) + ': ' +
                           proc.stderr.decode('utf-8', 'replace').strip())
    return proc.stdout


def repo_root(path: str) -> Path:
    cwd = Path(path).expanduser().resolve()
    p = subprocess.run(['git', '-C', str(cwd), 'rev-parse', '--show-toplevel'],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode:
        raise RuntimeError('当前目录不是 Git 工作仓库。请在 Git 项目中运行。')
    return Path(os.fsdecode(p.stdout.strip())).resolve()


def allowed_path(path: str) -> bool:
    p = Path(path)
    name = p.name.lower()
    parts = [x.lower() for x in p.parts]
    if any(x in OMIT_DIRS for x in parts[:-1]):
        return False
    if name in NOISE_NAMES or name.startswith('.env') or name.startswith('id_rsa'):
        return False
    if name in {'credentials', 'credentials.json', 'secret.json', 'secrets.json',
                'service-account.json', 'google-services.json', 'google-service-info.plist',
                '.npmrc', '.pypirc', '.netrc', '.yarnrc', 'secrets.yml', 'secrets.yaml'}:
        return False
    if name.endswith(('.min.js', '.min.css', '.map', '.g.dart', '.freezed.dart',
                      '.generated.ts', '.generated.js', '.pb.go', '_pb2.py')):
        return False
    if any(x in {'secrets', 'credentials', '.ssh', '.aws', '.kube'} for x in parts[:-1]):
        return False
    if p.suffix.lower() in SENSITIVE_SUFFIXES:
        return False
    return True


def effective_source(path: str) -> bool:
    p = Path(path)
    if not allowed_path(path) or p.suffix.lower() not in SOURCE_EXTS:
        return False
    if p.name.lower() in {'readme.md'}:
        return False
    return True


def paths_z(raw: bytes) -> List[str]:
    return [os.fsdecode(i) for i in raw.split(b'\0') if i]


def snapshot(root: Path) -> str:
    """Produce a local tree object from the working tree using an isolated temp index.

    Excludes ignored, large new, generated, and known secret paths. Git objects
    remain local and no real staging area is modified.
    """
    tracked_changes = paths_z(run_git(root, 'ls-files', '-m', '-d', '-z'))
    staged_changes = paths_z(run_git(root, 'diff', '--cached', '--name-only',
                                     '--no-renames', '-z'))
    new_changes = paths_z(run_git(root, 'ls-files', '-o', '--exclude-standard', '-z'))
    allpaths = set(tracked_changes + staged_changes + new_changes)
    keep = []
    for p in sorted(allpaths):
        if not allowed_path(p):
            continue
        target = root / p
        try:
            if p in new_changes and target.is_file() and target.stat().st_size > MAX_NEW_FILE_BYTES:
                continue
        except OSError:
            pass
        keep.append(p)
    with tempfile.TemporaryDirectory(prefix='change-review-index-') as t:
        env = os.environ.copy()
        env['GIT_INDEX_FILE'] = str(Path(t) / 'index')
        env['GIT_LITERAL_PATHSPECS'] = '1'
        if run_git(root, 'rev-parse', '--verify', 'HEAD', check=False).strip():
            run_git(root, 'read-tree', 'HEAD', env=env)
        else:
            run_git(root, 'read-tree', '--empty', env=env)
        if keep:
            pathfile = Path(t) / 'paths'
            pathfile.write_bytes(b'\0'.join(os.fsencode(p) for p in keep) + b'\0')
            run_git(root, '-c', 'core.safecrlf=false', 'add', '-A',
                    '--pathspec-from-file=' + str(pathfile), '--pathspec-file-nul',
                    env=env)
        return run_git(root, 'write-tree', env=env).decode().strip()


def base_head(root: Path) -> str:
    tree = run_git(root, 'rev-parse', '--verify', 'HEAD^{tree}', check=False).decode().strip()
    return tree or run_git(root, 'mktree').decode().strip()


def changes(root: Path, base: str, tree: str) -> dict:
    # Git -w / ignore-blank-lines exclude pure whitespace churn from thresholds.
    num = run_git(root, 'diff', '--no-renames', '-w', '--ignore-blank-lines',
                  '--numstat', '-z', base, tree)
    statusraw = run_git(root, 'diff', '--no-renames', '-w', '--ignore-blank-lines',
                        '--name-status', '-z', base, tree)
    statuses = {}
    fields = paths_z(statusraw)
    for i in range(0, len(fields) - 1, 2):
        statuses[fields[i + 1]] = fields[i]
    files = []
    for chunk in num.split(b'\0'):
        if not chunk:
            continue
        v = os.fsdecode(chunk).split('\t', 2)
        if len(v) != 3:
            continue
        added, removed, path = v
        if not allowed_path(path):
            continue
        file = {
            'path': path, 'status': statuses.get(path, 'M'),
            'added': int(added) if added.isdigit() else 0,
            'deleted': int(removed) if removed.isdigit() else 0,
            'binary': added == '-' or removed == '-',
            'effective': effective_source(path),
        }
        files.append(file)
    files.sort(key=lambda f: f['path'])
    effective = [f for f in files if f['effective']]
    file_count = len(effective)
    line_changes = sum(f['added'] + f['deleted'] for f in effective)
    critical_candidates = sorted({f['path'] for f in effective if
                                  f['path'].endswith('.proto') or
                                  any(c in f['path'].lower() for c in CRITICAL_PARTS)})
    return {
        'files': files,
        'stats': {
            'all_files': len(files), 'effective_files': file_count,
            'line_changes': line_changes,
            'added': sum(f['added'] for f in effective),
            'deleted': sum(f['deleted'] for f in effective),
        },
        'critical_candidates': critical_candidates[:12],
    }


@contextlib.contextmanager
def state_lock(root: Path):
    folder = root / STATE_DIR
    folder.mkdir(parents=True, exist_ok=True)
    (folder / '.gitignore').write_text('*\n', encoding='utf-8')
    lock = folder / 'state.lock'
    with open(lock, 'a+b') as fh:
        if os.name == 'nt':
            import msvcrt
            fh.seek(0)
            fh.write(b'0') if fh.tell() == 0 else None
            fh.flush()
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == 'nt':
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(fh, fcntl.LOCK_UN)


def state_path(root: Path) -> Path:
    return root / STATE_DIR / 'state.json'


def save_json(path: Path, data: Any):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile('w', encoding='utf-8',
                                     dir=path.parent, prefix='.tmp-',
                                     suffix='.json', delete=False) as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write('\n')
        temp = Path(f.name)
    os.replace(temp, path)


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec='seconds')


def load_state(root: Path) -> dict:
    path = state_path(root)
    if path.exists():
        data = json.loads(path.read_text(encoding='utf-8'))
        if data.get('version') != VERSION:
            raise RuntimeError('状态版本不匹配；请备份 .agent-change-review 并执行 baseline --reset')
        return data
    # No initial checkpoint: compare with HEAD, retaining existing uncommitted changes.
    state = {
        'version': VERSION, 'baseline_tree': base_head(root),
        'baseline_kind': 'HEAD fallback (may include pre-existing edits)',
        'phase': 0, 'reports': [], 'last_notification': '',
        'pending_critical': '', 'started_at': now_iso(),
    }
    save_json(path, state)
    return state


def get_info(root: Path, state: dict, tree: Optional[str] = None) -> dict:
    current = tree or snapshot(root)
    info = changes(root, state['baseline_tree'], current)
    st = info['stats']
    soft = st['effective_files'] >= 5 or st['line_changes'] >= 1000
    hard = st['effective_files'] >= 10 or st['line_changes'] >= 2000
    critical = bool(state.get('pending_critical')) or bool(info['critical_candidates'])
    reasons = []
    if soft:
        reasons.append('达到阶段阈值（≥5 文件或 ≥1000 行）')
    if hard:
        reasons.append('达到硬阈值（≥10 文件或 ≥2000 行）')
    if state.get('pending_critical'):
        reasons.append('Agent 标记关键变更：' + state['pending_critical'])
    if info['critical_candidates']:
        reasons.append('疑似契约/迁移/权限变更（需人工确认）')
    due = bool(soft or critical)
    return {
        'due': due, 'hard_due': hard, 'soft_due': soft,
        'critical_due': critical, 'reasons': reasons,
        'base_tree': state['baseline_tree'], 'current_tree': current,
        'phase': state['phase'] + 1,
        'stats': st, 'critical_candidates': info['critical_candidates'],
        'files': info['files'],
    }


def check_cmd(root: Path, args) -> dict:
    with state_lock(root):
        state = load_state(root)
        if args.critical:
            state['pending_critical'] = args.critical[:180]
            save_json(state_path(root), state)
        info = get_info(root, state)
        result = {k: v for k, v in info.items() if args.full or k not in {'files'}}
        return result


def baseline_cmd(root: Path, args) -> dict:
    with state_lock(root):
        existing = state_path(root).exists()
        if existing and not (args.reset or args.new_task):
            state = load_state(root)
            return {'created': False, 'baseline_tree': state['baseline_tree'],
                    'phase': state['phase'],
                    'message': '保留已有基线；新任务请使用 baseline --new-task（会归档旧报告）'}
        archive = ''
        if existing:
            state = load_state(root)
            pending = get_info(root, state)
            if pending['files'] and not args.discard_pending:
                raise RuntimeError('仍有未报告代码修改；请先完成阶段报告，或显式加 --discard-pending 再归档')
            folder = root / STATE_DIR
            history = folder / 'history'
            history.mkdir(parents=True, exist_ok=True)
            stamp = dt.datetime.now().strftime('%Y%m%d-%H%M%S')
            archived = history / ('task-' + stamp)
            suffix = 1
            while archived.exists():
                archived = history / ('task-' + stamp + '-' + str(suffix))
                suffix += 1
            archived.mkdir()
            for dirname in ('reports', 'drafts'):
                old = folder / dirname
                if old.exists():
                    shutil.move(str(old), str(archived / dirname))
            shutil.copy2(state_path(root), archived / 'state.json')
            archive = str(archived)
        tree = snapshot(root)
        state = {'version': VERSION, 'baseline_tree': tree,
                 'baseline_kind': 'explicit working-tree snapshot',
                 'task_name': args.task or '',
                 'phase': 0, 'reports': [], 'last_notification': '',
                 'pending_critical': '', 'started_at': now_iso()}
        save_json(state_path(root), state)
        return {'created': True, 'baseline_tree': tree, 'phase': 0,
                'archive': archive,
                'message': '已记录任务开始工作树快照；旧阶段已归档（如有）'}


def draft_skeleton(info: dict, reason: str) -> dict:
    return {
        '_internal': {
            'version': VERSION, 'base_tree': info['base_tree'],
            'current_tree': info['current_tree'], 'phase': info['phase'],
            'captured_at': now_iso(), 'reason': reason,
        },
        'task': '', 'phase_title': '',
        'system': {
            'mission': '', 'business_impact': '', 'technical_impact': '',
            'module_flow': [
                {'name': '', 'responsibility': '', 'impact': 'direct', 'evidence': []},
                {'name': '', 'responsibility': '', 'impact': 'indirect', 'evidence': []},
                {'name': '', 'responsibility': '', 'impact': 'untouched', 'evidence': []},
            ],
        },
        'flow': {'label': '', 'before': [], 'after': [], 'explanation': '', 'evidence': []},
        'capabilities': [{
            'name': '', 'business': '', 'technical': '', 'acceptance': '', 'evidence': [],
        }],
        'differences': [{
            'title': '', 'before': '', 'after': '', 'reason': '', 'evidence': [],
        }],
        'validation': [{'item': '', 'status': 'not_run', 'detail': ''}],
        'risks': [],
        'file_notes': {},
        'stats': info['stats'], 'files': info['files'],
    }


def collect_cmd(root: Path, args) -> dict:
    with state_lock(root):
        state = load_state(root)
        info = get_info(root, state)
        if not info['files']:
            raise RuntimeError('没有可报告的源码变更（忽略了锁文件、生成物、隐私文件等）')
        if not (info['due'] or args.force):
            raise RuntimeError('未达到检查点：可累计修改，或者完成业务阶段后加 --force')
        reason = args.reason or (' / '.join(info['reasons']) if info['reasons'] else '业务阶段完成')
        name = 'draft-{:03d}-{}.json'.format(info['phase'], info['current_tree'][:10])
        path = root / STATE_DIR / 'drafts' / name
        if not path.exists() or args.overwrite:
            save_json(path, draft_skeleton(info, reason))
        return {'draft': str(path), 'phase': info['phase'], 'stats': info['stats'],
                'base_tree': info['base_tree'], 'current_tree': info['current_tree'],
                'message': '只生成 Git 事实骨架。Agent 必须阅读真实代码并填写业务/技术内容。'}


def evidence_path(item: Any) -> str:
    if isinstance(item, dict):
        item = item.get('path', '')
    s = str(item or '').strip()
    return re.sub(r':\d+(?:-\d+)?$', '', s)


def is_tree_file(root: Path, tree: str, path: str) -> bool:
    if not allowed_path(path) or path.startswith('/') or '..' in Path(path).parts:
        return False
    result = subprocess.run(['git', '-C', str(root), 'cat-file', '-e', tree + ':' + path],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return result.returncode == 0


def semantic_checks(root: Path, doc: dict) -> None:
    errs = []
    def required(text, desc, low=2):
        if not isinstance(text, str) or len(text.strip()) < low:
            errs.append(desc + ' 不可为空或太短')
    required(doc.get('task'), 'task')
    required(doc.get('phase_title'), 'phase_title')
    system = doc.get('system', {})
    if not isinstance(system, dict):
        system = {}
    for k in ('mission', 'business_impact', 'technical_impact'):
        required(system.get(k), 'system.' + k)
    mods = system.get('module_flow', [])
    if not isinstance(mods, list) or not (2 <= len(mods) <= 10):
        errs.append('system.module_flow 必须提供 2–10 个自顶向下的逻辑模块')
        mods = []
    for i, mod in enumerate(mods):
        for key in ('name', 'responsibility'):
            required(mod.get(key), f'module_flow[{i}].{key}')
        if mod.get('impact') not in ('direct', 'indirect', 'untouched'):
            errs.append(f'module_flow[{i}].impact 非法')
    if not any(x.get('impact') == 'direct' for x in mods):
        errs.append('至少一个逻辑模块标为 direct')
    flow = doc.get('flow', {})
    if not isinstance(flow, dict):
        flow = {}
    required(flow.get('label'), 'flow.label')
    for key in ('before', 'after'):
        if not isinstance(flow.get(key), list) or not flow[key] or not all(str(s).strip() for s in flow[key]):
            errs.append('flow.' + key + ' 必须是非空节点数组')
    required(flow.get('explanation'), 'flow.explanation')
    caps = doc.get('capabilities', [])
    diffs = doc.get('differences', [])
    if not isinstance(caps, list) or not (1 <= len(caps) <= 5):
        errs.append('capabilities 需 1–5 项')
        caps = []
    if not isinstance(diffs, list) or not (1 <= len(diffs) <= 5):
        errs.append('differences 需 1–5 项')
        diffs = []
    for i, cap in enumerate(caps):
        for k in ('name', 'business', 'technical', 'acceptance'):
            required(cap.get(k), f'capabilities[{i}].{k}')
        if not cap.get('evidence'):
            errs.append(f'capabilities[{i}] 至少提供一个证据文件')
    for i, diff in enumerate(diffs):
        for k in ('title', 'before', 'after', 'reason'):
            required(diff.get(k), f'differences[{i}].{k}')
        if not diff.get('evidence'):
            errs.append(f'differences[{i}] 至少提供一个证据文件')
    for row in doc.get('validation', []):
        if row.get('status') not in ('passed', 'failed', 'not_run', 'partial'):
            errs.append('validation.status 仅支持 passed/failed/not_run/partial')
    base = doc.get('_internal', {}).get('base_tree', '')
    tree = doc.get('_internal', {}).get('current_tree', '')
    evidence_sets = [flow.get('evidence', [])]
    evidence_sets += [m.get('evidence', []) for m in mods]
    evidence_sets += [c.get('evidence', []) for c in caps]
    evidence_sets += [d.get('evidence', []) for d in diffs]
    evidence_sets += [r.get('evidence', []) for r in doc.get('risks', [])]
    for items in evidence_sets:
        if not isinstance(items, list):
            errs.append('evidence 必须是路径字符串列表')
            continue
        for pathref in items:
            path = evidence_path(pathref)
            if not path or not (is_tree_file(root, tree, path) or is_tree_file(root, base, path)):
                errs.append('证据文件在阶段快照中不存在: ' + repr(pathref))
    if errs:
        raise RuntimeError('HTML 生成前校验失败:\n- ' + '\n- '.join(errs[:25]))


def html_page(payload: dict) -> str:
    template = (SKILL_ROOT / 'assets' / 'report.html').read_text(encoding='utf-8')
    data = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
    # Prevent </script> and HTML parser injection within JSON script tag.
    data = data.replace('&', '\\u0026').replace('<', '\\u003c').replace('>', '\\u003e')
    return template.replace('<!--__PAYLOAD__-->', data).replace('__PAGE_TITLE__',
        html.escape(payload.get('title', '架构变更复盘'), quote=True))


def build_index(root: Path, state: dict) -> str:
    report_dir = root / STATE_DIR / 'reports'
    phases = []
    newest = None
    for item in state['reports']:
        path = report_dir / item['json_file']
        if not path.exists():
            continue
        doc = json.loads(path.read_text(encoding='utf-8'))
        phases.append({
            'phase': item['phase'], 'html': item['html_file'],
            'task': doc['task'], 'title': doc['phase_title'],
            'captured_at': doc['_internal']['captured_at'],
            'stats': doc['stats'], 'capabilities': [c['name'] for c in doc['capabilities']],
            'changes': [d['title'] for d in doc['differences']],
            'validation': doc['validation'],
        })
        newest = doc
    if newest is None:
        return ''
    payload = {'mode': 'index', 'title': '架构变更总览 · ' + newest['task'],
               'generated': now_iso(), 'latest': newest,
               'phases': phases, 'phase_count': len(phases)}
    dest = report_dir / 'index.html'
    dest.write_text(html_page(payload), encoding='utf-8')
    return str(dest)


def render_cmd(root: Path, args) -> dict:
    path = Path(args.input).expanduser()
    if not path.is_absolute():
        path = (root / path).resolve()
    if not path.is_file() or not path.is_relative_to(root / STATE_DIR):
        raise RuntimeError('input 必须是此仓库 .agent-change-review/ 下的草稿 JSON')
    doc = json.loads(path.read_text(encoding='utf-8'))
    with state_lock(root):
        state = load_state(root)
        internal = doc.get('_internal', {})
        if internal.get('base_tree') != state['baseline_tree'] or internal.get('phase') != state['phase'] + 1:
            raise RuntimeError('阶段基线已改变；重新 collect，勿跨阶段复用旧草稿')
        current = snapshot(root)
        if internal.get('current_tree') != current:
            raise RuntimeError('collect 后源码发生变化；重新 collect 获取新的变更范围')
        facts = changes(root, state['baseline_tree'], current)
        if not facts['files']:
            raise RuntimeError('没有可报告的文件')
        semantic_checks(root, doc)
        # Always overwrite facts with recomputed Git facts.
        doc['stats'] = facts['stats']
        doc['files'] = facts['files']
        doc['_internal']['rendered_at'] = now_iso()
        phase = state['phase'] + 1
        stem = f'phase-{phase:03d}'
        reports = root / STATE_DIR / 'reports'
        reports.mkdir(exist_ok=True)
        payload = {'mode': 'phase', 'title': doc['phase_title'] + ' · 架构变更复盘',
                   'generated': now_iso(), 'report': doc}
        html_path = reports / (stem + '.html')
        json_path = reports / (stem + '.json')
        save_json(json_path, doc)
        html_path.write_text(html_page(payload), encoding='utf-8')
        state['reports'].append({'phase': phase, 'html_file': html_path.name,
                                 'json_file': json_path.name, 'tree': current})
        state['phase'] = phase
        state['baseline_tree'] = current
        state['baseline_kind'] = 'last rendered checkpoint'
        state['last_notification'] = ''
        state['pending_critical'] = ''
        save_json(state_path(root), state)
        index = build_index(root, state)
        return {'phase': phase, 'html': str(html_path), 'index': index,
                'stats': facts['stats'],
                'message': '阶段快照推进成功；后续只累计新改动'}


def status_cmd(root: Path, args) -> dict:
    with state_lock(root):
        state = load_state(root)
        info = get_info(root, state)
        return {'phase_completed': state['phase'], 'reports': state['reports'],
                'latest_index': str(root / STATE_DIR / 'reports' / 'index.html') if state['reports'] else '',
                'unreported': {k: info[k] for k in ('due', 'hard_due', 'stats', 'reasons')}}


def notify_cmd(root: Path, args) -> dict:
    """Called by tool hooks: first due / hard crossing once per threshold bucket."""
    with state_lock(root):
        state = load_state(root)
        info = get_info(root, state)
        if not info['due']:
            return {'notify': False, 'due': False}
        st = info['stats']
        # Deduplicates repeated PostToolUse calls while still re-notifying after
        # significantly more changes (e.g. thousands of lines in a long task).
        bucket = f"{int(info['hard_due'])}:{st['effective_files']//5}:{st['line_changes']//1000}:{bool(info['critical_due'])}"
        tag = info['base_tree'][:10] + ':' + bucket
        if state['last_notification'] == tag and not args.force:
            return {'notify': False, 'due': True, 'hard_due': info['hard_due']}
        state['last_notification'] = tag
        save_json(state_path(root), state)
        return {'notify': True, 'due': True, 'hard_due': info['hard_due'],
                'reasons': info['reasons'], 'stats': st, 'phase': info['phase']}


def main() -> int:
    parser = argparse.ArgumentParser(description='Agent 开发改动分段总结 / HTML 架构透视')
    parser.add_argument('--repo', default='.', help='Git 项目目录')
    sub = parser.add_subparsers(dest='cmd', required=True)
    b = sub.add_parser('baseline', help='开发任务开始前记录基线')
    b.add_argument('--reset', action='store_true', help='向后兼容：同 --new-task，归档旧报告')
    b.add_argument('--new-task', action='store_true', help='开始新任务：归档已完成阶段并重新基线')
    b.add_argument('--task', default='', help='新任务名称')
    b.add_argument('--discard-pending', action='store_true', help='明确放弃归档前未报告的增量')
    c = sub.add_parser('check', help='检查阶段阈值；不生成报告')
    c.add_argument('--full', action='store_true', help='包含变更文件清单')
    c.add_argument('--critical', default='', help='Agent 确认有架构关键变更并标注原因')
    cc = sub.add_parser('collect', help='生成 Git 事实骨架 JSON')
    cc.add_argument('--force', action='store_true', help='在功能里程碑强制生成')
    cc.add_argument('--reason', default='', help='阶段名称或触发原因')
    cc.add_argument('--overwrite', action='store_true', help='重建同一源码快照的草稿')
    r = sub.add_parser('render', help='校验事实和证据并生成 HTML')
    r.add_argument('--input', required=True, help='填完语义字段的草稿路径')
    sub.add_parser('status', help='列出现有阶段及待报告改动')
    n = sub.add_parser('notify', help='由 Hook 调用：达到下一档阈值时通知一次')
    n.add_argument('--force', action='store_true')
    args = parser.parse_args()
    try:
        root = repo_root(args.repo)
        fn = {'baseline': baseline_cmd, 'check': check_cmd,
              'collect': collect_cmd, 'render': render_cmd,
              'status': status_cmd, 'notify': notify_cmd}[args.cmd]
        print(json.dumps(fn(root, args), ensure_ascii=False, indent=2))
        return 0
    except (OSError, RuntimeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
