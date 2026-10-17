'use strict';
// Hash-gated build-time patching. Importing this module never writes files.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const hashes = {
  'dist/nodes/Aws/SES/AwsSes.node.js': '51febf78584d8a6414794ff61679e8ef3570d813fd233ade58a2134c2649a835',
  'dist/nodes/Aws/SES/GenericFunctions.js': '838a53da650c3f69e55c884f50a37c7ac558c84ce850f91b932412761b85c30e',
};
function transform(base) {
  const patch = fs.readFileSync(path.join(__dirname, 'n8n-2.43.5-aws-ses-version.patch'), 'utf8');
  const output = {};
  for (const block of patch.split('--- a/').slice(1)) {
    const lines = block.split('\n');
    const relative = lines.shift();
    assert(Object.hasOwn(hashes, relative), 'unexpected patch target');
    assert.equal(lines.shift(), '+++ b/' + relative);
    const source = fs.readFileSync(path.join(base, relative), 'utf8');
    assert.equal(crypto.createHash('sha256').update(source).digest('hex'), hashes[relative], 'unaudited input file');
    let result = source;
    for (const hunk of lines.join('\n').split(/@@[^\n]*\n/).slice(1)) {
      const entries = hunk.split('\n').filter(line => /^[ +\-]/.test(line));
      const before = entries.filter(line => !line.startsWith('+')).map(line => line.slice(1)).join('\n') + '\n';
      const after = entries.filter(line => !line.startsWith('-')).map(line => line.slice(1)).join('\n') + '\n';
      assert.equal(result.split(before).length - 1, 1, 'patch context mismatch');
      result = result.replace(before, after);
    }
    assert.notEqual(result, source);
    output[path.join(base, relative)] = result;
  }
  assert.equal(Object.keys(output).length, Object.keys(hashes).length);
  return output;
}
function packageBase() {
  const root = '/usr/local/lib/node_modules/n8n/node_modules/.pnpm';
  const pkg = fs.readdirSync(root).find(name => name.startsWith('n8n-nodes-base@'));
  assert(pkg);
  assert.equal(require('/usr/local/lib/node_modules/n8n/package.json').version, '2.43.5');
  return path.join(root, pkg, 'node_modules/n8n-nodes-base');
}
module.exports = {transform, packageBase};
if (require.main === module) {
  assert.equal(process.argv[2], '--apply', 'explicit build-time --apply required');
  const transformed = transform(packageBase()); // validate all inputs before any write
  for (const [file, content] of Object.entries(transformed)) fs.writeFileSync(file, content);
  console.log('Applied verified n8n 2.43.5 SES form transport patch to two files');
}
