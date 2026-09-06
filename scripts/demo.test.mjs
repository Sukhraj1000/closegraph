import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,writeFileSync,chmodSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {spawnSync} from 'node:child_process';
test('judges receive four per-install accounts, and a public credential file is rejected',()=>{
 const folder=mkdtempSync(join(tmpdir(),'closegraph-accounts-'));const path=join(folder,'.env');
 try{
  const names=['accountant','account_manager','fund_manager','investor'];
  writeFileSync(path,names.map(name=>'CLOSEGRAPH_'+name.toUpperCase()+'_PASSWORD='+JSON.stringify(name+'-test-only')).join('\n'),{mode:0o600});
  const good=spawnSync(process.execPath,['scripts/demo.mjs','--accounts',path],{encoding:'utf8'});assert.equal(good.status,0,good.stderr);
  for(const name of names)assert.ok(good.stdout.includes('username: '+name+' | password: '+name+'-test-only'));
  chmodSync(path,0o644);const bad=spawnSync(process.execPath,['scripts/demo.mjs','--accounts',path],{encoding:'utf8'});assert.notEqual(bad.status,0);assert.ok(!bad.stdout.includes('test-only'));
 }finally{rmSync(folder,{recursive:true,force:true});}
});
