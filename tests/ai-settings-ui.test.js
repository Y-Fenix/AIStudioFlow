const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');

const studio = fs.readFileSync(require.resolve('../web/studio.js'), 'utf8');

test('AI settings disclose that relay config belongs to the server Mac, not each browser user', () => {
  assert.match(studio, /服务端 Mac/);
  assert.match(studio, /用户个人 Mac 的中转站不会自动读取/);
  assert.match(studio, /整个工作室/);
});
