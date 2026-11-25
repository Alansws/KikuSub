import assert from 'node:assert/strict';
import test from 'node:test';

import { cleanCueText, cleanLine, markedSpans, planClean } from '../renderer/src/lib/punctuation.ts';

/** 只看文本，省得每个断言都写 `.text`。 */
function clean(text, opts) {
  return cleanLine(text, opts).text;
}

test('行尾的顿号句号省略号按默认清掉，不留尾空格', () => {
  assert.equal(clean('凍えたままで、'), '凍えたままで');
  assert.equal(clean('人前では優しく生きていた。'), '人前では優しく生きていた');
  assert.equal(clean('しわ寄せで、。'), 'しわ寄せで');
  // 省略号在行尾默认就清（字幕条尾的 … 基本是断句噪音），紧贴的顿号也删
  assert.equal(clean('そうか、…'), 'そうか');
  assert.equal(clean('大きく深呼吸してみましょうか。 吸って…'), '大きく深呼吸してみましょうか吸って');
});

test('句中的顿号句号默认直接删掉，不补空格', () => {
  assert.equal(clean('こういうことを、二ヶ月前'), 'こういうことを二ヶ月前');
  assert.equal(clean('ただいま。おかえり。'), 'ただいまおかえり');
  assert.equal(clean('あ、、、い'), 'あい');
  assert.equal(clean('吐いて、もう一回'), '吐いてもう一回');
});

test('标记后面跟着的空格一起吃掉，不留孤零零的空格', () => {
  assert.equal(clean('吐いて、 もう一回'), '吐いてもう一回');
  assert.equal(clean('吐いて、　もう一回'), '吐いてもう一回');
  assert.equal(clean('吐いて 、もう一回'), '吐いてもう一回');
});

test('紧邻英文 / 数字时补一个半角空格，别把两个词粘成一个', () => {
  assert.equal(clean('Thank you、またね'), 'Thank you またね');
  assert.equal(clean('はい、OK'), 'はい OK');
  assert.equal(clean('100、200'), '100 200');
});

test('旧口径仍可选：句中换成半角 / 全角空格', () => {
  assert.equal(clean('吐いて、もう一回', { mid: 'half' }), '吐いて もう一回');
  assert.equal(clean('吐いて、もう一回', { mid: 'full' }), '吐いて　もう一回');
  // 台词里原本的英文单词间半角空格不许被压成全角
  assert.equal(clean('Thank you、またね', { mid: 'full' }), 'Thank you　またね');
  assert.equal(clean('Thank you、またね', { mid: 'half' }), 'Thank you またね');
});

test('省略号默认只清行尾，句中（语气）保留', () => {
  assert.equal(clean('大きく深呼吸して…'), '大きく深呼吸して');
  assert.equal(clean('そうか...'), 'そうか');
  assert.equal(clean('そうか……'), 'そうか');
  // 收尾括号里的省略号也算行尾
  assert.equal(clean('「吸って…」'), '「吸って」');
  // 省略号后面只剩同样要清掉的句号，一样算行尾
  assert.equal(clean('吸って…。'), '吸って');
  // 句中的不动
  assert.equal(clean('あの…そう'), 'あの…そう');
  assert.equal(clean('でもこの人、どこかで…'), 'でもこの人どこかで');
});

test('省略号口径：全部删 / 全部保留', () => {
  assert.equal(clean('あの…そう', { ellipsis: 'all' }), 'あのそう');
  assert.equal(clean('あの…、そう', { ellipsis: 'all' }), 'あのそう');
  assert.equal(clean('そうか…', { ellipsis: 'all' }), 'そうか');
  assert.equal(clean('そうか...', { ellipsis: 'all' }), 'そうか');
  assert.equal(clean('「吸って…」', { ellipsis: 'keep' }), '「吸って…」');
  assert.equal(clean('でもこの人、どこかで…', { ellipsis: 'keep' }), 'でもこの人どこかで…');
});

test('半角 ｡ ､ 与全角等价处理', () => {
  assert.equal(clean('吐いて､もう一回'), '吐いてもう一回');
  assert.equal(clean('吐いて､もう一回｡'), '吐いてもう一回');
  assert.equal(clean('､あの'), 'あの');
});

test('数字与英文上下文里的 . 和 , 不动', () => {
  for (const text of ['3.14', '1,000', '1,000.50', 'No.1', 'v2.0', 'A.I', '2.5倍', 'v1.2.3']) {
    assert.equal(clean(text), text, text);
  }
  // 行尾规则优先：`A.I.` 结尾那一点是句末，会被删掉（`A.I.` → `A.I`）。
  // 这是「行尾必须干净」与「缩写点保护」冲突时的取舍，写在这里当契约。
  assert.equal(clean('A.I.'), 'A.I');
  assert.equal(clean('3.14円、あと'), '3.14円あと');
  assert.equal(clean('1,000円、高い'), '1,000円高い');
});

