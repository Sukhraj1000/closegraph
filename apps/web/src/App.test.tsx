import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import App from './App';
import { initialScenario, snapshot } from './lib/synthetic';

describe('session transitions', () => {
 it('ignores a previous session response after a different account signs in', async () => {
  const user=userEvent.setup();
  const first={...snapshot(initialScenario('ready')),pack_id:'first-pack',title:'First fund private pack',fund_id:'First fund'};
  const second={...snapshot(initialScenario('ready')),pack_id:'second-pack',title:'Second fund scoped pack',fund_id:'Second fund'};
  const principal=(actor_id:string,csrf_token:string,pack_id:string)=>({actor:{actor_id,role:'PREPARER'},csrf_token,scopes:[{tenant_id:'test',fund_id:pack_id,pack_id}]});
  let lists=0,resolveOld!:(response:Response)=>void;
  const oldResponse=new Promise<Response>(resolve=>{resolveOld=resolve;});
  const json=(body:unknown)=>new Response(JSON.stringify(body),{status:200});
  vi.spyOn(globalThis,'fetch').mockImplementation(async(input,options)=>{
   const url=String(input);
   if(url==='/api/session')return json(principal('first-person','first-session','first-pack'));
   if(url==='/api/session/logout')return new Response(null,{status:204});
   if(url==='/api/session/login')return json(principal('second-person','second-session','second-pack'));
   if(url==='/api/packs'){lists++;return lists===1?json([first]):lists===2?oldResponse:json([second]);}
   if(url==='/api/packs/first-pack')return json(first);
   if(url==='/api/packs/second-pack')return json(second);
   throw new Error('Unexpected request '+url+' '+options?.method);
  });
  window.history.replaceState(null,'','#reports');
  render(<App/>);
  await screen.findByRole('heading',{name:'First fund private pack'});
  await user.click(screen.getByRole('button',{name:'Refresh current version'}));
  await waitFor(()=>expect(lists).toBe(2));
  await user.click(screen.getByRole('button',{name:'Sign out'}));
  await screen.findByRole('heading',{name:'Sign in to CloseGraph'});
  await user.type(screen.getByRole('textbox',{name:'Username'}),'second-person');
  await user.type(screen.getByLabelText('Password',{exact:true}),'test-password-not-a-secret');
  await user.click(screen.getByRole('button',{name:'Sign in'}));
  await screen.findByRole('heading',{name:'Second fund scoped pack'});
  await act(async()=>{resolveOld(json([first]));await oldResponse;});
  expect(screen.queryByText('First fund private pack')).not.toBeInTheDocument();
  expect(screen.getByRole('heading',{name:'Second fund scoped pack'})).toBeVisible();
 });
});
