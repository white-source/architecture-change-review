"""Unit + integration tests. Execute: python3 -m unittest discover -s tests -v"""
from __future__ import annotations
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / 'scripts' / 'change_review.py'
INSTALL = ROOT / 'scripts' / 'install.py'
HOOK = ROOT / 'scripts' / 'hook_adapter.py'


def git(root, *args):
    return subprocess.run(['git', '-C',str(root), *args],capture_output=True,
                          text=True,check=True).stdout.strip()


def cli(root, *args, fail=False):
    r = subprocess.run([sys.executable, str(SCRIPT), *args], cwd=root,
                       text=True,capture_output=True)
    if fail:
        if r.returncode == 0:
            raise AssertionError('expected CLI failure: ' + ' '.join(args))
        return json.loads(r.stderr)
    if r.returncode:
        raise AssertionError('CLI failed: ' + r.stderr)
    return json.loads(r.stdout)


class ChangeReviewTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='architecture-skill-test-')
        self.root = Path(self.tmp.name)
        git(self.root, 'init','-q')
        git(self.root, 'config','user.email','test@example.test')
        git(self.root, 'config','user.name','Review Test')
        (self.root / 'src').mkdir()
        (self.root / 'src' / 'api.py').write_text('def api():\n    return 1\n')
        git(self.root, 'add','.')
        git(self.root, 'commit','-qm','base')

    def tearDown(self):
        self.tmp.cleanup()

    def fill(self, path):
        doc=json.loads(Path(path).read_text(encoding='utf-8'))
        changed = [f['path'] for f in doc['files']]
        evidence=changed[0]
        doc['task']='示例订单系统重构'
        doc['phase_title']='阶段一：订单请求校验'
        doc['system']={
            'mission':'为订单平台提供可靠的请求到数据落库处理链路。',
            'business_impact':'减少因遗漏校验造成的订单错误，增加可检查的入站状态。',
            'technical_impact':'修改入口校验及服务层，沿用已有数据访问接口。',
            'module_flow':[
                {'name':'调用方','responsibility':'下发订单请求','impact':'untouched','evidence':[]},
                {'name':'API 入口','responsibility':'请求校验与失败响应','impact':'direct','evidence':[evidence]},
                {'name':'业务规则','responsibility':'验证订单有效性','impact':'direct','evidence':[evidence]},
                {'name':'持久化','responsibility':'保存已校验订单','impact':'indirect','evidence':[]},
            ],
        }
        doc['flow']={'label':'创建订单','before':['请求','直接入库','响应'],
                     'after':['请求','参数校验','持久化','响应'],
                     'explanation':'将校验前置到 API 入口，数据接口不改。',
                     'evidence':[evidence]}
        doc['capabilities']=[{'name':'订单校验','business':'阻止缺少订单编号的请求进入数据库。',
              'technical':'API 参数校验函数在调用服务层前抛出明确错误。',
              'acceptance':'提交无订单编号的请求，验证得到校验失败消息。',
              'evidence':[evidence]}]
        doc['differences']=[{'title':'入口校验前置','before':'请求不校验直接继续处理。',
              'after':'参数校验失败即终止业务流转。','reason':'减少不合法订单进入下游，但增加错误响应分支。',
              'evidence':[evidence]}]
        doc['validation']=[{'item':'API 单元测试','status':'not_run','detail':'未执行'}]
        doc['file_notes']={evidence:'订单 API 主逻辑'}
        Path(path).write_text(json.dumps(doc,ensure_ascii=False,indent=2),encoding='utf-8')
        return doc

    def test_checkpoints_reset_and_index(self):
        before=git(self.root,'status','--porcelain')
        cli(self.root,'baseline')
        for i in range(4):
            (self.root/'src'/f'feature_{i}.py').write_text(f'print({i})\n')
        x=cli(self.root,'check')
        self.assertFalse(x['due'])
        (self.root/'src'/'feature_4.py').write_text('print(4)\n')
        (self.root/'.env.local').write_text('SECRET=do-not-store\n')
        (self.root/'src'/'package-lock.json').write_text('{"generated":true}\n')
        x=cli(self.root,'check','--full')
        self.assertTrue(x['due'])
        self.assertEqual(x['stats']['effective_files'],5)
        self.assertNotIn('.env.local',[f['path'] for f in x['files']])
        self.assertNotIn('src/package-lock.json',[f['path'] for f in x['files']])
        draft=cli(self.root,'collect')['draft']
        self.fill(draft)
        out=cli(self.root,'render','--input',draft)
        self.assertTrue(Path(out['index']).exists())
        self.assertTrue(Path(out['html']).exists())
        html=Path(out['html']).read_text(encoding='utf-8')
        self.assertIn('订单校验',html)
        self.assertIn('filetree',html)
        self.assertEqual(cli(self.root,'check')['stats']['line_changes'],0)
        self.assertEqual(cli(self.root,'status')['phase_completed'],1)
        self.assertEqual(cli(self.root,'baseline')['created'],False)
        self.assertNotEqual(git(self.root,'status','--porcelain'),before)
        self.assertNotIn('src/feature_0.py',git(self.root,'diff','--cached','--name-only'))

        # The same file now changes, but only the new delta should be counted.
        (self.root/'src'/'feature_0.py').write_text('print("changed")\n')
        x=cli(self.root,'check')
        self.assertEqual(x['stats']['effective_files'],1)
        self.assertFalse(x['due'])
        draft=cli(self.root,'collect','--force')['draft']
        self.fill(draft)
        second=cli(self.root,'render','--input',draft)
        self.assertEqual(second['phase'],2)
        index=Path(second['index']).read_text(encoding='utf-8')
        self.assertIn('phase-001.html',index)
        self.assertIn('phase-002.html',index)

    def test_line_threshold_without_five_files(self):
        cli(self.root,'baseline')
        lines=['value = '+str(i) for i in range(1100)]
        (self.root/'src'/'large.py').write_text('\n'.join(lines)+'\n')
        info=cli(self.root,'check')
        self.assertTrue(info['soft_due'])
        self.assertFalse(info['hard_due'])
        (self.root/'src'/'large.py').write_text('\n'.join(lines + ['a = '+str(i) for i in range(1100)])+'\n')
        self.assertTrue(cli(self.root,'check')['hard_due'])

    def test_major_threshold_and_critical(self):
        cli(self.root,'baseline')
        for i in range(11):
            (self.root/'src'/f'mod_{i}.py').write_text('value = 5\n')
        data=cli(self.root,'check')
        self.assertTrue(data['hard_due'])
        self.assertEqual(data['stats']['effective_files'],11)
        # Critical marking persists until render.
        why=cli(self.root,'check','--critical','修改支付接口契约')
        self.assertTrue(why['critical_due'])
        self.assertIn('修改支付接口契约',' '.join(why['reasons']))

    def test_preexisting_changes_baseline(self):
        (self.root/'src'/'api.py').write_text('def api():\n    return 2\n')
        (self.root/'src'/'preexisting.py').write_text('old=1\n')
        cli(self.root,'baseline')
        self.assertEqual(cli(self.root,'check')['stats']['all_files'],0)
        (self.root/'src'/'preexisting.py').write_text('old=3\n')
        self.assertEqual(cli(self.root,'check')['stats']['effective_files'],1)

    def test_stale_draft_and_invalid_evidence(self):
        cli(self.root,'baseline')
        (self.root/'src'/'feature.py').write_text('x=1\n')
        draft=cli(self.root,'collect','--force')['draft']
        doc=self.fill(draft)
        doc['capabilities'][0]['evidence']=['absent/wrong.py']
        Path(draft).write_text(json.dumps(doc,ensure_ascii=False),encoding='utf-8')
        err=cli(self.root,'render','--input',draft,fail=True)
        self.assertIn('证据文件',err['error'])
        self.fill(draft)
        (self.root/'src'/'feature.py').write_text('x=2\n')
        err=cli(self.root,'render','--input',draft,fail=True)
        self.assertIn('源码发生变化',err['error'])
        self.assertEqual(cli(self.root,'status')['phase_completed'],0)

    def test_new_task_preserves_prior_reports(self):
        cli(self.root,'baseline')
        (self.root/'src'/'phase.py').write_text('value=1\n')
        draft=cli(self.root,'collect','--force')['draft']
        self.fill(draft)
        one=cli(self.root,'render','--input',draft)
        self.assertTrue(Path(one['index']).exists())
        new=cli(self.root,'baseline','--new-task','--task','另一个功能')
        self.assertTrue(new['archive'])
        self.assertTrue((Path(new['archive'])/'reports'/'index.html').exists())
        self.assertEqual(cli(self.root,'status')['phase_completed'],0)
        self.assertEqual(cli(self.root,'check')['stats']['effective_files'],0)

    def test_resume_new_task_prevents_unreported_loss(self):
        cli(self.root,'baseline')
        (self.root/'src'/'phase.py').write_text('value=1\n')
        err=cli(self.root,'baseline','--new-task',fail=True)
        self.assertIn('未报告',err['error'])
        new=cli(self.root,'baseline','--new-task','--discard-pending')
        self.assertTrue(new['created'])
        self.assertEqual(cli(self.root,'check')['stats']['effective_files'],0)

    def test_hook_post_and_stop(self):
        cli(self.root,'baseline')
        for i in range(5):
            (self.root/'src'/f'feature_{i}.py').write_text('x=1\n')
        event={'cwd':str(self.root),'tool_name':'Write', 'tool_input':{'file_path':'src/feature_4.py'}}
        post=subprocess.run([sys.executable,str(HOOK),'--platform','claude','--event','post'],
                            input=json.dumps(event),text=True,capture_output=True)
        self.assertEqual(post.returncode,0)
        p=json.loads(post.stdout)
        self.assertIn('PostToolUse',p['hookSpecificOutput']['hookEventName'])
        stop=subprocess.run([sys.executable,str(HOOK),'--platform','codex','--event','stop'],
                            input=json.dumps({'cwd':str(self.root),'stop_hook_active':False}),
                            text=True,capture_output=True)
        self.assertEqual(json.loads(stop.stdout)['decision'],'block')
        again=subprocess.run([sys.executable,str(HOOK),'--platform','codex','--event','stop'],
                            input=json.dumps({'cwd':str(self.root),'stop_hook_active':True}),
                            text=True,capture_output=True)
        self.assertEqual(again.stdout,'')

    def test_install_merge_preserves_existing(self):
        p=self.root/'.codex'/'hooks.json'
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps({'hooks':{'PostToolUse':[{'matcher':'Other','hooks':[{'type':'command','command':'echo keep'}]}]}}))
        c=self.root/'.claude'/'settings.json'
        c.parent.mkdir(parents=True)
        c.write_text(json.dumps({'permissions':{'allow':['Bash(git status)']}}))
        run=subprocess.run([sys.executable,str(INSTALL),'--repo',str(self.root),
                            '--clients','all','--hooks','--rules'],capture_output=True,text=True)
        self.assertEqual(run.returncode,0,run.stderr)
        d=json.loads(p.read_text())
        self.assertEqual(len(d['hooks']['PostToolUse']),2)
        self.assertIn('echo keep',str(d))
        self.assertEqual(len(d['hooks']['Stop']),1)
        claude=json.loads(c.read_text())
        self.assertEqual(claude['permissions']['allow'],['Bash(git status)'])
        self.assertTrue((self.root/'.zcode'/'skills'/'architecture-change-review'/'SKILL.md').exists())
        self.assertTrue((self.root/'.dsh'/'skills'/'architecture-change-review'/'SKILL.md').exists())
        self.assertIn('architecture-change-review:start',(self.root/'AGENTS.md').read_text())
        again=subprocess.run([sys.executable,str(INSTALL),'--repo',str(self.root),
                            '--clients','all','--hooks','--rules','--update'],capture_output=True,text=True)
        self.assertEqual(again.returncode,0,again.stderr)
        self.assertEqual(len(json.loads(p.read_text())['hooks']['PostToolUse']),2)
        self.assertEqual((self.root/'AGENTS.md').read_text().count('architecture-change-review:start'),1)


if __name__ == '__main__':
    unittest.main()
