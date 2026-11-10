'use strict';

/**
 * 守卫：`.svelte` 的**模板表达式**里调用了 store/api 的导出，却没 import。
 *
 * 为什么需要：Svelte 5 把未定义的标识符当**全局变量**处理，编译期不报错，
 * 运行时才抛 `ReferenceError: xxx is not defined`——一次渲染异常会让整棵组件树挂掉，
 * 表现就是「整个界面都不可用」。2026-11-11 就是这样挂的（`isTranslationStale`）。
 *
 * 检查口径刻意收窄，避免误报：
 *   - 只看 `lib/store.svelte.ts` 与 `lib/api.ts` 的导出名；
 *   - 只认**函数调用** `name(`，且必须出现在 `<script>` 或 `{...}` 表达式里；
 *   - 先剥掉注释、字符串、`<style>`，所以 icon 里的 'undo'、CSS 类名不会误伤。
 */

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const RENDERER = path.join(__dirname, '..', 'renderer', 'src');

function walk(dir, out = []) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) walk(full, out);
    else out.push(full);
  }
  return out;
}

function exportedNames(file) {
  const source = fs.readFileSync(file, 'utf8');
  const names = new Set();
  const re = /^export\s+(?:async\s+)?(?:function|const|let|class|type|interface)\s+([A-Za-z_$][\w$]*)/gm;
  for (const match of source.matchAll(re)) names.add(match[1]);
  return names;
}

function stripNoise(source) {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, ' ')
    .replace(/\/\/[^\n]*/g, ' ')
    .replace(/'(?:[^'\\]|\\.)*'/g, "''")
    .replace(/"(?:[^"\\]|\\.)*"/g, '""')
    .replace(/`(?:[^`\\]|\\.)*`/g, '``');
}

/** 从 markup 里把 `{...}` 表达式抠出来（支持嵌套花括号）。 */
function expressionsOf(markup) {
  const parts = [];
  let depth = 0;
  let start = -1;
  for (let i = 0; i < markup.length; i += 1) {
    const ch = markup[i];
    if (ch === '{') {
      if (depth === 0) start = i + 1;
      depth += 1;
    } else if (ch === '}') {
      depth -= 1;
      if (depth === 0 && start >= 0) {
        parts.push(markup.slice(start, i));
        start = -1;
      }
    }
  }
  return parts.join('\n');
}

function splitFile(source) {
  const script = /<script[^>]*>([\s\S]*?)<\/script>/.exec(source);
  const withoutScript = script ? source.replace(script[0], ' ') : source;
  const markup = withoutScript.replace(/<style[^>]*>[\s\S]*?<\/style>/g, ' ');
  return { script: script ? script[1] : '', markup };
}

function importedNames(script) {
  const names = new Set();
  for (const match of script.matchAll(/import\s*\{([\s\S]*?)\}\s*from/g)) {
    for (const part of match[1].split(',')) {
      const cleaned = part.trim().replace(/^type\s+/, '');
      if (!cleaned) continue;
      const name = cleaned.split(/\s+as\s+/).pop().trim();
      if (name) names.add(name);
    }
  }
  return names;
}

function declaredNames(script) {
  const names = new Set();
  for (const match of script.matchAll(/\b(?:let|const|function|class)\s+([A-Za-z_$][\w$]*)/g)) {
    names.add(match[1]);
  }
  // `let { a, b } = $props()` —— 解构出来的也算声明
  for (const match of script.matchAll(/\{([^{}]*)\}\s*(?::[^=]+)?=\s*\$props\(\)/g)) {
    for (const part of match[1].split(',')) {
      const name = part.trim().split(':')[0].trim();
      if (/^[A-Za-z_$][\w$]*$/.test(name)) names.add(name);
    }
  }
  return names;
}

test('模板表达式里没有"调用了但没 import"的 store/api 导出', () => {
  const exported = new Set([
    ...exportedNames(path.join(RENDERER, 'lib', 'store.svelte.ts')),
    ...exportedNames(path.join(RENDERER, 'lib', 'api.ts')),
  ]);

  const problems = [];
  for (const file of walk(RENDERER).filter((f) => f.endsWith('.svelte'))) {
    const { script, markup } = splitFile(fs.readFileSync(file, 'utf8'));
    const code = `${stripNoise(script)}\n${stripNoise(expressionsOf(markup))}`;
    const imported = importedNames(script);
    const declared = declaredNames(script);
    const rel = path.relative(RENDERER, file);

    for (const name of exported) {
      if (imported.has(name) || declared.has(name)) continue;
      if (new RegExp(`(?<![.\\w$])${name}\\s*\\(`).test(code)) {
        problems.push(`${rel}: 调用了 ${name}() 但没有 import`);
      }
    }
  }

  assert.deepEqual(problems, [], `发现未导入的调用：\n${problems.join('\n')}`);
});
