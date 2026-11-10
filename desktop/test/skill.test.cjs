'use strict';

/**
 * 「一键配置 Agent 技能」的回归用例。
 *
 * 这里守的是：装完目录结构对、paths.json 带着正确的字幕目录、重复安装幂等、
 * 随包技能更新后能识别出"需要重新配置"。
 */

const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');

const { defaultTargetDir, install, listFiles, status } = require('../main/skill.cjs');

const SOURCE = path.join(__dirname, '..', 'resources', 'skill', 'kikusub-subtitle');

function tmpdir() {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'kikusub-skill-'));
}

test('随包技能目录是完整的', () => {
  const files = listFiles(SOURCE);
  assert.ok(files.includes('SKILL.md'), '缺 SKILL.md');
  assert.ok(files.includes('references/digest.md'), '缺 digest.md');
  assert.ok(files.includes('references/proposal.schema.json'), '缺 schema');
});

test('默认目标根是 DSH 会扫描的 ~/.agents/skills', () => {
  const home = path.join(os.tmpdir(), 'kikusub-home');
  const target = defaultTargetDir({ home });
  assert.equal(target, path.join(home, '.agents', 'skills', 'kikusub-subtitle'));
  // 回归：曾经装到 ~/.claude/skills，那是 Claude Code 的根，DSH 不扫，
  // 表现就是目录、文件、权限全对，但 / 斜杠菜单里永远没有 kikusub-subtitle。
  assert.ok(!target.includes(`${path.sep}.claude${path.sep}`), '目标根不能是 ~/.claude/skills');
});

test('未安装时 status 报告未安装', () => {
  const targetDir = path.join(tmpdir(), 'skills', 'kikusub-subtitle');
  const st = status({ sourceDir: SOURCE, targetDir });
  assert.equal(st.installed, false);
  assert.equal(st.upToDate, false);
  assert.equal(st.targetDir, targetDir);
});

test('install 复制文件并写入 paths.json', () => {
  const root = tmpdir();
  const targetDir = path.join(root, 'skills', 'kikusub-subtitle');
  const st = install({
    sourceDir: SOURCE,
    targetDir,
    paths: { output_dir: '/tmp/out', export_dir: '/tmp/deliver' },
  });

  assert.equal(st.installed, true);
  assert.equal(st.upToDate, true);
  assert.ok(fs.existsSync(path.join(targetDir, 'SKILL.md')));
  assert.ok(fs.existsSync(path.join(targetDir, 'references', 'digest.md')));

  const paths = JSON.parse(fs.readFileSync(path.join(targetDir, 'references', 'paths.json'), 'utf8'));
  assert.equal(paths.output_dir, '/tmp/out');
  assert.equal(paths.export_dir, '/tmp/deliver');
  assert.ok(paths.installed_at > 0);
  assert.equal(st.paths.output_dir, '/tmp/out');
});

test('重复安装是幂等的，且用最新目录覆盖', () => {
  const root = tmpdir();
  const targetDir = path.join(root, 'skills', 'kikusub-subtitle');
  install({ sourceDir: SOURCE, targetDir, paths: { output_dir: '/a', export_dir: '/b' } });
  const st = install({ sourceDir: SOURCE, targetDir, paths: { output_dir: '/c', export_dir: '/d' } });

  assert.equal(st.paths.output_dir, '/c');
  // 不会因为重复安装多出文件
  const files = listFiles(targetDir).filter((f) => f !== 'references/paths.json');
  assert.deepEqual(files, listFiles(SOURCE));
});

test('随包文件变了会标记为需要更新', () => {
  const root = tmpdir();
  const targetDir = path.join(root, 'skills', 'kikusub-subtitle');
  install({ sourceDir: SOURCE, targetDir, paths: {} });

  // 模拟"装了旧版本"：往目标里改一个文件大小
  fs.appendFileSync(path.join(targetDir, 'SKILL.md'), '\n<!-- 旧版本 -->\n');
  const st = status({ sourceDir: SOURCE, targetDir });
  assert.equal(st.installed, true);
  assert.equal(st.upToDate, false);
});

test('源目录缺 SKILL.md 时拒绝安装', () => {
  const empty = tmpdir();
  assert.throws(() => install({ sourceDir: empty, targetDir: path.join(tmpdir(), 'x') }), /不完整/);
});

test('digest 文档里的自测向量是对的', () => {
  const crypto = require('node:crypto');
  const doc = fs.readFileSync(path.join(SOURCE, 'references', 'digest.md'), 'utf8');
  const expected = crypto
    .createHash('sha256')
    .update('1\tおはよう\n2\tまたね', 'utf8')
    .digest('hex');
  assert.ok(doc.includes(expected), `digest.md 里的固定值过期了，应为 ${expected}`);
});
