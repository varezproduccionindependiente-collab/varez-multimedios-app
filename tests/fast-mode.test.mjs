import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

test('fast mode preserves each Gemini fallback model URL',async()=>{
  const requested=[];
  const nativeFetch=async url=>{requested.push(String(url));return new Response('{}',{status:503})};
  const context=vm.createContext({
    Response,setTimeout,
    localStorage:{removeItem(){}},
    document:{querySelector(){return null}},
    window:{fetch:nativeFetch}
  });
  vm.runInContext(fs.readFileSync(new URL('../fast-mode.js',import.meta.url),'utf8'),context);
  const first='https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent';
  const fallback='https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent';
  await context.window.fetch(first,{});
  await context.window.fetch(fallback,{});
  assert.deepEqual(requested,[first,fallback]);
});
