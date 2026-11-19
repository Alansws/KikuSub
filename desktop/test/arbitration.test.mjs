import assert from 'node:assert/strict';
import test from 'node:test';

import {
  adoptLabel,
  canAdopt,
  classifyText,
  contextFor,
  isFreshRecord,
} from '../renderer/src/lib/arbitration.ts';

function cue(start, end, text = '') {
  return { start, end, text };
}

test('contextFor takes three nearest by time, excluding the current index', () => {
  const cues = [
    cue(8, 9, '后2'),
    cue(0, 1, '前1'),
    cue(4, 5, '当前'),
    cue(2, 3, '前2'),
    cue(6, 7, '后1'),
    cue(10, 11, '后3'),
    cue(1.2, 2.4, '前3'),
  ];
  const ctx = contextFor(cues, 2);
  assert.deepEqual(ctx.before, ['前1', '前3', '前2']);
  assert.deepEqual(ctx.after, ['后1', '后2', '后3']);
});

test('contextFor keeps neighbours that overlap due to selection padding', () => {
  // 当前句 5.0-7.0，邻句被 pad 到 4.7-5.1 / 6.9-7.3：不能按 end <= start 过滤。
  const cues = [cue(4.7, 5.1, '重叠前'), cue(5.0, 7.0, '当前'), cue(6.9, 7.3, '重叠后')];
  const ctx = contextFor(cues, 1);
  assert.deepEqual(ctx.before, ['重叠前']);
  assert.deepEqual(ctx.after, ['重叠后']);
});

test('contextFor skips empty text and caps at radius', () => {
  const cues = [
    cue(0, 1, ''),
    cue(1, 2, 'a'),
    cue(2, 3, 'b'),
    cue(3, 4, 'c'),
    cue(4, 5, 'd'),
    cue(5, 6, '当前'),
  ];
  const ctx = contextFor(cues, 5);
  assert.deepEqual(ctx.before, ['b', 'c', 'd']);
  assert.deepEqual(ctx.after, []);
});

test('classifyText distinguishes same-as-A, same-as-B and third', () => {
  assert.equal(classifyText('A', 'B', 'A'), 'a');
  assert.equal(classifyText('A', 'B', 'B'), 'b');
  assert.equal(classifyText('A', 'B', 'C'), 'third');
  assert.equal(classifyText('A', 'B', ' A '), 'a');
});

test('isFreshRecord guards media, time, A and B snapshots', () => {
  const record = {
    start: 1,
    end: 2,
    textA: 'A',
    textB: 'B',
    text: 'C',
    note: '',
    model: 'm',
    mediaId: 'm1',
  };
  assert.equal(isFreshRecord(record, cue(1, 2, 'A'), 'B', 'm1'), true);
  assert.equal(isFreshRecord(record, cue(1.1, 2, 'A'), 'B', 'm1'), false);
  assert.equal(isFreshRecord(record, cue(1, 2, 'A2'), 'B', 'm1'), false);
  assert.equal(isFreshRecord(record, cue(1, 2, 'A'), 'B2', 'm1'), false);
  assert.equal(isFreshRecord(record, cue(1, 2, 'A'), 'B', 'm2'), false);
  assert.equal(isFreshRecord(null, cue(1, 2, 'A'), 'B', 'm1'), false);
});


test('same-as-B keeps an adopt button labelled 同 B 版', () => {
  assert.equal(canAdopt('b'), true);
  assert.equal(adoptLabel('b'), '采用（同 B 版）');
  assert.equal(canAdopt('a'), false);
  assert.equal(adoptLabel('third'), '采用 AI 版');
});

import {
  arbitrationButtonLabel,
  cueThreadKey,
  historyForRequest,
  isFreshThread,
  MAX_HISTORY_CHARS,
  MAX_HISTORY_ROUNDS,
} from '../renderer/src/lib/arbitration.ts';

function thread(start, end, textA, textB) {
  return {
    key: 'k',
    mediaId: 'm1',
    start,
    end,
    textA,
    textB,
    draft: '',
    messages: [],
    updatedAt: 0,
  };
}

