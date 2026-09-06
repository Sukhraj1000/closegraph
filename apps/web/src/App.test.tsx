import {act,render,screen,waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {describe,expect,it,vi} from 'vitest';
import App from './App';
const json=(body:unknown)=>new Response(JSON.stringify(body),{status:200});
const principal=(id:string)=>({actor:{actor_id:id,role:'PREPARER'},csrf_token:id,collection_funds:[{tenant_id:'test',fund_id:'fund'}]});
const work=(title:string)=>({id:title,title,sources:[],datasets:[],tasks:[],version:1,status:'EMPTY'});
describe('fund review entry and identity',()=>{
 it('shows the upload journey without technical workspace navigation',async()=>{
  vi.spyOn(globalThis,'fetch').mockImplementation(async input=>String(input)==='/api/session'?json(principal('one')):json([]));
  render(<App/>);await screen.findByRole('heading',{name:/Know what is ready/});
  expect(screen.getByLabelText('Reporting pack and supporting documents')).toBeVisible();
  expect(screen.queryByRole('button',{name:'Reports'})).not.toBeInTheDocument();expect(screen.queryByRole('button',{name:'Collections'})).not.toBeInTheDocument();
  expect(screen.getByRole('button',{name:'Prepare review brief'})).toBeDisabled();
 });
 it('does not display delayed private work after changing accounts',async()=>{
  const user=userEvent.setup();let identity='one',calls=0,resolveOld!:(r:Response)=>void;const old=new Promise<Response>(r=>{resolveOld=r;});
  vi.spyOn(globalThis,'fetch').mockImplementation(async input=>{const url=String(input);if(url==='/api/session')return json(principal(identity));if(url==='/api/session/logout')return new Response(null,{status:204});if(url==='/api/session/login'){identity='two';return json(principal(identity));}if(url==='/api/collections'){calls++;return calls===1?old:json([work('Second account work')]);}throw Error(url);});
  render(<App/>);await screen.findByRole('heading',{name:/Know what is ready/});await user.click(screen.getByRole('button',{name:'Sign out'}));await screen.findByRole('heading',{name:'Sign in to CloseGraph'});
  await user.type(screen.getByLabelText('Username'),'two');await user.type(screen.getByLabelText('Password'),'test-password');await user.click(screen.getByRole('button',{name:'Sign in'}));await screen.findByRole('heading',{name:/Know what is ready/});await user.click(screen.getByRole('button',{name:'Recent work'}));await screen.findByText('Second account work');
  await act(async()=>{resolveOld(json([work('First private work')]));await old;});expect(screen.queryByText('First private work')).not.toBeInTheDocument();
 });
 it('refreshes identity after a forbidden mutation and does not replay it',async()=>{
  const user=userEvent.setup();let sessions=0,creates=0;
  vi.spyOn(globalThis,'fetch').mockImplementation(async(input,options)=>{const url=String(input);if(url==='/api/session'){sessions++;return json(principal(sessions===1?'one':'two'));}if(url==='/api/collections'&&options?.method==='POST'){creates++;return new Response(JSON.stringify({detail:'Session changed'}),{status:403});}if(url==='/api/collections')return json([]);throw Error(url);});
  render(<App/>);await screen.findByRole('heading',{name:/Know what is ready/});await user.upload(screen.getByLabelText('Reporting pack and supporting documents'),new File(['date,amount\n2026-01-01,1'],'bank.csv',{type:'text/csv'}));await user.click(screen.getByRole('button',{name:'Prepare review brief'}));await screen.findByText(/Your session or permissions were refreshed/);await waitFor(()=>expect(sessions).toBe(2));expect(creates).toBe(1);
 });
});

it('offers business accounts without granting a session by choosing a role',async()=>{
 const user=userEvent.setup();vi.spyOn(globalThis,'fetch').mockResolvedValue(new Response('{}',{status:401}));
 render(<App/>);await screen.findByRole('heading',{name:'Sign in to CloseGraph'});
 for(const name of ['Accountant','Account manager','Fund manager','Investor'])expect(screen.getByRole('button',{name})).toBeVisible();
 await user.click(screen.getByRole('button',{name:'Account manager'}));expect(screen.getByLabelText('Username')).toHaveValue('account_manager');
 expect(screen.getByLabelText('Password')).toHaveValue('');expect(screen.queryByRole('navigation',{name:'Main navigation'})).not.toBeInTheDocument();
});
