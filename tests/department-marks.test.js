const test=require('node:test'),assert=require('node:assert/strict');
const marks=require('../web/department-marks.js');
test('five department hero marks have distinct role graphics and accessible identities',()=>{
 const ids=['product','design','development','testing','growth'];
 const values=ids.map(id=>marks.hero(id));
 assert.equal(new Set(values).size,5);
 for(const value of values){assert.match(value,/<svg/);assert.match(value,/<title>/);assert.doesNotMatch(value,/<script|http|onload=/)}
 assert.equal(marks.hero('unknown'),'');
});