test('cueThreadKey combines media and millisecond time', () => {
  assert.equal(cueThreadKey('m1', { start: 1.23456, end: 2.34567 }), 'm1|1.235|2.346');
  assert.equal(cueThreadKey('', { start: 0, end: 1 }), '|0.000|1.000');
});

test('isFreshThread guards media, time, A and B', () => {
  const t = thread(1, 2, 'A', 'B');
  assert.equal(isFreshThread(t, cue(1, 2, 'A'), 'B', 'm1'), true);
  assert.equal(isFreshThread(t, cue(1.1, 2, 'A'), 'B', 'm1'), false);
  assert.equal(isFreshThread(t, cue(1, 2, 'A2'), 'B', 'm1'), false);
  assert.equal(isFreshThread(t, cue(1, 2, 'A'), 'B2', 'm1'), false);
  assert.equal(isFreshThread(t, cue(1, 2, 'A'), 'B', 'm2'), false);
  assert.equal(isFreshThread(null, cue(1, 2, 'A'), 'B', 'm1'), false);
});

test('historyForRequest keeps the latest six rounds and drops old ones', () => {
  const messages = [];
  for (let i = 1; i <= 8; i += 1) {
    messages.push({ role: 'user', text: `追问${i}` });
    messages.push({ role: 'assistant', text: `答复${i}` });
  }
  const out = historyForRequest(messages);
  assert.equal(out.length, MAX_HISTORY_ROUNDS * 2);
  assert.equal(out[0].text, '追问3');
  assert.equal(out.at(-1).text, '答复8');
});

test('historyForRequest keeps a leading assistant as prior context', () => {
  const out = historyForRequest([
    { role: 'assistant', text: '开头就是 AI' },
    { role: 'user', text: '用户线索' },
    { role: 'assistant', text: 'AI 回答' },
  ]);
  assert.deepEqual(out, [
    { role: 'assistant', text: '开头就是 AI' },
    { role: 'user', text: '用户线索' },
    { role: 'assistant', text: 'AI 回答' },
  ]);
});

test('historyForRequest stays within the character budget', () => {
  const messages = [];
  for (let i = 0; i < 6; i += 1) {
    messages.push({ role: 'user', text: '问'.repeat(260) });
    messages.push({ role: 'assistant', text: '答'.repeat(260) });
  }
  const out = historyForRequest(messages);
  const chars = out.reduce((sum, item) => sum + item.text.length + 4, 0);
  assert.ok(chars <= MAX_HISTORY_CHARS, `${chars} > ${MAX_HISTORY_CHARS}`);
});

test('arbitrationButtonLabel adapts to materials', () => {
  assert.equal(
    arbitrationButtonLabel({ textA: 'A', textB: 'B', hint: '', hasRecord: false }),
    '让 AI 判定',
  );
  assert.equal(
    arbitrationButtonLabel({ textA: 'A', textB: '', hint: '', hasRecord: false }),
    '让 AI 辅助修正',
  );
  assert.equal(
    arbitrationButtonLabel({ textA: '', textB: '', hint: '斯国一', hasRecord: false }),
    '根据线索推断',
  );
  assert.equal(
    arbitrationButtonLabel({ textA: '', textB: '', hint: '', hasRecord: false }),
    '根据上下文与线索推断',
  );
  assert.equal(
    arbitrationButtonLabel({ textA: 'A', textB: 'B', hint: '', hasRecord: true }),
    '重新判定',
  );
  assert.equal(
    arbitrationButtonLabel({ textA: 'A', textB: 'B', hint: '再听', hasRecord: true }),
    '重新判定',
  );
  assert.equal(
    arbitrationButtonLabel({ textA: 'A', textB: 'A', hint: '', hasRecord: false }),
    '让 AI 复核',
  );
});

import {
  hasFollowUpHistory,
  lastUserPosition,
  planArbitrationRequest,
  rejudgeButtonLabel,
  truncateFromUser,
} from '../renderer/src/lib/arbitration.ts';