test('问号与感叹号保持原样', () => {
  for (const text of ['え?', 'やった!', 'マジ？', '本当に!?', 'んっ!']) {
    assert.equal(clean(text), text, text);
  }
  assert.equal(clean('あの、どこかでお会いしましたっけ?'), 'あのどこかでお会いしましたっけ?');
});

test('行首多余标点删掉', () => {
  assert.equal(clean('、あの'), 'あの');
  assert.equal(clean('。そう'), 'そう');
  assert.equal(clean('、。あの'), 'あの');
});

test('收尾括号前的标点直接删，不补空格', () => {
  assert.equal(clean('「行く。」'), '「行く」');
  assert.equal(clean('（笑）、'), '（笑）');
  assert.equal(clean('「そう、そう」'), '「そうそう」');
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
  assert.equal(cleanLine('…', { ellipsis: 'all' }).reverted, true);
});

test('空行与纯空白原样返回', () => {
  assert.deepEqual(cleanLine(''), { text: '', end: 0, mid: 0, reverted: false });
  assert.deepEqual(cleanLine('   '), { text: '   ', end: 0, mid: 0, reverted: false });
});

test('统计口径：行尾删掉的（含行尾省略号）记 end，句中处理掉的记 mid', () => {
  const one = cleanLine('大きく深呼吸してみましょうか。 吸って…');
  assert.equal(one.end, 1);
  assert.equal(one.mid, 1);
});

test('幂等：清两次结果一样', () => {
  for (const text of [
    'あの、どこかで…お会いしました?',
    'Thank you、またね',
    '吐いて、 もう一回',
    '「吸って…」',
  ]) {
    const once = clean(text);
    assert.equal(clean(once), once, text);
  }
});

test('planClean 逐条对齐并给出统计与跳过项', () => {
  const texts = ['こういうことを、二ヶ月前', 'え?', '、。', 'ただいま。おかえり。'];
  const plan = planClean(texts);
  assert.equal(plan.texts.length, texts.length);
  assert.deepEqual(plan.changed, [0, 3]);
  assert.deepEqual(plan.skipped, [2]);
  assert.equal(plan.texts[1], 'え?');
  assert.equal(plan.texts[2], '、。');
  assert.equal(plan.texts[3], 'ただいまおかえり');
  assert.equal(plan.endMarks, 1);
  assert.equal(plan.midMarks, 2);
});

test('planClean 把只以行尾省略号结尾的条目算进 changed', () => {
  const plan = planClean(['吸って…', 'あの…そう', 'しぶい。']);
  assert.deepEqual(plan.changed, [0, 2]);
  assert.equal(plan.texts[0], '吸って');
  assert.equal(plan.texts[1], 'あの…そう');
  assert.equal(plan.texts[2], 'しぶい');
  assert.equal(plan.endMarks, 2);
});

test('planClean 统计行尾与句中的处数', () => {
  const plan = planClean(['あ、', 'い。', 'う、え']);
  assert.deepEqual(plan.changed, [0, 1, 2]);
  assert.equal(plan.endMarks, 2);
  assert.equal(plan.midMarks, 1);
});

test('markedSpans 只标这次真要删的字符', () => {
  const tail = markedSpans('吸って…', {});
  assert.deepEqual(
    tail.filter((s) => s.hit).map((s) => s.text),
    ['…'],
  );
  // 句中的省略号保留 → 不标
  const mid = markedSpans('あの…そう', {});
  assert.deepEqual(
    mid.filter((s) => s.hit).map((s) => s.text),
    [],
  );
  // 小数点的点受保护 → 只标顿号
  const num = markedSpans('3.14円、あと', {});
  assert.deepEqual(
    num.filter((s) => s.hit).map((s) => s.text),
    ['、'],
  );
  // 口径改成全删时，句中的省略号要标出来
  const all = markedSpans('あの…そう', { ellipsis: 'all' });
  assert.deepEqual(
    all.filter((s) => s.hit).map((s) => s.text),
    ['…'],
  );
});

// ---------------------------------------------------------------------------
// 译文轨（target）：2026-11-25 用户要求「译文标点也要能清，但规则要适配」
//
// 关键差别：中文的句中逗号 / 顿号 / 省略号都是语义，删掉会把句子黏死，
// 所以 target 档只做行首行尾 + 折叠重复 + 收空白。
// ---------------------------------------------------------------------------

