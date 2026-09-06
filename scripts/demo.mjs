// Local judge launcher. Passwords are generated per installation, never checked in.
import {spawnSync} from 'node:child_process';
import {readFileSync,lstatSync} from 'node:fs';
import {resolve,dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
const root=resolve(dirname(fileURLToPath(import.meta.url)),'..');
if(process.argv.includes('--accounts')){
 const args=process.argv.slice(2).filter(x=>x!=='--accounts');
 const path=resolve(args[0]??resolve(root,'.local/dev-runtime/.env'));
 const info=lstatSync(path);
 if(!info.isFile()||info.isSymbolicLink()||(info.mode&0o077)||(process.getuid&&info.uid!==process.getuid()))throw Error('Account file must belong to you and have private permissions (chmod 600).');
 const values=Object.fromEntries(readFileSync(path,'utf8').split('\n').filter(line=>line.trim()&&!line.trim().startsWith('#')).map(line=>{const split=line.indexOf('=');return [line.slice(0,split),JSON.parse(line.slice(split+1))];}));
 for(const [name,label] of [['accountant','Accountant'],['account_manager','Account manager'],['fund_manager','Fund manager'],['investor','Investor']]){
  const password=values['CLOSEGRAPH_'+name.toUpperCase()+'_PASSWORD'];
  if(typeof password!=='string'||!password)throw Error('Run npm run demo first to create all four local accounts.');
  console.log(label+' | username: '+name+' | password: '+password);
 }
}else{
 if(process.platform!=='darwin')throw Error('This local demo requires macOS because its process isolation uses Seatbelt.');
 for(const [command,args] of [['uv',['sync','--locked','--project','apps/api']],['npm',['ci','--prefix','apps/web']],['uv',['run','--locked','--project','apps/api','python','scripts/local_runtime.py','init']],['uv',['run','--locked','--project','apps/api','python','scripts/local_runtime.py','up']]]){
  const result=spawnSync(command,args,{cwd:root,stdio:'inherit',shell:false});
  if(result.error)throw result.error;
  if(result.status!==0)process.exit(result.status??1);
 }
 console.log('Open http://127.0.0.1:24173. Run npm run demo:accounts to view your four local sign-ins.');
}
