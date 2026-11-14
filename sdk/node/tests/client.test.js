'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const net = require('node:net');
const {once} = require('node:events');
const {FastKV, FastKVCommandError, FastKVConnectionError} = require('../index');

async function mockServer() {
  const commands = [];
  const store = new Map();
  const expires = new Map();
  let defaultTTL = null;
  const server = net.createServer(sock => {
    let data = '';
    sock.on('data', chunk => {
      data += chunk.toString();
      if (!data.includes('\n')) return;
      const line = data.substring(0, data.indexOf('\n'));
      commands.push(line);
      const [op, k, v] = line.split(' ');
      let out = 'ERR unknown';
      if (op === 'PING') out = 'PONG';
      if (op === 'TTLDEFAULT') { if (k === 'GET') out = defaultTTL === null ? 'never' : String(defaultTTL); else {defaultTTL = v === 'never' ? null : Number(v); out = 'OK';} }
      if (op === 'SET') {
        const prior = expires.get(k);
        store.set(k, v);
        const bits = line.split(' ');
        if (bits[3] === 'EX') expires.set(k, Number(bits[4]));
        else if (bits[3] === 'PERSIST') expires.delete(k);
        else if (bits[3] === 'KEEPTTL' && prior !== undefined) expires.set(k, prior);
        else if (defaultTTL !== null) expires.set(k, defaultTTL);
        else expires.delete(k);
        out = 'OK';
      }
      if (op === 'GET') out = store.get(k) ?? '(nil)';
      if (op === 'DEL') out = String(Number(store.delete(k)));
      if (op === 'EXISTS') out = String(Number(store.has(k)));
      if (op === 'INCR') { out = String(Number(store.get(k) ?? 0) + 1); store.set(k, out); }
      if (op === 'EXPIRE') { out = String(Number(store.has(k))); if (out === '1') expires.set(k, Number(v)); }
      if (op === 'PERSIST') out = String(Number(expires.delete(k)));
      if (op === 'TTL') out = String(!store.has(k) ? -2 : (expires.get(k) ?? -1));
      if (op === 'WHERE') out = store.has(k) ? '6381' : '(nil)';
      if (op === 'COUNT') out = String(store.size);
      if (line === 'CLUSTER STATUS') out = 'nodes=1 max_nodes=3';
      if (op === 'OSSTATS') out = 'node=6381';
      if (op === 'ALLOCSTATS') out = 'node=6381';
      const reply = Buffer.from(out + '\n');
      sock.write(reply.subarray(0, 1));
      sock.end(reply.subarray(1));
    });
  });
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  return {server, port: server.address().port, commands};
}

test('typed commands, TTL and error handling', async (t) => {
  const {server, port, commands} = await mockServer();
  t.after(() => server.close());
  const db = new FastKV({port});
  assert.equal(await db.ping(), true);
  assert.equal(await db.get('missing'), null);
  assert.equal(await db.where('missing'), null);
  assert.equal(await db.set('session', 'active', {ttl: 15}), true);
  assert.equal(await db.get('session'), 'active');
  assert.equal(await db.ttl('session'), 15);
  assert.equal(await db.where('session'), 6381);
  assert.equal(await db.exists('session'), true);
  assert.equal(await db.persist('session'), true);
  assert.equal(await db.ttl('session'), -1);
  assert.equal(await db.set('counter', 2), true);
  assert.equal(await db.incr('counter'), 3);
  assert.equal(await db.count(), 2);
  assert.match(await db.clusterStatus(), /nodes=1/);
  assert.match(await db.osStats(), /node=6381/);
  assert.match(await db.allocStats(), /node=6381/);
  assert.equal(await db.delete('session'), true);
  assert.equal(await db.delete('session'), false);
  assert.equal(await db.expire('session', 5), false);
  assert(commands.includes('SET session active EX 15'));
  assert.equal(await db.setDefaultTTL(300), true);
  assert.equal(await db.getDefaultTTL(), 300);
  assert.equal(await db.set('defaultKey', 'v'), true);
  assert.equal(await db.ttl('defaultKey'), 300);
  assert.equal(await db.set('perm', 'v', {persist: true}), true);
  assert.equal(await db.ttl('perm'), -1);
  await assert.rejects(db.command('UNKNOWN'), FastKVCommandError);
  await assert.rejects(db.get('bad\nkey'), TypeError);
  await assert.rejects(db.set('key', 'two words'), TypeError);
  assert.throws(() => db.command('PING\nSET other value'), TypeError);
  await assert.rejects(db.expire('key', -1), RangeError);
});

test('connection errors are surfaced', async () => {
  const server = net.createServer();
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  const port = server.address().port;
  await new Promise(resolve => server.close(resolve));
  const db = new FastKV({port, timeout: 250});
  await assert.rejects(db.ping(), FastKVConnectionError);
});
