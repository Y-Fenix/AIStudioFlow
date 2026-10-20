const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');

const themesCss = fs.readFileSync(new URL('../web/themes.css', `file://${__filename}`), 'utf8');

test('overview and department home top modules share compact desktop height and reset for mobile stacking', () => {
  assert.match(themesCss, /\.hero-grid,\.department-hero-grid\s*\{[^}]*min-height:var\(--home-module-height\)[^}]*grid-auto-rows:var\(--home-module-height\)/);
  assert.match(themesCss, /\.hero-grid>\.hero,[\s\S]*?\.department-hero-grid>\.home-checkpoint\s*\{[^}]*height:100%[^}]*min-height:var\(--home-module-height\)/);
  assert.match(themesCss, /--home-module-height:\s*270px/);
  assert.match(themesCss, /@media\(max-width:1100px\)[\s\S]*--home-module-height:\s*290px/);
  assert.match(themesCss, /@media\(max-width:760px\)[\s\S]*--home-module-height:\s*auto/);
});
