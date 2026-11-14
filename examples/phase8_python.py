"""Run after installing SDK and starting cluster. No external dependencies."""
from fastkv import FastKV

kv = FastKV(port=7001)
assert kv.ping()
kv.set('demo:user', 'awnish')
print('GET:', kv.get('demo:user'))
kv.set('demo:session', 'active', ttl=120)
print('TTL:', kv.ttl('demo:session'))
print('Cluster:', kv.cluster_status())
