import assert from 'node:assert/strict';
import test from 'node:test';

import {
  clampFloatBox,
  defaultFloatBox,
  parseFloatBox,
} from '../renderer/src/lib/floatBox.ts';

test('clampFloatBox keeps the box inside the viewport', () => {
  const box = clampFloatBox({ x: -20, y: 2000, w: 100, h: 100 }, { w: 1200, h: 800 });
  assert.equal(box.x, 8);
  assert.equal(box.y, 800 - box.h - 8);
  assert.equal(box.w, 360);
  assert.equal(box.h, 300);
});

test('clampFloatBox shrinks oversized boxes', () => {
  const box = clampFloatBox({ x: 0, y: 0, w: 5000, h: 5000 }, { w: 1000, h: 700 });
  assert.equal(box.w, 1000 - 16);
  assert.equal(box.h, 700 - 16);
  assert.equal(box.x, 8);
  assert.equal(box.y, 8);
});

test('defaultFloatBox avoids the right inspector and stays visible', () => {
  const box = defaultFloatBox({ w: 1360, h: 838 });
  assert.equal(box.x, 268);
  assert.equal(box.y, 84);
  assert.ok(box.x + box.w < 1360);
  assert.ok(box.y + box.h <= 838);
});

test('defaultFloatBox shifts left on narrow windows so the inspector stays usable', () => {
  const box = defaultFloatBox({ w: 1000, h: 700 });
  assert.equal(box.x, 120);
  assert.ok(box.x + box.w <= 1000 - 400);
});

test('parseFloatBox rejects broken values and clamps good ones', () => {
  assert.equal(parseFloatBox('nope', { w: 1200, h: 800 }), null);
  assert.equal(parseFloatBox('{"x":1}', { w: 1200, h: 800 }), null);
  const box = parseFloatBox('{"x":-50,"y":10,"w":500,"h":500}', { w: 1200, h: 800 });
  assert.equal(box.x, 8);
  assert.equal(box.y, 10);
  assert.equal(box.w, 500);
});
