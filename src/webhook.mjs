import https from 'node:https';
import dns from 'node:dns/promises';
import { BlockList, isIPv4 } from 'node:net';
import { createHmac } from 'node:crypto';

const blocked = new BlockList();
for (const [address, prefix] of [
  ['0.0.0.0', 8], ['10.0.0.0', 8], ['100.64.0.0', 10], ['127.0.0.0', 8],
  ['169.254.0.0', 16], ['172.16.0.0', 12], ['192.0.0.0', 24], ['192.0.2.0', 24],
  ['192.168.0.0', 16], ['198.18.0.0', 15], ['198.51.100.0', 24],
  ['203.0.113.0', 24], ['224.0.0.0', 3]
]) blocked.addSubnet(address, prefix);

export function publicIPv4(address) { return isIPv4(address) && !blocked.check(address); }
const fakeIP = new BlockList();
fakeIP.addSubnet('198.18.0.0', 15);
export async function resolvePublicIPv4(host, { lookup = dns.lookup, fetchDNS = fetch } = {}) {
  let addresses = await lookup(host, { all: true, family: 4 });
  // Some local TUN proxies synthesize benchmark-range addresses. Resolve the
  // public hostname through authenticated HTTPS instead of allowing that range.
  if (addresses.length && !isIPv4(host) && addresses.every(x => isIPv4(x.address) && fakeIP.check(x.address))) {
    const response = await fetchDNS('https://cloudflare-dns.com/dns-query?name=' + encodeURIComponent(host) + '&type=A', {
      headers: { accept: 'application/dns-json' }, redirect: 'error', signal: AbortSignal.timeout(10000)
    });
    if (!response.ok) throw new Error('dns_lookup_failed');
    const result = await response.json();
    if (result.Status !== 0) throw new Error('dns_lookup_failed');
    addresses = (result.Answer ?? []).filter(x => x.type === 1).map(x => ({ address: x.data, family: 4 }));
  }
  if (!addresses.length || addresses.some(x => !publicIPv4(x.address))) throw new Error('non_public_callback');
  return addresses[0].address;
}
export function secretKey(secret) {
  if (typeof secret !== 'string' || !/^whsec_[A-Za-z0-9+/]+={0,2}$/.test(secret)) throw new Error('invalid_signing_secret');
  const key = Buffer.from(secret.slice(6), 'base64');
  if (key.length < 24 || key.length > 64 || key.toString('base64').replace(/=+$/, '') !== secret.slice(6).replace(/=+$/, '')) throw new Error('invalid_signing_secret');
  return key;
}
export function signedHeaders(secret, id, body, subscriptionId, seconds = Math.floor(Date.now() / 1000)) {
  const signature = createHmac('sha256', secretKey(secret)).update(`${id}.${seconds}.${body}`).digest('base64');
  return {
    'Content-Type': 'application/json', 'webhook-id': id,
    'webhook-timestamp': String(seconds), 'webhook-signature': `v1,${signature}`,
    'X-MCP-Subscription-Id': subscriptionId
  };
}
export function callbackURL(raw) {
  const url = new URL(raw);
  if (url.protocol !== 'https:' || url.username || url.password || url.hash || (url.port && url.port !== '443')) throw new Error('callback_requires_https_443');
  return url;
}

// Resolve once per attempt and pin the validated IPv4 address; TLS still checks the hostname.
// IPv6-only callbacks are not supported by this small proof of concept.
export async function postWebhook(raw, body, headers) {
  const url = callbackURL(raw);
  if (Buffer.byteLength(body) > 262144) throw new Error('payload_too_large');
  const address = await resolvePublicIPv4(url.hostname);
  return new Promise((resolve, reject) => {
    const req = https.request(url, {
      method: 'POST', headers, agent: false, family: 4,
      lookup: (_host, options, cb) => options.all ? cb(null, [{ address, family: 4 }]) : cb(null, address, 4)
    }, res => {
      const chunks = []; let size = 0;
      res.on('data', chunk => {
        size += chunk.length;
        if (size > 262144) res.destroy(new Error('response_too_large'));
        else chunks.push(chunk);
      });
      res.on('error', reject);
      res.on('end', () => resolve({ status: res.statusCode, body: Buffer.concat(chunks).toString('utf8') }));
    });
    const timer = setTimeout(() => req.destroy(new Error('callback_timeout')), 10000);
    req.on('close', () => clearTimeout(timer));
    req.on('error', reject);
    req.end(body);
  });
}