/** 译文轨清理的简写。 */
function tclean(text, extras) {
  return cleanLine(text, { flavor: 'target', ...(extras || {}) }).text;
}

test('译文轨：行尾句读清掉，句中语义标点保留', () => {
  assert.equal(tclean('呼…刚刚好舒服。'), '呼…刚刚好舒服');
  assert.equal(tclean('今天，下雨了。'), '今天，下雨了');
  assert.equal(tclean('他说：走吧。'), '他说：走吧');
  assert.equal(tclean('呼…刚刚好舒服'), '呼…刚刚好舒服');
  assert.equal(tclean('别碰我！'), '别碰我！');
  assert.equal(tclean('真的吗？'), '真的吗？');
  // 行尾省略号默认清（与原文口径一致），句中保留
  assert.equal(tclean('啊…'), '啊');
  assert.equal(tclean('好……'), '好');
  assert.equal(tclean('等等...'), '等等');
});

test('译文轨：行首多余标点删掉，不补空格', () => {
  assert.equal(tclean('，你好'), '你好');
  assert.equal(tclean('。今天下雨'), '今天下雨');
  assert.equal(tclean('、。 走吧'), '走吧');
});

test('译文轨：连续重复的语义标点折叠成一个', () => {
  assert.equal(tclean('啊，，别'), '啊，别');
  assert.equal(tclean('等等、、我说'), '等等、我说');
  assert.equal(tclean('好；；算了'), '好；算了');
  // 问号感叹号是强调，不折叠
  assert.equal(tclean('真的？？'), '真的？？');
  assert.equal(tclean('走吧！！'), '走吧！！');
  // 英文三点省略号不是「重复的点」，不能被折叠成一个点
  assert.equal(tclean('Well... maybe'), 'Well... maybe');
});

test('译文轨：省略号口径可切「保留」', () => {
  assert.equal(tclean('啊…', { target: { ellipsis: false } }), '啊…');
  assert.equal(tclean('呼…刚刚好舒服。', { target: { ellipsis: false } }), '呼…刚刚好舒服');
  assert.equal(tclean('等等...', { target: { ellipsis: false } }), '等等...');
  // 省略号后面还跟着句号：句号要清，省略号要留
  assert.equal(tclean('等等...。', { target: { ellipsis: false } }), '等等...');
  assert.equal(tclean('啊…。', { target: { ellipsis: false } }), '啊…');
  // 默认「清」时两轮都清掉
  assert.equal(tclean('啊…。'), '啊');
});

test('译文轨：数字与英文缩写点受保护', () => {
  assert.equal(tclean('价格是 3.14。'), '价格是 3.14');
  assert.equal(tclean('1,000 日元'), '1,000 日元');
  // 英文缩写点：`U.S.` 的句点保留（只在 lang=en 时保护）
  assert.equal(tclean('It is U.S.', { lang: 'en' }), 'It is U.S.');
  assert.equal(tclean('Hello, world.', { lang: 'en' }), 'Hello, world');
  assert.equal(tclean('Are you  ok?', { lang: 'en' }), 'Are you ok?');
});

test('译文轨：多行逐行处理，清空回退原文', () => {
  const out = cleanCueText('啊…\n呼…刚刚好舒服。', { flavor: 'target' });
  assert.equal(out.text, '啊\n呼…刚刚好舒服');
  assert.equal(out.end, 2);
  // 只由标点组成的一行不能清成空译文
  assert.equal(tclean('。'), '。');
  assert.equal(cleanLine('……', { flavor: 'target' }).reverted, true);
});

test('译文轨：markedSpans 只标这次真要删的字符', () => {
  const hits = (text, extras) =>
    markedSpans(text, { flavor: 'target', ...(extras || {}) })
      .filter((seg) => seg.hit)
      .map((seg) => seg.text);

  assert.deepEqual(hits('呼…刚刚好舒服。'), ['。']);
  assert.deepEqual(hits('啊…'), ['…']);
  assert.deepEqual(hits('呼…刚刚好舒服'), []);
  assert.deepEqual(hits('啊，，别'), ['，']);
  assert.deepEqual(hits('，你好'), ['，']);
  assert.deepEqual(hits('别碰我！'), []);
});

test('译文轨：planClean 对齐条数与统计', () => {
  const plan = planClean(['啊…', '呼…刚刚好舒服', '别碰我！', '。'], {
    flavor: 'target',
  });
  assert.deepEqual(plan.changed, [0]);
  assert.deepEqual(plan.skipped, [3]);
  assert.equal(plan.texts[1], '呼…刚刚好舒服');
  assert.equal(plan.texts[3], '。');
});
