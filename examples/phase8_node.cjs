const {FastKV} = require('../sdk/node');

(async () => {
  const kv = new FastKV({port: 7001});
  await kv.ping();
  await kv.set('demo:node', 'hello');
  console.log('GET:', await kv.get('demo:node'));
  await kv.expire('demo:node', 120);
  console.log('TTL:', await kv.ttl('demo:node'));
  console.log('Cluster:', await kv.clusterStatus());
})().catch(e => { console.error(e.message); process.exitCode = 1; });