function conversation() {
  return [
    { role: 'assistant', text: '第一轮干净结果', note: 'round 1' },
    { role: 'user', text: '旧追问：像 kokoro' },
    { role: 'assistant', text: '被带偏的第二轮', note: 'round 2' },
    { role: 'user', text: '旧追问二：再听一遍' },
    { role: 'assistant', text: '被带偏的第三轮', note: 'round 3' },
  ];
}

test('planArbitrationRequest: clean rejudge drops every old message and empty draft hint', () => {
  const plan = planArbitrationRequest({ mode: 'rejudge', draft: '', messages: conversation() });
  assert.deepEqual(plan.history, []);
  assert.equal(plan.hint, '');
  assert.equal(plan.resetThread, true);
  assert.equal(plan.recordHint, false);
});

test('planArbitrationRequest: rejudge may use a newly typed clue but still no history', () => {
  const plan = planArbitrationRequest({
    mode: 'rejudge',
    draft: '这次只按新线索：koko',
    messages: conversation(),
  });
  assert.deepEqual(plan.history, []);
  assert.equal(plan.hint, '这次只按新线索：koko');
  assert.equal(plan.resetThread, true);
  assert.equal(plan.recordHint, true);
});

test('planArbitrationRequest: followup is the only mode that carries history', () => {
  const messages = conversation();
  const plan = planArbitrationRequest({ mode: 'followup', draft: '再听一遍', messages });
  assert.equal(plan.history.length, messages.length);
  assert.equal(plan.history[0].text, '第一轮干净结果');
  assert.equal(plan.hint, '再听一遍');
  assert.equal(plan.resetThread, false);
  assert.equal(plan.recordHint, true);

  const empty = planArbitrationRequest({ mode: 'followup', draft: '   ', messages });
  assert.equal(empty.hint, '');
  assert.equal(empty.recordHint, false);
  assert.equal(empty.history.length, messages.length);
});

test('planArbitrationRequest: auto and initial start clean', () => {
  for (const mode of ['auto', 'initial']) {
    const plan = planArbitrationRequest({
      mode,
      draft: mode === 'initial' ? '首轮线索' : '自动模式不应读草稿',
      messages: conversation(),
    });
    assert.deepEqual(plan.history, [], `${mode} 不该携带历史`);
    assert.equal(plan.resetThread, true);
  }
  const auto = planArbitrationRequest({ mode: 'auto', draft: '草稿', messages: conversation() });
  assert.equal(auto.hint, '');
  const initial = planArbitrationRequest({ mode: 'initial', draft: '首轮线索', messages: conversation() });
  assert.equal(initial.hint, '首轮线索');
});

test('hasFollowUpHistory only counts real follow-ups', () => {
  assert.equal(hasFollowUpHistory([]), false);
  assert.equal(hasFollowUpHistory([{ role: 'assistant', text: '只有第一轮' }]), false);
  assert.equal(hasFollowUpHistory(conversation()), true);
  assert.equal(hasFollowUpHistory([{ role: 'assistant', text: 'a' }, { role: 'assistant', text: 'b' }]), true);
});

test('rejudgeButtonLabel makes the history-clearing action explicit', () => {
  assert.equal(rejudgeButtonLabel(false), '重新判定');
  assert.equal(rejudgeButtonLabel(true), '清空追问并重判');
});

test('lastUserPosition and truncateFromUser cut a round and everything after it', () => {
  const messages = conversation();
  assert.equal(lastUserPosition(messages), 3);
  assert.deepEqual(
    truncateFromUser(messages, 3).map((item) => item.text),
    ['第一轮干净结果', '旧追问：像 kokoro', '被带偏的第二轮'],
  );
  assert.deepEqual(
    truncateFromUser(messages, 1).map((item) => item.text),
    ['第一轮干净结果'],
  );
  // 不是用户气泡的位置原样返回；UI 用长度差判断是否真的撤销了东西。
  assert.equal(truncateFromUser(messages, 0).length, messages.length);
  assert.equal(truncateFromUser(messages, -1).length, messages.length);
  assert.equal(truncateFromUser(messages, 99).length, messages.length);
  assert.equal(lastUserPosition([{ role: 'assistant', text: 'a' }]), -1);
});
