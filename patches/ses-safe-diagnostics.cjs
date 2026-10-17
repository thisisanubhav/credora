'use strict';
// Intentionally excludes provider text, request options, headers and payloads.
function sesSafeDiagnostics(error) {
  const codes = new Set([
    'MessageRejected', 'InvalidParameterValue', 'InvalidParameterCombination',
    'MissingParameter', 'InvalidAction', 'InvalidClientTokenId', 'SignatureDoesNotMatch',
    'AccessDenied', 'AccessDeniedException', 'IncompleteSignature', 'RequestExpired',
    'Throttling', 'ThrottlingException', 'ServiceUnavailable', 'InternalFailure',
    'MailFromDomainNotVerifiedException', 'ConfigurationSetDoesNotExistException',
    'ConfigurationSetSendingPausedException', 'AccountSendingPausedException',
    'InvalidConfigurationSet', 'ValidationError',
  ]);
  const output = {http_status: null, aws_error_code: null, request_id: null};
  const queue = [error];
  const seen = new Set();
  const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  const takeCode = value => {
    if (typeof value === 'string' && codes.has(value) && !output.aws_error_code) output.aws_error_code = value;
  };
  const takeId = value => {
    if (typeof value === 'string' && uuid.test(value) && !output.request_id) output.request_id = value;
  };
  for (let index = 0; index < queue.length && index < 32; index++) {
    const item = queue[index];
    if (typeof item === 'string') {
      // Bounded extraction, not XML entity expansion. Never retain Message text.
      if (item.length > 65536) continue;
      takeCode(item.match(/<(?:\w+:)?Code>\s*([A-Za-z]+)\s*<\/(?:\w+:)?Code>/)?.[1]);
      takeId(item.match(/<(?:\w+:)?RequestId>\s*([0-9a-f-]+)\s*<\/(?:\w+:)?RequestId>/i)?.[1]);
      continue;
    }
    if (!item || typeof item !== 'object' || seen.has(item)) continue;
    seen.add(item);
    for (const key of ['httpCode', 'statusCode', 'status']) {
      const value = item[key];
      if ((typeof value === 'number' || typeof value === 'string') && /^[45]\d\d$/.test(String(value)) && output.http_status === null) output.http_status = Number(value);
    }
    takeCode(item.Code); takeCode(item.code);
    takeId(item.RequestId); takeId(item.requestId);
    // Only allowlisted response header names, never request/authorization headers.
    if (item.headers && typeof item.headers === 'object') {
      for (const key of ['x-amzn-requestid', 'x-amzn-request-id', 'x-amz-request-id']) takeId(item.headers[key]);
    }
    for (const key of ['cause', 'errorResponse', 'error', 'Error', 'ErrorResponse', 'response', 'data', 'body']) {
      if (item[key] !== undefined && queue.length < 32) queue.push(item[key]);
    }
  }
  return output;
}
module.exports = {sesSafeDiagnostics};
