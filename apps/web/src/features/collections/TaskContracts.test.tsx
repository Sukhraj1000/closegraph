import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { TasksPanel } from './TasksPanel';
import { CollectionsApi } from './api';
import type { Collection } from './model';
const base:Collection={id:'col-1',title:'Evidence',fund_id:'Fund',version:5,status:'NEEDS_REVIEW',sources:[],datasets:[],issues:[],recipe:null,steps:[],history:[],review:null,artifacts:[],summary:{},tasks:[],access:{actor_id:'manager',party:'account_manager',can_manage:true,can_prepare:true,can_review:true,can_flag:true,restricted:false}};
function mount(collection:Collection,restricted=false){const onChange=vi.fn(async fn=>{await fn();});render(<TasksPanel collection={collection} api={new CollectionsApi('csrf')} pending={false} actor={collection.access?.actor_id??'manager'} canFlag={false} restricted={restricted} onChange={onChange} onUpload={vi.fn()} onDocument={vi.fn()}/>);return onChange;}
afterEach(()=>vi.restoreAllMocks());
describe('manual concern and withdrawn-task controls',()=>{
 it('excludes withdrawn policies from Active tasks while retaining readable history',async()=>{
  const user=userEvent.setup();mount({...base,tasks:[{id:'withdrawn',title:'Superseded evidence policy',status:'open',active:false,allowed_actions:['acknowledge']},{id:'current',title:'Current evidence request',status:'open',active:true,allowed_actions:[]}]});
  expect(screen.queryByText('Superseded evidence policy')).not.toBeInTheDocument();expect(screen.getByRole('heading',{name:'Current evidence request'})).toBeVisible();
  await user.selectOptions(screen.getByRole('combobox',{name:'Task filter'}),'all');await user.click(screen.getByRole('button',{name:/Superseded evidence policy/}));
  expect(screen.getByText('Withdrawn',{exact:true})).toBeVisible();expect(screen.queryByRole('button',{name:'Acknowledge request'})).not.toBeInTheDocument();
 });
 it('labels an unverified manual concern and lets only its allowed manager make it blocking with a note',async()=>{
  const action=vi.spyOn(CollectionsApi.prototype,'taskAction').mockResolvedValue(base),user=userEvent.setup();mount({...base,tasks:[{id:'concern',kind:'manual',title:'Value looks inconsistent',status:'open',active:true,blocking:false,allowed_actions:['make_blocking']}]});
  expect(screen.getByText('Manually raised concern')).toBeVisible();expect(screen.getByText(/an automated check has not verified/)).toBeVisible();
  const button=screen.getByRole('button',{name:'Require resolution before output release'});expect(button).toBeDisabled();await user.type(screen.getByRole('textbox',{name:'Response or action note'}),'Resolve the discrepancy before release.');await user.click(button);
  await waitFor(()=>expect(action).toHaveBeenCalledWith('col-1',5,'concern','make_blocking','Resolve the discrepancy before release.'));
 });
 it('hides manager-only blocking controls from other parties even if stale actions contain one',()=>{
  mount({...base,access:{...base.access!,actor_id:'accountant',party:'accountant',can_manage:false},tasks:[{id:'concern',kind:'manual',title:'Manual concern',status:'open',active:true,allowed_actions:['make_blocking']}]});
  expect(screen.queryByRole('button',{name:'Require resolution before output release'})).not.toBeInTheDocument();
 });
 it('allows a restricted member to flag only available managers without exposing other recipients',async()=>{
  const save=vi.spyOn(CollectionsApi.prototype,'flag').mockResolvedValue(base),user=userEvent.setup();
  mount({...base,access:{...base.access!,actor_id:'investor',party:'investor',can_prepare:false,can_manage:false,can_review:false,can_flag:true,restricted:true},flag_recipients:[{actor_id:'manager',party:'account_manager',display_name:'Morgan Manager'},{actor_id:'accountant',party:'accountant',display_name:'Private Accountant'}]},true);
  await user.click(screen.getByText('Raise a concern or request evidence'));expect(screen.queryByRole('combobox',{name:'Responsible team'})).not.toBeInTheDocument();expect(screen.queryByRole('option',{name:'Private Accountant'})).not.toBeInTheDocument();
  await user.type(screen.getByRole('textbox',{name:'What needs attention?'}),'Please explain the amount');await user.type(screen.getByRole('textbox',{name:'Explain the request'}),'The amount differs from my statement.');await user.selectOptions(screen.getByRole('combobox',{name:'Assign to'}),'manager');await user.click(screen.getByRole('button',{name:'Create task'}));
  await waitFor(()=>expect(save).toHaveBeenCalledWith('col-1',5,{title:'Please explain the amount',reason:'The amount differs from my statement.',document_ids:[],owner_actor_id:'manager'}));
 });
});

