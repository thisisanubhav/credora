'use strict';
// Optional build-time overlay; NOT deployed by the existing Dockerfile.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const transport = require('./apply-n8n-ses-patch.cjs');
function transform(base) {
  assert.equal(require('/usr/local/lib/node_modules/n8n/package.json').version, '2.43.5');
  const output = transport.transform(base); // hash-check pristine pinned files first
  const file = path.join(base, 'dist/nodes/Aws/SES/AwsSes.node.js');
  const before = 'this.helpers.returnJsonArray({ error: error.message })';
  const after = "this.helpers.returnJsonArray({ error: 'SES request failed; inspect safe diagnostics', ses_diagnostics: sesSafeDiagnostics(error) })";
  assert.equal(output[file].split(before).length - 1, 1, 'diagnostic patch context mismatch');
  const sanitizer = fs.readFileSync(path.join(__dirname, 'ses-safe-diagnostics.cjs'), 'utf8');
  const functionSource = sanitizer.slice(sanitizer.indexOf('function sesSafeDiagnostics'), sanitizer.indexOf('module.exports'));
  output[file] = output[file].replace(before, after) + '\n' + functionSource;
  return output;
}
module.exports = {transform};
if (require.main === module) {
  assert.equal(process.argv[2], '--apply');
  const output = transform(transport.packageBase());
  for (const [file, content] of Object.entries(output)) fs.writeFileSync(file, content);
  console.log('Applied pinned SES transport and safe diagnostic overlay');
}
