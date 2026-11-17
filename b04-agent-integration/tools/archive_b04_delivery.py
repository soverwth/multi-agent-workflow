"""Stage, validate, archive and independently verify a B04 source delivery.

Only stage writes a new directory; no original files are moved or removed.
Test and demo subprocesses run against the staged project, not the checkout.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
GROUPS = ('model_adapter', 'agent_runner', 'tool_executor', 'reference_backend')
REFERENCES = ('第十组 设计规格与开发任务编排.docx', '多智能体共识收敛Workflow_优化版.docx')
DESIGNS = ('B04_任务执行协议设计.md', 'B04_Agent角色模板设计.md', 'B04_model_adapter模块设计.md',
           'B04_agent_runner模块设计.md', 'B04_tool_executor模块设计.md')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def files(directory):
    return sorted(p for p in directory.rglob('*') if p.is_file() and '__pycache__' not in p.parts and '.pytest_cache' not in p.parts)


def stage(target):
    if target.parent != (ROOT / 'deliveries').resolve():
        raise ValueError('Stage must create a direct child of this workspace deliveries directory')
    target.mkdir(parents=True, exist_ok=False)
    project = target / 'project'
    evidence = target / 'evidence'
    project.mkdir(); evidence.mkdir()
    selected = [ROOT / name for name in ('pyproject.toml', 'README.md', '.gitignore')]
    selected.extend(ROOT / name for name in DESIGNS + REFERENCES)
    for folder in ('src/b04', 'tests', 'examples', 'tools'):
        selected.extend(p for p in files(ROOT / folder) if p.suffix in {'.py', '.json', '.txt'})
    frozen = {}
    for source in sorted(set(selected)):
        if source.is_symlink():
            raise ValueError('Source symlink is not a delivery payload')
        relative = source.relative_to(ROOT)
        dest = project / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)
        frozen[relative.as_posix()] = sha(source)
    write_json(evidence / 'frozen_sources.json', frozen)
    print(json.dumps({'delivery': str(target), 'staged_files': len(frozen)}))


def check_frozen(target):
    frozen = json.loads((target / 'evidence/frozen_sources.json').read_text(encoding='utf-8'))
    for relative, expected in frozen.items():
        if sha(target / 'project' / relative) != expected:
            raise ValueError('Staged payload changed: ' + relative)
        if sha(ROOT / relative) != expected:
            raise ValueError('Workspace payload changed after staging: ' + relative)


def run_log(command, project, log, env):
    started = datetime.now(timezone.utc).isoformat()
    start = time.monotonic()
    with log.open('w', encoding='utf-8') as output:
        proc = subprocess.Popen(command, cwd=project, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding='utf-8', errors='replace', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        for line in proc.stdout:
            output.write(line); output.flush()
            print(line, end='', flush=True)
        proc.stdout.close()
        code = proc.wait()
    return dict(command=command[1:], exit_code=code, started_at=started,
                finished_at=datetime.now(timezone.utc).isoformat(), duration_seconds=round(time.monotonic()-start, 3), log=log.name)


def parse_junit(path):
    cases = []
    by_group = {g: Counter() for g in GROUPS}
    for item in ET.parse(path).getroot().iter('testcase'):
        classname = item.get('classname', '')
        group = next((g for g in GROUPS if g in classname.split('.')), None)
        if group is None:
            raise ValueError('Unclassified test case: ' + classname)
        outcome = 'error' if item.find('error') is not None else 'failed' if item.find('failure') is not None else 'skipped' if item.find('skipped') is not None else 'passed'
        skipped = item.find('skipped')
        cases.append(dict(group=group, classname=classname, name=item.get('name'), outcome=outcome,
                          duration_seconds=float(item.get('time', '0')), skip_reason=skipped.get('message') if skipped is not None else None))
        by_group[group][outcome] += 1
    totals = Counter(c['outcome'] for c in cases)
    return dict(total=len(cases), outcomes=dict(totals), groups={g: dict(v) for g, v in by_group.items()}, cases=cases)


def validate(target):
    check_frozen(target)
    project, evidence = target / 'project', target / 'evidence'
    env = dict(os.environ, PYTHONPATH=str(project / 'src'), PYTEST_DISABLE_PLUGIN_AUTOLOAD='1', PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1')
    environment = dict(python=sys.version, executable=sys.executable, platform=sys.platform,
                       packages={p: importlib.metadata.version(p) for p in ['pytest', 'jsonschema', 'Flask', 'argon2-cffi', 'setuptools']},
                       docker_test_image_configured=bool(env.get('B04_TEST_DOCKER_IMAGE')))
    write_json(evidence / 'environment.json', environment)
    command = [sys.executable, '-u', '-m', 'pytest', '-q', '-p', 'no:cacheprovider', '--junitxml=' + str(evidence / 'pytest_junit.xml')]
    run = run_log(command, project, evidence / 'pytest.log', env)
    results = parse_junit(evidence / 'pytest_junit.xml')
    results['run'] = run
    write_json(evidence / 'test_results.json', results)
    if run['exit_code'] or results['outcomes'].get('failed', 0) or results['outcomes'].get('error', 0):
        raise RuntimeError('Validation failed; evidence retained, no archive finalized')
    demos = []
    for name in ('model_adapter_demo.py', 'agent_runner_demo.py', 'tool_executor_demo.py', 'reference_backend_demo.py'):
        demos.append(run_log([sys.executable, 'examples/' + name], project, evidence / (name.removesuffix('.py') + '.log'), env))
        write_json(evidence / 'demo_results.json', demos)
        if demos[-1]['exit_code']:
            raise RuntimeError('Demo failed; evidence retained')
    check_frozen(target)
    print(json.dumps({'tests': results['outcomes'], 'demos_passed': len(demos)}))


def check_documents(project):
    errors, json_examples, checked_links = [], 0, 0
    for path in sorted(project.glob('*.md')):
        text = path.read_text(encoding='utf-8')
        for block in re.findall(r'```json\s*\n(.*?)```', text, flags=re.S):
            try:
                json.loads(block)
                json_examples += 1
            except ValueError as exc:
                errors.append(f'{path.name}: invalid JSON example: {exc}')
        for match in re.finditer(r'\[[^\]]*\]\((?:<([^>]+)>|([^\s)]+))\)', text):
            link = match.group(1) or match.group(2)
            if re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:', link) or link.startswith('#'):
                continue
            dest = link.split('#', 1)[0]
            checked_links += 1
            if not (path.parent / dest).exists():
                errors.append(f'{path.name}: missing local link: {link}')
    compiled = 0
    for path in files(project):
        if path.suffix == '.py':
            compile(path.read_text(encoding='utf-8-sig'), str(path), 'exec')
            compiled += 1
    return dict(compiled_python_files=compiled, valid_json_examples=json_examples, local_links_checked=checked_links, errors=errors)


def category(path):
    if path.startswith('project/src/'): return 'code'
    if path.startswith('project/tests/'): return 'tests'
    if path.startswith('project/examples/'): return 'examples'
    if path.startswith('project/tools/'): return 'archive_tool'
    if path.startswith('evidence/'): return 'validation_evidence'
    if path.endswith('.docx'): return 'team_reference_snapshot'
    if path.endswith('.md'): return 'documentation'
    return 'configuration'


def finalize(target):
    check_frozen(target)
    project, evidence = target / 'project', target / 'evidence'
    results = json.loads((evidence / 'test_results.json').read_text(encoding='utf-8'))
    demos = json.loads((evidence / 'demo_results.json').read_text(encoding='utf-8'))
    if results['run']['exit_code'] or any(d['exit_code'] for d in demos) or len(demos) != 4:
        raise ValueError('Missing successful validation')
    # Runtime payload remains byte-identical to what was tested; documentation
    # is copied after updating the recorded results, keeping its relative links.
    documents = [p for p in ROOT.glob('B04*.md') if p.name != 'B04_交付清单.md']
    sources = {}
    for source in documents + [ROOT / p for p in REFERENCES]:
        shutil.copy2(source, project / source.name)
        sources['project/' + source.name] = {'workspace_path': source.name, 'source_sha256': sha(source)}
    check = check_documents(project)
    snapshot = json.loads((project / 'tests/reference_backend/c1_contract.json').read_text(encoding='utf-8'))
    check['c1_source_sha256_matches_snapshot'] = sha(project / REFERENCES[0]) == snapshot['source']['sha256']
    check['frozen_runtime_payload_unchanged'] = True
    write_json(evidence / 'archive_checks.json', check)
    if check['errors'] or not check['c1_source_sha256_matches_snapshot']:
        raise ValueError(json.dumps(check, ensure_ascii=False))
    rows = '\n'.join(f"| {g} | {results['groups'][g].get('passed', 0)} | {results['groups'][g].get('skipped', 0)} |" for g in GROUPS)
    guide = f'''# B04 交付包\n\n本包冻结自当前源码，校验依据为本包 project 上重新执行的测试与示例；原工作区未移动。\n\n- [交付清单](<./B04_交付清单.md>)\n- [实验验收说明](<./project/B04_实验验收说明.md>)\n- [模块与接口说明](<./project/README.md>)\n- [JUnit 原始结果](<./evidence/pytest_junit.xml>)、[逐项结果](<./evidence/test_results.json>)、[测试日志](<./evidence/pytest.log>)\n\n## 测试结果\n\n| 测试组 | 通过 | 跳过 |\n| --- | --- | --- |\n{rows}\n\n## 复现\n\n解压后在 project 目录执行：\n\n```powershell\npython -m pip install -e ".[test]"\npython -m pip install -r src/b04/reference_backend/requirements.txt\n$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"\npython -u -m pytest -q\n$env:PYTHONPATH = (Resolve-Path .\\src).Path\npython examples/model_adapter_demo.py\npython examples/agent_runner_demo.py\npython examples/tool_executor_demo.py\npython examples/reference_backend_demo.py\n```\n\n目录校验：在包根目录运行 `python project/tools/archive_b04_delivery.py verify .`。\n\n模型示例使用 mock；Windows 进程树和文件测试使用真实本地资源。真实 Docker 测试的跳过及原因以 evidence 为准。B03 实际存储、B05 前端联调、B06 独立验收与真实模型供应商接入不因本包本地测试通过而宣告完成。角色模板交付为设计和嵌入式示例，文档原有待评审状态保留。\n\n本包保留项目布局以保证文档相对链接与 Python 导入可用。团队 DOCX 仅为来源快照；文档中注明的早期结果是阶段历史，以本次 evidence 为验收依据。旧 wheel、build 缓存、临时数据库和文档渲染中间文件不纳入归档。\n'''
    (target / 'README.md').write_text(guide, encoding='utf-8')
    inventory = '''# B04 交付清单\n\n负责人：汤志豪。交付日期：2026-11-17。包版本：源码快照（项目元数据 0.3.0）；运行契约保持原版本。\n\n| 交付项 | 主要文件 | 状态 |\n| --- | --- | --- |\n| 任务协议 | [B04 协议 v0.2.1](<./project/B04_任务执行协议设计.md>) | 设计交付；团队评审状态不替代运行证据 |\n| 角色模板 | [角色模板 v0.1](<./project/B04_Agent角色模板设计.md>) | 通用角色／PM 规划／嵌入式示例设计 |\n| model_adapter | [设计 v0.1.1](<./project/B04_model_adapter模块设计.md>)、[实现与测试说明](<./project/B04_model_adapter_实现与测试说明.md>)、project/src/b04/model_adapter | 已实现，本地模型驱动验证 |\n| agent_runner | [设计 v0.1.1](<./project/B04_agent_runner模块设计.md>)、[实现与测试说明](<./project/B04_agent_runner_实现与测试说明.md>)、project/src/b04/agent_runner | 已实现，本地闭环验证 |\n| tool_executor | [设计 v0.1.1](<./project/B04_tool_executor模块设计.md>)、[实现与测试说明](<./project/B04_tool_executor_实现与测试说明.md>)、project/src/b04/tool_executor | 已实现；真实 Docker 条件单列 |\n| T03—T05 参考后端 | [实现与验收说明](<./project/B04_T03-T05_参考后端实现与验收说明.md>)、project/src/b04/reference_backend | 11 个 C1 接口；HTTP 500／U+0000 回归包含在测试中 |\n| 接口与交接核对 | [设计静态复查](<./project/B04_接口一致性检查报告.md>)、[C1/B03 核对](<./project/B04_C1一致性与B03存储接入核对.md>) | 区分历史设计检查与当前接入边界 |\n| 对应测试 | project/tests 下四组测试及 C1 JSON 快照 | 详见下表及 JUnit |\n| 示例与依赖 | project/examples 四个示例、pyproject.toml、reference_backend/requirements.txt | 可复现源码交付 |\n| 实验验收与证据 | [实验验收说明](<./project/B04_实验验收说明.md>)、evidence | 实际日志／逐项结果／环境记录 |\n| 来源快照 | project 下两份团队 DOCX | 原始字节及哈希保留，不属 B04 新著文档 |\n| 文件完整性 | manifest.json、SHA256SUMS.txt、包外 ZIP.sha256 | 每文件分类、大小、SHA-256 与来源 |\n\n## 本包测试\n\n| 测试组 | 通过 | 跳过 |\n| --- | --- | --- |\n'''+rows+'''\n\n完整文件列表在 [manifest.json](<./manifest.json>)，运行与证据入口见 [README](<./README.md>)。\n\n## 待交接事项\n\nB03/T02 实际 Repository、迁移及会话归属待接入验证；B05 页面真实接口联调、B06 独立验收待完成。真实 Docker 环境未满足时不得将 mock 命令测试当作真实隔离通过。当前包不宣布项目全局任务或产品计划已接受。\n'''
    (target / 'B04_交付清单.md').write_text(inventory, encoding='utf-8')
    frozen = json.loads((evidence / 'frozen_sources.json').read_text(encoding='utf-8'))
    for relative, digest in frozen.items():
        sources['project/' + relative] = {'workspace_path': relative, 'source_sha256': digest}
    entries = [dict(path=p.relative_to(target).as_posix(), category=category(p.relative_to(target).as_posix()),
                    bytes=p.stat().st_size, sha256=sha(p), **sources.get(p.relative_to(target).as_posix(), {})) for p in files(target)]
    write_json(target / 'manifest.json', dict(delivery=target.name, generated_at=datetime.now(timezone.utc).isoformat(), files=entries))
    (target / 'SHA256SUMS.txt').write_text(''.join(f'{sha(p)}  {p.relative_to(target).as_posix()}\n' for p in files(target) if p.name != 'SHA256SUMS.txt'), encoding='utf-8')
    verify(target)
    archive = target.with_suffix('.zip')
    if archive.exists():
        raise FileExistsError(archive)
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as z:
        for path in files(target):
            z.write(path, target.name + '/' + path.relative_to(target).as_posix())
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None:
            raise ValueError('ZIP integrity failed')
        for path in files(target):
            assert hashlib.sha256(z.read(target.name + '/' + path.relative_to(target).as_posix())).hexdigest() == sha(path)
    archive.with_suffix('.zip.sha256').write_text(f'{sha(archive)}  {archive.name}\n', encoding='utf-8')
    print(json.dumps({'archive': str(archive), 'bytes': archive.stat().st_size, 'sha256': sha(archive), 'payload_files': len(files(target))}, ensure_ascii=False))


def verify(target):
    manifest = json.loads((target / 'manifest.json').read_text(encoding='utf-8'))
    expected = {item['path'] for item in manifest['files']} | {'manifest.json', 'SHA256SUMS.txt'}
    actual = {p.relative_to(target).as_posix() for p in files(target)}
    if expected != actual:
        raise ValueError('File inventory changed')
    for item in manifest['files']:
        path = target / item['path']
        if sha(path) != item['sha256'] or path.stat().st_size != item['bytes']:
            raise ValueError('Manifest mismatch: ' + item['path'])
    for line in (target / 'SHA256SUMS.txt').read_text(encoding='utf-8').splitlines():
        digest, relative = line.split('  ', 1)
        if sha(target / relative) != digest:
            raise ValueError('Checksum mismatch: ' + relative)
    print(json.dumps({'verified_files': len(actual), 'delivery': target.name}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['stage', 'validate', 'finalize', 'verify'])
    parser.add_argument('delivery', type=lambda value: Path(value).resolve())
    args = parser.parse_args()
    globals()[args.action](args.delivery)
