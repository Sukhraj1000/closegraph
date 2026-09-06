import {BatmanPet} from './components/closegraph/Batman';
import { useEffect, useId, useRef, useState } from 'react';
import { Alert, Button, Card, Input } from './components/ui';
import { Field } from './components/closegraph/Field';
import { ClosegraphApi } from './lib/api';
import type { Session } from './lib/model';
import { FundReviewWorkspace } from './features/fund-review/Workspace';
const api = new ClosegraphApi();
function Login({onLogin}:{onLogin:(session:Session)=>void}) {
 const id=useId(),[username,setUsername]=useState(''),[password,setPassword]=useState(''),[error,setError]=useState(''),[pending,setPending]=useState(false),ref=useRef<HTMLInputElement>(null);
 async function submit(e:React.FormEvent){e.preventDefault();if(!username||!password){setError('Enter your username and password.');ref.current?.focus();return;}setPending(true);setError('');try{onLogin(await api.login(username,password));}catch(error){setError((error as Error).message);}finally{setPending(false);}}
 return <main className="login"><Card><div className="brand"><span className="brand-mark" aria-hidden/>CloseGraph</div><h1>Sign in to CloseGraph</h1><p className="muted">Review your fund reporting pack, trace questions to source evidence and see what changed.</p>{error&&<div role="alert"><Alert title="Sign-in failed" tone="danger">{error}</Alert></div>}<form onSubmit={submit} noValidate><Field id={id+'-username'} label="Username"><Input id={id+'-username'} ref={ref} autoComplete="username" value={username} onChange={e=>setUsername(e.target.value)} required disabled={pending}/></Field><Field id={id+'-password'} label="Password"><Input id={id+'-password'} type="password" autoComplete="current-password" value={password} onChange={e=>setPassword(e.target.value)} required disabled={pending}/></Field><Button type="submit" disabled={pending}>{pending?'Signing in…':'Sign in'}</Button></form></Card></main>;
}
function WorkspaceApp(){
 const [session,setSession]=useState<Session|null>(null),[checking,setChecking]=useState(true),[notice,setNotice]=useState('');
 useEffect(()=>{api.session().then(setSession).catch(()=>{}).finally(()=>setChecking(false));},[]);
 async function refreshIdentity(){try{const fresh=await api.session();setSession(fresh);setNotice('Your session or permissions were refreshed. Review the current result before retrying your action.');}catch{setSession(null);}}
 if(checking)return <main className="login"><p role="status">Opening your workspace…</p></main>;
 if(!session)return <Login onLogin={s=>{setSession(s);setNotice('');}}/>;
 return <FundReviewWorkspace key={session.csrf_token} session={session} notice={notice} onSessionChange={()=>void refreshIdentity()} onLogout={()=>void api.logout().then(()=>setSession(null)).catch(()=>refreshIdentity())}/>;
}

export default function App(){return <><WorkspaceApp/><BatmanPet/></>;}
