// Execute only in a network-disabled n8nio/n8n:2.43.5 container.
// Synthetic credentials and addresses. The transport is replaced before any I/O.
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');

const pnpm = '/usr/local/lib/node_modules/n8n/node_modules/.pnpm';
const packageDir = fs.readdirSync(pnpm).find(x => x.startsWith('n8n-nodes-base@'));
assert(packageDir, 'n8n nodes-base is unavailable');
const base = path.join(pnpm, packageDir, 'node_modules/n8n-nodes-base/dist');
const nodeFile = path.join(base, 'nodes/Aws/SES/AwsSes.node.js');
const credentialsFile = path.join(base, 'credentials/Aws.credentials.js');
const source = fs.readFileSync(nodeFile, 'utf8');
assert.equal(crypto.createHash('sha256').update(source).digest('hex'),
  '51febf78584d8a6414794ff61679e8ef3570d813fd233ade58a2134c2649a835',
  'installed SES node differs from audited n8n 2.43.5 build');
const expected = "'/?Action=SendEmail&' + params.join('&')";
assert.equal(source.split(expected).length - 1, 1, 'unexpected installed SES node implementation');
const mode = process.argv[2] || 'original';
assert(['original', 'versioned'].includes(mode));
let AwsSes;
if (mode === 'versioned') {
  const patch = fs.readFileSync('/audit/patches/n8n-2.43.5-aws-ses-version.patch', 'utf8');
  const oldLine = patch.split('\n').find(line => line.startsWith('-                        responseData'))?.slice(1);
  const newLine = patch.split('\n').find(line => line.startsWith('+                        responseData'))?.slice(1);
  assert(oldLine && newLine && source.includes(oldLine), 'version patch does not match installed node');
  const patched = source.replace(oldLine, newLine);
  const mod = new Module(nodeFile, module);
  mod.filename = nodeFile;
  mod.paths = Module._nodeModulePaths(path.dirname(nodeFile));
  mod._compile(patched, nodeFile);
  AwsSes = mod.exports.AwsSes;
} else {
  AwsSes = require(nodeFile).AwsSes;
}
const Aws = require(credentialsFile).Aws;
const workflow = JSON.parse(fs.readFileSync('/audit/workflows/notifications.json', 'utf8'));
const ses = workflow.nodes.find(n => n.name === 'AWS SES Send to Controlled Test Inbox');
assert(ses, 'SES node missing from checked-in workflow');

const data = {
  sender: 'controlled@example.test',
  recipient: 'controlled@example.test',
  subject: 'Synthetic subject',
  html: '<p>Synthetic body</p>',
};
function resolve(value) {
  if (Array.isArray(value)) return value.map(resolve);
  if (typeof value !== 'string' || !value.startsWith('={{')) return value;
  const expr = value.slice(3, -2).trim().replaceAll('$json.', 'data.');
  return Function('data', `return (${expr})`)(data);
}
const credentials = {
  accessKeyId: 'AKIDEXAMPLE',
  secretAccessKey: 'synthetic-secret-for-offline-signing-only',
  region: 'eu-north-1',
};
let captured;
const context = {
  getInputData: () => [{json: data}],
  getNodeParameter: name => resolve(ses.parameters[name] ?? ({authentication:'iam', resource:'email', operation:'send'}[name])),
  getCredentials: async () => credentials,
  getNode: () => ({name: ses.name, type: ses.type, typeVersion: ses.typeVersion}),
  continueOnFail: () => false,
  logger: {warn: () => {}},
  helpers: {
    returnJsonArray: value => [{json: value}],
    constructExecutionMetaData: value => value,
    requestWithAuthentication: async (type, options) => {
      assert.equal(type, 'aws');
      const signed = await new Aws().authenticate(credentials, options);
      const parsed = new URL(signed.url);
      const params = Object.fromEntries(parsed.searchParams.entries());
      captured = {
        method: signed.method,
        host: parsed.host,
        path: parsed.pathname,
        rawQuery: parsed.search.slice(1),
        contentType: signed.headers?.['Content-Type'] ?? signed.headers?.['content-type'] ?? null,
        body: signed.body ?? null,
        params,
        recipientCount: [...parsed.searchParams.keys()].filter(k => k.startsWith('Destination.ToAddresses.member.')).length,
        signatureV4: /^AWS4-HMAC-SHA256 /.test(signed.headers?.authorization ?? signed.headers?.Authorization ?? ''),
        authorizationScope: (signed.headers?.authorization ?? signed.headers?.Authorization ?? '').match(/Credential=[^/]+\/([^,]+)/)?.[1] ?? null,
      };
      // No HTTP request is made. The returned XML is purely synthetic.
      return '<SendEmailResponse><SendEmailResult><MessageId>synthetic-only</MessageId></SendEmailResult></SendEmailResponse>';
    },
  },
};
new AwsSes().execute.call(context).then(() => {
  assert(captured, 'request was not captured');
  console.log(JSON.stringify(captured));
}).catch(error => { console.error(error.message); process.exitCode = 1; });
