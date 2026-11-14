const {FastKV} = require('..');

async function main() {
  const db = new FastKV({port: 7001});
  await db.ping();
  await db.set('example:key', 'hello');
  console.log('value:', await db.get('example:key'));
  await db.expire('example:key', 90);
  console.log('ttl:', await db.ttl('example:key'));
  console.log('where:', await db.where('example:key'));
}
main().catch(err => { console.error(err.message); process.exitCode = 1; });
