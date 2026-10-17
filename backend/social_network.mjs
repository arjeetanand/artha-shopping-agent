import dns from 'node:dns/promises';
import { BlockList, isIP } from 'node:net';

const blockedAddresses = { ipv4: new BlockList(), ipv6: new BlockList() };
for (const [subnet, prefix] of [
  ['0.0.0.0', 8], ['10.0.0.0', 8], ['100.64.0.0', 10], ['127.0.0.0', 8],
  ['169.254.0.0', 16], ['172.16.0.0', 12], ['192.0.0.0', 24], ['192.0.2.0', 24],
  ['192.88.99.0', 24], ['192.168.0.0', 16], ['198.18.0.0', 15], ['198.51.100.0', 24],
  ['203.0.113.0', 24], ['224.0.0.0', 4], ['240.0.0.0', 4],
]) blockedAddresses.ipv4.addSubnet(subnet, prefix, 'ipv4');
for (const [subnet, prefix] of [
  ['::', 96], ['64:ff9b::', 96], ['64:ff9b:1::', 48], ['100::', 64],
  ['2001::', 23], ['2001:db8::', 32], ['2002::', 16], ['3fff::', 20],
  ['fc00::', 7], ['fe80::', 10], ['ff00::', 8],
]) blockedAddresses.ipv6.addSubnet(subnet, prefix, 'ipv6');

export async function isPublicHttpUrl(value) {
  let target;
  try {
    target = new URL(value);
  } catch {
    return false;
  }
  if (!['http:', 'https:'].includes(target.protocol) || target.username || target.password) return false;
  if (target.port && target.port !== (target.protocol === 'https:' ? '443' : '80')) return false;
  const host = target.hostname.replace(/^\[|\]$/g, '').toLowerCase().replace(/\.$/, '');
  if (!host || ['localhost', 'localhost.localdomain'].includes(host) || /\.(localhost|local|localdomain|internal)$/.test(host)) return false;
  let addresses;
  try {
    const family = isIP(host);
    addresses = family ? [{ address: host, family }] : await dns.lookup(host, { all: true, verbatim: true });
  } catch {
    return false;
  }
  return addresses.length > 0 && addresses.every(({ address, family }) => {
    if (family === 6 && address.toLowerCase().startsWith('::ffff:')) return false;
    return !blockedAddresses[family === 6 ? 'ipv6' : 'ipv4'].check(address, family === 6 ? 'ipv6' : 'ipv4');
  });
}
