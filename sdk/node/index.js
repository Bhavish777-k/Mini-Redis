'use strict';

const net = require('node:net');
const MAX_LINE = 1024 * 1024;

class FastKVError extends Error {}
class FastKVCommandError extends FastKVError {}
class FastKVConnectionError extends FastKVError {}
class FastKVProtocolError extends FastKVError {}

function token(value, field) {
  if (!(typeof value === 'string' || (typeof value === 'number' && Number.isSafeInteger(value)))) {
    throw new TypeError(`${field} must be a string or safe integer`);
  }
  const s = String(value);
  if (!s || /\s|\x00/u.test(s)) throw new TypeError(`${field} must be a nonempty token without whitespace or NUL`);
  return s;
}
function integer(value, op) {
  if (!/^-?\d+$/.test(value)) throw new FastKVProtocolError(`Invalid ${op} reply: ${JSON.stringify(value)}`);
  const n = Number(value);
  if (!Number.isSafeInteger(n)) throw new FastKVProtocolError(`${op} result outside JS safe integer range`);
  return n;
}

class FastKV {
  constructor({host = '127.0.0.1', port = 7001, timeout = 3000} = {}) {
    if (typeof host !== 'string' || !host) throw new TypeError('host must be nonempty');
    if (!Number.isSafeInteger(port) || port < 1 || port > 65535) throw new RangeError('port must be 1..65535');
    if (!Number.isSafeInteger(timeout) || timeout <= 0) throw new RangeError('timeout must be positive milliseconds');
    this.host = host;
    this.port = port;
    this.timeout = timeout;
  }

  command(command) {
    if (typeof command !== 'string' || !command || /[\r\n\x00]/u.test(command)) {
      throw new TypeError('command must be one nonempty line');
    }
    const payload = Buffer.from(command + '\n', 'utf8');
    if (payload.length > MAX_LINE) throw new RangeError('command exceeds 1 MiB router limit');

    return new Promise((resolve, reject) => {
      const socket = net.createConnection({host: this.host, port: this.port});
      const chunks = [];
      let total = 0;
      let settled = false;
      const finish = (err, reply) => {
        if (settled) return;
        settled = true;
        socket.destroy();
        if (err) reject(err); else resolve(reply);
      };
      socket.setTimeout(this.timeout);
      socket.on('connect', () => socket.write(payload));
      socket.on('timeout', () => finish(new FastKVConnectionError('Timed out: command outcome may be unknown')));
      socket.on('error', err => finish(new FastKVConnectionError(`Fast-KV connection failed: ${err.message}; write outcome may be unknown`)));
      socket.on('end', () => finish(new FastKVProtocolError('Router closed without newline reply')));
      socket.on('close', () => {
        if (!settled) finish(new FastKVProtocolError('Connection closed without complete reply'));
      });
      socket.on('data', data => {
        const end = data.indexOf(10);
        const part = end >= 0 ? data.subarray(0, end) : data;
        chunks.push(part);
        total += part.length;
        if (total > MAX_LINE) return finish(new FastKVProtocolError('Router reply exceeds 1 MiB'));
        if (end >= 0) {
          const bytes = Buffer.concat(chunks, total);
          // Buffer.toString normally substitutes the replacement character; reject invalid UTF-8 explicitly.
          const reply = new TextDecoder('utf-8', {fatal: true});
          let text;
          try { text = reply.decode(bytes); }
          catch { return finish(new FastKVProtocolError('Router response is not UTF-8')); }
          if (text === 'ERR' || text.startsWith('ERR ')) return finish(new FastKVCommandError(text));
          finish(null, text);
        }
      });
    });
  }

  async ping() {
    const r = await this.command('PING');
    if (r !== 'PONG') throw new FastKVProtocolError(`Expected PONG, got ${JSON.stringify(r)}`);
    return true;
  }
  async set(key, value, options = {}) {
    const k = token(key, 'key'), v = token(value, 'value');
    const {ttl} = options;
    if (ttl !== undefined && (!Number.isSafeInteger(ttl) || ttl < 0 || ttl > 3153600000)) {
      throw new RangeError('ttl must be an integer between 0 and 3153600000');
    }
    const r = await this.command(`SET ${k} ${v}`);
    if (r !== 'OK') throw new FastKVProtocolError(`Expected OK from SET, got ${JSON.stringify(r)}`);
    if (ttl !== undefined && !await this.expire(k, ttl)) {
      throw new FastKVProtocolError('SET succeeded but EXPIRE did not set the TTL');
    }
    return true;
  }
  async get(key) { const r = await this.command(`GET ${token(key, 'key')}`); return r === '(nil)' ? null : r; }
  async delete(key) { return this._bool('DEL', key); }
  async exists(key) { return this._bool('EXISTS', key); }
  async incr(key) { return integer(await this.command(`INCR ${token(key, 'key')}`), 'INCR'); }
  async expire(key, seconds) {
    if (!Number.isSafeInteger(seconds) || seconds < 0 || seconds > 3153600000) {
      throw new RangeError('seconds must be an integer between 0 and 3153600000');
    }
    return this._bool('EXPIRE', key, String(seconds));
  }
  async ttl(key) { return integer(await this.command(`TTL ${token(key, 'key')}`), 'TTL'); }
  async persist(key) { return this._bool('PERSIST', key); }
  async where(key) {
    const r = await this.command(`WHERE ${token(key, 'key')}`);
    return r === '(nil)' ? null : integer(r, 'WHERE');
  }
  async count() { return integer(await this.command('COUNT'), 'COUNT'); }
  async clusterStatus() { return this.command('CLUSTER STATUS'); }
  async osStats() { return this.command('OSSTATS'); }
  async allocStats() { return this.command('ALLOCSTATS'); }
  async _bool(op, key, arg) {
    const r = await this.command(`${op} ${token(key, 'key')}${arg === undefined ? '' : ' ' + arg}`);
    if (r !== '0' && r !== '1') throw new FastKVProtocolError(`Expected 0/1 from ${op}, got ${JSON.stringify(r)}`);
    return r === '1';
  }
}

module.exports = {FastKV, FastKVError, FastKVCommandError, FastKVConnectionError, FastKVProtocolError};
