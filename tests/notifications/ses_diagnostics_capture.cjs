'use strict';
const fs = require('node:fs');
const Module = require('node:module');
const assert = require('node:assert/strict');
const {sesSafeDiagnostics} = require('/audit/patches/ses-safe-diagnostics.cjs');
const id = '12345678-1234-4234-8234-123456789abc';
const secret = 'sensitive-placeholder-do-not-retain';
const xml = code => `<ErrorResponse><Error><Code>${code}</Code><Message>${secret}</Message></Error><RequestId>${id}</RequestId></ErrorResponse>`;
for (const code of ['MessageRejected', 'InvalidParameterValue', 'SignatureDoesNotMatch']) {
  const error = new Error(secret);
  error.statusCode = 400;
  error.error = xml(code);
  error.options = {headers: {Authorization: secret}, body: secret};
  const nested = new Error(secret, {cause: error});
  assert.deepEqual(sesSafeDiagnostics(nested), {http_status: 400, aws_error_code: code, request_id: id});
}
const cyclic = {message: secret, status: '400 '+secret, Code: secret, RequestId: secret};
cyclic.cause = cyclic;
assert.deepEqual(sesSafeDiagnostics(cyclic), {http_status:null, aws_error_code:null, request_id:null});
assert.deepEqual(sesSafeDiagnostics({error: 'x'.repeat(65537) + xml('MessageRejected')}), {http_status:null, aws_error_code:null, request_id:null});
assert.deepEqual(sesSafeDiagnostics({response:{status:403,headers:{'x-amzn-requestid':id},data:{Error:{Code:'AccessDenied',Message:secret}}}}), {http_status:403,aws_error_code:'AccessDenied',request_id:id});
assert.deepEqual(sesSafeDiagnostics({error:'<Code>UnknownPrivateValue</Code><RequestId>private</RequestId>'}), {http_status:null,aws_error_code:null,request_id:null});
let source = fs.readFileSync('/audit/tests/notifications/ses_offline_capture.cjs', 'utf8');
function replace(before, after) {
  assert.equal(source.split(before).length-1, 1);
  source = source.replace(before, after);
}
replace("require('/audit/patches/apply-n8n-ses-patch.cjs')", "require('/audit/patches/apply-n8n-ses-diagnostics.cjs')");
replace('let captured;', 'let captured; let diagnosticRequests = 0;');
replace("assert.equal(type, 'aws');", "assert.equal(type, 'aws'); diagnosticRequests++;");
replace('continueOnFail: () => false', 'continueOnFail: () => true');
replace("return '<SendEmailResponse><SendEmailResult><MessageId>synthetic-only</MessageId></SendEmailResult></SendEmailResponse>';", `
const failure = new Error('sensitive-placeholder-do-not-retain');
failure.statusCode = 400;
failure.error = ${JSON.stringify(xml(process.argv[3] || 'MessageRejected'))};
failure.options = {headers:{Authorization:'sensitive-placeholder-do-not-retain'}};
const {NodeApiError} = Module.createRequire(nodeFile)('n8n-workflow');
throw new NodeApiError(context.getNode(), failure);
`);
replace('new AwsSes().execute.call(context).then(() => {', 'new AwsSes().execute.call(context).then(result => {');
replace('console.log(JSON.stringify(captured));', `
assert.equal(diagnosticRequests, 1);
assert.equal(captured.signatureVerified, true);
const resultItem = result[0][0].json;
assert.deepEqual(resultItem, {error:'SES request failed; inspect safe diagnostics', ses_diagnostics:{http_status:400,aws_error_code:${JSON.stringify(process.argv[3] || 'MessageRejected')},request_id:${JSON.stringify(id)}}});
assert(!JSON.stringify(result).includes('sensitive-placeholder-do-not-retain'));
console.log(JSON.stringify({unitCases:7,nodeOutput:resultItem,signatureVerified:captured.signatureVerified}));
`);
process.argv[2] = process.argv[2] === 'installed' ? 'installed' : 'versioned';
const mod = new Module('/audit/tests/notifications/offline-diagnostic-run.cjs', module);
mod.filename = '/audit/tests/notifications/offline-diagnostic-run.cjs';
mod._compile(source, mod.filename);
