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
const mode = process.argv[2] || 'original';
assert(['original', 'versioned', 'installed'].includes(mode));
const patcher = require('/audit/patches/apply-n8n-ses-patch.cjs');
let AwsSes;
if (mode === 'versioned') {
  const transformed = patcher.transform(path.dirname(base));
  // Compile the patched helper first so the node loads that exact helper.
  for (const file of [path.join(base, 'nodes/Aws/SES/GenericFunctions.js'), nodeFile]) {
    const mod = new Module(file, module);
    mod.filename = file;
    mod.paths = Module._nodeModulePaths(path.dirname(file));
    require.cache[file] = mod;
    mod._compile(transformed[file], file);
  }
  AwsSes = require.cache[nodeFile].exports.AwsSes;
} else {
  if (mode === 'original') patcher.transform(path.dirname(base)); // verify original hashes
  AwsSes = require(nodeFile).AwsSes;
}
const Aws = require(credentialsFile).Aws;
const workflow = JSON.parse(fs.readFileSync('/audit/workflows/notifications.json', 'utf8'));
const ses = workflow.nodes.find(n => n.name === 'AWS SES Send to Controlled Test Inbox');
assert(ses, 'SES node missing from checked-in workflow');

const data = {
  sender: 'controlled@example.test',
  recipient: 'controlled@example.test',
  subject: "Synthetic subject & + café !*'()",
  html: '<p>Synthetic body & + café</p>',
};
const {Expression} = Module.createRequire(nodeFile)('n8n-workflow');
function resolve(value) {
  if (Array.isArray(value)) return value.map(resolve);
  if (typeof value !== 'string' || !value.startsWith('={{')) return value;
  return new Expression('UTC').resolveSimpleParameterValue(value, {$json: data}, false);
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
      const form = new URLSearchParams(signed.body ?? parsed.search);
      const params = Object.fromEntries(form.entries());
      const headers = Object.fromEntries(Object.entries(signed.headers).map(([k,v]) => [k.toLowerCase(), String(v)]));
      const authorization = headers.authorization;
      const scope = authorization.match(/Credential=[^/]+\/([^,]+)/)[1];
      const signedHeaders = authorization.match(/SignedHeaders=([^,]+)/)[1];
      const signature = authorization.match(/Signature=(.+)$/)[1];
      const hash = value => crypto.createHash('sha256').update(value).digest('hex');
      const hmac = (key, value) => crypto.createHmac('sha256', key).update(value).digest();
      const encode = value => encodeURIComponent(value).replace(/[!'()*]/g, c => '%' + c.charCodeAt(0).toString(16).toUpperCase());
      function verify(body, candidateHeaders) {
        const canonicalHeaders = signedHeaders.split(';').map(k => k + ':' + candidateHeaders[k].trim().replace(/\s+/g, ' ') + '\n').join('');
        const query = [...parsed.searchParams].map(([k,v]) => [encode(k), encode(v)]).sort((a,b) => a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : a[1].localeCompare(b[1])).map(([k,v]) => k + '=' + v).join('&');
        const canonical = [signed.method, parsed.pathname, query, canonicalHeaders, signedHeaders, hash(body ?? '')].join('\n');
        const toSign = ['AWS4-HMAC-SHA256', headers['x-amz-date'], scope, hash(canonical)].join('\n');
        const [date, region, service] = scope.split('/');
        const key = hmac(hmac(hmac(hmac('AWS4' + credentials.secretAccessKey, date), region), service), 'aws4_request');
        return crypto.createHmac('sha256', key).update(toSign).digest('hex') === signature;
      }
      captured = {
        method: signed.method,
        host: parsed.host,
        path: parsed.pathname,
        rawQuery: parsed.search.slice(1),
        contentType: signed.headers?.['Content-Type'] ?? signed.headers?.['content-type'] ?? null,
        body: signed.body ?? null,
        contentLength: headers['content-length'] ?? null,
        signedHeaders: signedHeaders.split(';'),
        signatureVerified: verify(signed.body, headers),
        bodyTamperRejected: !verify((signed.body ?? '') + 'tampered', headers),
        contentTypeTamperRejected: headers['content-type'] ? !verify(signed.body, {...headers, 'content-type': 'application/json'}) : null,
        params,
        recipientCount: [...form.keys()].filter(k => k.startsWith('Destination.ToAddresses.member.')).length,
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
