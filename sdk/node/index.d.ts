export class FastKVError extends Error {}
export class FastKVCommandError extends FastKVError {}
export class FastKVConnectionError extends FastKVError {}
export class FastKVProtocolError extends FastKVError {}
export interface FastKVOptions { host?: string; port?: number; timeout?: number; }
export class FastKV {
  constructor(options?: FastKVOptions);
  readonly host: string;
  readonly port: number;
  readonly timeout: number;
  command(command: string): Promise<string>;
  ping(): Promise<boolean>;
  set(key: string | number, value: string | number, options?: {ttl?: number}): Promise<boolean>;
  get(key: string | number): Promise<string | null>;
  delete(key: string | number): Promise<boolean>;
  exists(key: string | number): Promise<boolean>;
  incr(key: string | number): Promise<number>;
  expire(key: string | number, seconds: number): Promise<boolean>;
  ttl(key: string | number): Promise<number>;
  persist(key: string | number): Promise<boolean>;
  where(key: string | number): Promise<number | null>;
  count(): Promise<number>;
  clusterStatus(): Promise<string>;
  osStats(): Promise<string>;
  allocStats(): Promise<string>;
}
