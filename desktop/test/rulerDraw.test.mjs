import assert from 'node:assert/strict';
import test from 'node:test';

const { RULER_LABEL_GAP, rulerLabelX, paintRuler } = await import(
  '../renderer/src/lib/waveformDraw.ts'
);

test('右端标签被夹回画布内，而不是移到刻度左边', () => {
  const tick = 1047;
  const width = 1076;
  const labelWidth = 42;
  const x = rulerLabelX(tick, labelWidth, width);
  assert.equal(x, width - 2 - labelWidth);
  assert.ok(x < tick);
  assert.ok(x + labelWidth <= width - 2);
});

test('正常刻度标签仍在刻度右侧 +3', () => {
  assert.equal(rulerLabelX(100, 20, 800), 103);
});

test('标签比画布还宽时从 0 开始，不出现负坐标', () => {
  assert.equal(rulerLabelX(10, 900, 800), 0);
});

function fakeCtx() {
  const drawn = [];
  return {
    font: '',
    textBaseline: '',
    fillStyle: '',
    measureText: (text) => ({ width: String(text).length * 7 }),
    fillText: (text, x) => drawn.push({ text, x, width: String(text).length * 7 }),
    fillRect: () => {},
    drawn,
  };
}

function layout(width) {
  const ctx = fakeCtx();
  const viewSpan = 11138; // 185:38，用户截图里的片长
  paintRuler(ctx, {
    viewStart: 0,
    viewSpan,
    width,
    rulerH: 17,
    separator: '#ccc',
    separatorStrong: '#aaa',
    text: '#666',
    xOf: (t) => (t / viewSpan) * width,
  });
  return ctx.drawn;
}

test('185 分钟全片视图的末端标签不叠字', () => {
  const labels = layout(1076);
  assert.ok(labels.length >= 10);
  for (let i = 1; i < labels.length; i += 1) {
    const prev = labels[i - 1];
    assert.ok(
      labels[i].x >= prev.x + prev.width + RULER_LABEL_GAP - 0.01,
      `${prev.text}@${prev.x} 与 ${labels[i].text}@${labels[i].x} 重叠`,
    );
  }
});

test('窄画布放不下时只画刻度、跳过标签，绝不叠字', () => {
  const labels = layout(360);
  for (let i = 1; i < labels.length; i += 1) {
    const prev = labels[i - 1];
    assert.ok(labels[i].x >= prev.x + prev.width + RULER_LABEL_GAP - 0.01);
  }
});
