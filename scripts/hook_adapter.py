#!/usr/bin/env python3
"""Read Codex / Claude Code / ZCode hook JSON; emit portable structured feedback.

PostToolUse is a lightweight milestone reminder. Stop is a one-time recovery
check, not a recursive autonomous summarizer.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time

import change_review as cr

GAP_SECONDS = 4.0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--platform', choices=['codex', 'claude', 'zcode'], required=True)
    parser.add_argument('--event', choices=['post', 'stop'], required=True)
    args = parser.parse_args()
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        data = {}
    try:
        root = cr.repo_root(data.get('cwd') or os.getcwd())
        if args.event == 'post':
            # Don't immediately re-trigger on collect / render itself.
            inp = data.get('tool_input') or data.get('toolInput') or {}
            if 'change_review.py' in str(inp) or 'hook_adapter.py' in str(inp):
                return
        # Do not activate inside unrelated repos / Q&A sessions without an
        # explicit baseline. Project instructions initialize it before coding.
        if not cr.state_path(root).exists():
            return
        with cr.state_lock(root):
            state = cr.load_state(root)
            if args.event == 'post':
                now = time.time()
                if now - float(state.get('last_hook_poll', 0)) < GAP_SECONDS:
                    return
                state['last_hook_poll'] = now
            info = cr.get_info(root, state)
            if not info['due']:
                cr.save_json(cr.state_path(root), state)
                return
            if args.event == 'post':
                st = info['stats']
                bucket = f"{int(info['hard_due'])}:{st['effective_files']//5}:{st['line_changes']//1000}:{bool(info['critical_due'])}"
                tag = info['base_tree'][:10] + ':' + bucket
                if state.get('last_notification') == tag:
                    cr.save_json(cr.state_path(root), state)
                    return
                state['last_notification'] = tag
                cr.save_json(cr.state_path(root), state)
            elif data.get('stop_hook_active') or data.get('stopHookActive'):
                # Hook continuation limit: never force infinite retries.
                return
        st = info['stats']
        reason = ('硬阈值，尽快在下一个安全边界复盘' if info['hard_due']
                  else '达到复盘阈值，在当前业务阶段完整后复盘')
        instructions = ('读取 architecture-change-review Skill；执行 collect --force，'
                        '阅读真实代码填写 JSON 中的业务与技术交叉结论，最后 render 生成 HTML。'
                        '不要仅输出 diffstat；不要中断未完成的原子修改。')
        message = (f"[Architecture Checkpoint] {st['effective_files']} 个有效文件 / "
                   f"{st['line_changes']} 行增删；{reason}。{instructions}")
        if args.event == 'stop':
            print(json.dumps({'decision': 'block', 'reason': message}, ensure_ascii=False))
        else:
            print(json.dumps({'hookSpecificOutput': {
                'hookEventName': 'PostToolUse', 'additionalContext': message,
            }}, ensure_ascii=False))
    except (OSError, RuntimeError, KeyError, ValueError) as error:
        # Hook should never take down coding task; diagnostics only.
        if os.environ.get('ARCH_CHANGE_DEBUG'):
            print('[architecture-change-review] ' + str(error), file=sys.stderr)


if __name__ == '__main__':
    main()
