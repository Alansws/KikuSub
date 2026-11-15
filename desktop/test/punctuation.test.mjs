import assert from 'node:assert/strict';
import test from 'node:test';

import { cleanCueText, cleanLine, planClean } from '../renderer/src/lib/punctuation.ts';

/** 只看文本，省得每个断言都写 `.text`。 */
function clean(text, opts) {
  return cleanLine(text, opts).text;
}

test('行尾的顿号句号省略号按默认清掉，不留尾空格', () => {
  assert.equal(clean('凍えたままで、'), '凍えたままで');
  assert.equal(clean('人前では優しく生きていた。'), '人前では優しく生きていた');
  assert.equal(clean('しわ寄せで、。'), 'しわ寄せで');
  // 省略号默认保留，但紧贴的顿号要删
  assert.equal(clean('でもこの人、どこかで…'), 'でもこの人 どこかで…');
  assert.equal(clean('そうか、…'), 'そうか…');
});

test('句中的顿号句号换成半角空格（默认）', () => {
  assert.equal(clean('ただいま。おかえり。コロッケ買ってきたぜ'), 'ただいま おかえり コロッケ買ってきたぜ');
  assert.equal(clean('こういうことを、二ヶ月前'), 'こういうことを 二ヶ月前');
  assert.equal(clean('あ、、、い'), 'あ い');
});

test('全角空格选项只影响替换出来的那一个', () => {
  assert.equal(clean('あ、い', { space: 'full' }), 'あ　い');
  // 台词里原本的英文单词间半角空格不许被压成全角
  assert.equal(clean('Thank you、またね', { space: 'full' }), 'Thank you　またね');
  assert.equal(clean('Thank you、またね'), 'Thank you またね');
});

test('数字与英文上下文里的 . 和 , 不动', () => {
  for (const text of ['3.14', '1,000', '1,000.50', 'No.1', 'v2.0', 'A.I', '2.5倍', 'v1.2.3']) {
    assert.equal(clean(text), text, text);
  }
  // 行尾规则优先：`A.I.` 结尾那一点是句末，会被删掉（`A.I.` → `A.I`）。
  // 这是「行尾必须干净」与「缩写点保护」冲突时的取舍，写在这里当契约。
  assert.equal(clean('A.I.'), 'A.I');
  assert.equal(clean('3.14円、あと'), '3.14円 あと');
  assert.equal(clean('1,000円、高い'), '1,000円 高い');
});

test('问号与感叹号保持原样', () => {
  for (const text of ['え?', 'やった!', 'マジ？', '本当に!?', 'んっ!']) {
    assert.equal(clean(text), text, text);
  }
  assert.equal(clean('あの、どこかでお会いしましたっけ?'), 'あの どこかでお会いしましたっけ?');
});

test('行首多余标点删掉', () => {
  assert.equal(clean('、あの'), 'あの');
  assert.equal(clean('。そう'), 'そう');
  assert.equal(clean('、。あの'), 'あの');
});

test('收尾括号前的标点直接删，不补空格', () => {
  assert.equal(clean('「行く。」'), '「行く」');
  assert.equal(clean('（笑）、'), '（笑）');
  assert.equal(clean('「そう、そう」'), '「そう そう」');
});

test('省略号开关打开后按普通标点清理', () => {
  assert.equal(clean('そうか…', { stripEllipsis: true }), 'そうか');
  assert.equal(clean('そうか…また', { stripEllipsis: true }), 'そうか また');
  assert.equal(clean('そうか...', { stripEllipsis: true }), 'そうか');
});

test('半角三点默认整体保留，不被拆成三个句点', () => {
  assert.equal(clean('そうか...'), 'そうか...');
  assert.equal(clean('そうか...、'), 'そうか...');
});

test('多行字幕逐行清理并保留换行', () => {
  const out = cleanCueText('あ、\nい。');
  assert.equal(out.text, 'あ\nい');
  // 两行各自的句尾都被删：合计 2 处行尾、0 处句中
  assert.equal(out.end, 2);
  assert.equal(out.mid, 0);
});

test('清完是空的就回退原文，绝不产出空字幕', () => {
  const one = cleanLine('、。');
  assert.equal(one.text, '、。');
  assert.equal(one.reverted, true);
  assert.equal(cleanLine('…', { stripEllipsis: true }).reverted, true);
});

test('空行与纯空白原样返回', () => {
  assert.deepEqual(cleanLine(''), { text: '', end: 0, mid: 0, reverted: false });
  assert.deepEqual(cleanLine('   '), { text: '   ', end: 0, mid: 0, reverted: false });
});

test('幂等：清两次结果一样', () => {
  const once = clean('あの、どこかで…お会いしました?');
  assert.equal(clean(once), once);
});

test('planClean 逐条对齐并给出统计与跳过项', () => {
  const texts = ['こういうことを、二ヶ月前', 'え?', '、。', 'ただいま。おかえり。'];
  const plan = planClean(texts);
  assert.equal(plan.texts.length, texts.length);
  assert.deepEqual(plan.changed, [0, 3]);
  assert.deepEqual(plan.skipped, [2]);
  assert.equal(plan.texts[1], 'え?');
  assert.equal(plan.texts[2], '、。');
  assert.equal(plan.texts[3], 'ただいま おかえり');
  assert.equal(plan.endMarks, 1);
  assert.equal(plan.midMarks, 2);
});

test('planClean 统计行尾与句中的处数', () => {
  const plan = planClean(['あ、', 'い。', 'う、え']);
  assert.deepEqual(plan.changed, [0, 1, 2]);
  assert.equal(plan.endMarks, 2);
  assert.equal(plan.midMarks, 1);
});
