import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Session } from '../../lib/model';
import { CollectionsWorkspace } from './CollectionsWorkspace';
import { CollectionsApi } from './api';
import { ChangesPanel } from './ChangesPanel';
import { mappingRecipe, type FieldMapping } from './SimpleMapping';
import { TasksPanel } from './TasksPanel';
import { RequirementsPanel } from './RequirementsPanel';
import { MembersPanel } from './MembersPanel';
import type { Collection, Dataset } from './model';
const dataset:Dataset={id:'private-dataset-id',table_id:'private-table-key',source_id:'file-1',title:'Transactions',columns:[{key:'c1',label:'Date'},{key:'c2',label:'Amount'}],row_count:1,accepted:true,kind:'extraction',version:2};
const collection:Collection={id:'collection-1',title:'March evidence',fund_id:'Fund North',version:2,status:'ACCEPTED',sources:[{id:'file-1',filename:'statement.csv',media_type:'text/csv',status:'EXTRACTED'}],documents:[{id:'doc-1',title:'Bank statement',period:'March 2026',current_revision_id:'file-1',revisions:['file-1']}],datasets:[dataset],issues:[],recipe:null,steps:[],history:[],review:null,artifacts:[],summary:{},access:{party:'accountant',actor_id:'accountant-id',can_prepare:true,can_manage:false,can_review:false,restricted:false},requirements:[],tasks:[]};
const session:Session={username:'accountant',role:'ACCOUNTANT',csrf_token:'test',collection_funds:[{tenant_id:'t',fund_id:'Fund North'}]};
function mount(value=collection,principal=session){vi.spyOn(CollectionsApi.prototype,'list').mockResolvedValue([value]);vi.spyOn(CollectionsApi.prototype,'get').mockResolvedValue(value);vi.spyOn(CollectionsApi.prototype,'history').mockResolvedValue([]);vi.spyOn(CollectionsApi.prototype,'rows').mockResolvedValue({dataset_id:dataset.id,columns:dataset.columns,rows:[{row_id:'r1',values:{c1:'31/03/2026',c2:'1234.56'}}],total:1,offset:0,limit:50});return render(<CollectionsWorkspace session={principal} onReports={vi.fn()} onLogout={vi.fn()} onUnauthorized={vi.fn()}/>);}
afterEach(()=>vi.restoreAllMocks());
describe('document-first evidence workspace',()=>{
 it('starts with readable navigation and keeps internal keys out of standard document review',async()=>{
  const user=userEvent.setup();mount();await screen.findByRole('heading',{name:'March evidence'});
  for(const name of ['Overview','Documents','Tasks','Review changes','Outputs'])expect(screen.getByRole('button',{name})).toBeVisible();
  await user.click(screen.getByRole('button',{name:'Documents'}));await screen.findByRole('button',{name:'Date, row 1: 31/03/2026'});
  expect(screen.queryByText('private-table-key')).not.toBeInTheDocument();expect(screen.queryByText('c1')).not.toBeInTheDocument();
  expect(screen.getByRole('button',{name:'Upload new version'})).toBeVisible();
 });
 it('binds a replacement to the selected logical document and exact previous version',async()=>{
  const user=userEvent.setup(),upload=vi.spyOn(CollectionsApi.prototype,'upload').mockResolvedValue({...collection,version:3});mount();
  await user.click(await screen.findByRole('button',{name:'Documents'}));await user.click(screen.getByRole('button',{name:'Upload new version'}));
  const file=new File(['Date,Amount\n31/03/2026,1240.00'],'statement-updated.csv',{type:'text/csv'});Object.defineProperty(file,'arrayBuffer',{value:async()=>new TextEncoder().encode('Date,Amount\n31/03/2026,1240.00').buffer});
  await user.upload(screen.getByLabelText('Replacement file'),file);await user.type(screen.getByRole('textbox',{name:'What changed?'}),'Bank supplied a corrected fee.');await user.click(screen.getByRole('button',{name:'Save new version'}));
  await waitFor(()=>expect(upload).toHaveBeenCalledWith('collection-1',2,expect.objectContaining({filename:'statement-updated.csv'}),expect.objectContaining({document_id:'doc-1',parent_revision_id:'file-1',reason:'Bank supplied a corrected fee.',idempotency_key:expect.any(String)})));
 });
 it('shows investors only their request portal and shared documents',async()=>{
  const restricted:Collection={...collection,title:'Shared request',sources:[],documents:[],datasets:[],tasks:[{id:'task-1',title:'Please supply March evidence',status:'open',owner_actor_id:'investor-id',owner_party:'investor',allowed_actions:['acknowledge']}],access:{party:'investor',actor_id:'investor-id',can_prepare:false,can_manage:false,can_review:false,restricted:true}};
  mount(restricted,{...session,role:'INVESTOR',username:'investor'});await screen.findByRole('heading',{name:'Shared request'});
  expect(screen.getByRole('button',{name:'Documents'})).toBeVisible();expect(screen.getByRole('button',{name:/Tasks/})).toBeVisible();
  for(const name of ['Overview','Review changes','Outputs','Reports','Create collection'])expect(screen.queryByRole('button',{name})).not.toBeInTheDocument();
  expect(screen.queryByText('Bank statement')).not.toBeInTheDocument();expect(CollectionsApi.prototype.history).not.toHaveBeenCalled();
 });
 it('uses an explicit date format and decimal separators while leaving source data untouched',()=>{
  const fields:FieldMapping[]=[{key:'c1',label:'Posting date',included:true,format:'date',dateFormat:'%d/%m/%Y',numberFormat:'plain'},{key:'c2',label:'Amount',included:true,format:'decimal',dateFormat:'%d/%m/%Y',numberFormat:'grouped'}];
  const recipe=mappingRecipe(dataset,fields,['csv','xlsx']);
  expect(recipe.steps[0]).toEqual({id:'read_formats',op:'derive',input:'private-table-key',columns:{c1:{op:'date',args:[{column:'c1'}],format:'%d/%m/%Y'},c2:{op:'decimal',args:[{column:'c2'}],decimal_separator:'.',thousands_separator:','}}});
  expect(dataset.columns[0]).toEqual({key:'c1',label:'Date'});expect(recipe.steps[2]).toMatchObject({op:'rename',columns:{c1:'Posting date',c2:'Amount'}});
  expect(()=>mappingRecipe(dataset,[...fields.map(f=>({...f,label:'Duplicate'}))],['csv'])).toThrow(/different/);
 });
 it('displays both old and new values and does not claim complete coverage for ambiguous comparisons',async()=>{
  vi.spyOn(CollectionsApi.prototype,'comparison').mockResolvedValue({summary:{change_count:1},changes:[{id:'change-1',kind:'cell_changed',before_locator:{kind:'xlsx',sheet:'Fees',cell:'B2'},after_locator:{kind:'xlsx',sheet:'Fees',cell:'B2'},before:{value:'12.20'},after:{value:'12.25'},fields:['value']}],ambiguities:[{message:'Two rows use the same business key.'}],coverage:{complete:false},total:1,offset:0,limit:50});
  render(<ChangesPanel collection={{...collection,comparisons:[{id:'comparison-1',document_id:'doc-1',before_revision_id:'file-1',after_revision_id:'file-2',status:'NEEDS_REVIEW',summary:{}}]}} api={new CollectionsApi('test')} pending={false} canManage={false} onChange={vi.fn()} onError={vi.fn()}/>);
  expect(await screen.findByText('12.20')).toBeVisible();expect(screen.getByText('12.25')).toBeVisible();expect(screen.getByText('Two rows use the same business key.')).toBeVisible();expect(screen.getByText('Review comparison limits')).toBeVisible();expect(screen.getByRole('link',{name:'Open previous original'})).toHaveAttribute('href','/api/collections/collection-1/sources/file-1/download');
 });
 it('requires a note and uses only server-allowed task actions',async()=>{
  const action=vi.spyOn(CollectionsApi.prototype,'taskAction').mockResolvedValue(collection),onChange=vi.fn(async fn=>{await fn();}),user=userEvent.setup();
  render(<TasksPanel collection={{...collection,tasks:[{id:'task-1',title:'Missing March statement',status:'open',requirement_id:'req-1',allowed_actions:['acknowledge','evidence_received']}]}} api={new CollectionsApi('test')} pending={false} actor="accountant-id" canFlag={false} restricted={false} onChange={onChange} onUpload={vi.fn()} onDocument={vi.fn()}/>);
  expect(screen.queryByRole('button',{name:'Resolve concern'})).not.toBeInTheDocument();expect(screen.getByRole('button',{name:'Acknowledge request'})).toBeDisabled();
  await user.type(screen.getByRole('textbox',{name:'Response or action note'}),'Requested a replacement statement.');await user.click(screen.getByRole('button',{name:'Acknowledge request'}));
  await waitFor(()=>expect(action).toHaveBeenCalledWith('collection-1',2,'task-1','acknowledge','Requested a replacement statement.'));
 });
 it('creates a request for evidence not yet received without binding an unrelated document',async()=>{
  const save=vi.spyOn(CollectionsApi.prototype,'requirements').mockResolvedValue(collection),onChange=vi.fn(async fn=>{await fn();}),user=userEvent.setup();
  render(<RequirementsPanel collection={{...collection,members:[{actor_id:'accountant-id',party:'accountant',display_name:'Alex Accountant',document_ids:[]}]}} api={new CollectionsApi('test')} pending={false} canManage onChange={onChange} onDocument={vi.fn()}/>);
  await user.click(screen.getByText('Add a required check'));await user.type(screen.getByRole('textbox',{name:'Check name'}),'Signed statement is required');await user.selectOptions(screen.getByRole('combobox',{name:'Responsible person'}),'accountant-id');await user.click(screen.getByRole('button',{name:'Add check'}));
  await waitFor(()=>expect(save).toHaveBeenCalledWith('collection-1',2,[expect.objectContaining({kind:'evidence',document_ids:[],owner_actor_id:'accountant-id',parameters:{minimum_documents:1}})]));
 });
 it('saves only explicitly selected document grants for a named investor',async()=>{
  vi.spyOn(CollectionsApi.prototype,'participants').mockResolvedValue([{actor_id:'investor-id',party:'investor',display_name:'Morgan Investor',document_ids:[]}]);
  const save=vi.spyOn(CollectionsApi.prototype,'members').mockResolvedValue(collection),onChange=vi.fn(async fn=>{await fn();}),user=userEvent.setup();
  render(<MembersPanel collection={collection} api={new CollectionsApi('test')} pending={false} onChange={onChange}/>);
  await screen.findByRole('option',{name:'Morgan Investor'});await user.selectOptions(screen.getByRole('combobox',{name:'Add a person'}),'investor-id');await user.click(screen.getByRole('button',{name:'Add to team'}));
  expect(screen.getByRole('checkbox',{name:'Bank statement'})).not.toBeChecked();await user.click(screen.getByRole('checkbox',{name:'Bank statement'}));await user.click(screen.getByRole('button',{name:'Save people and sharing'}));
  await waitFor(()=>expect(save).toHaveBeenCalledWith('collection-1',2,[{actor_id:'investor-id',party:'investor',document_ids:['doc-1'],request_ids:[]}]))
 });
 it('requires inspection and a reason before recording unresolved comparison review',async()=>{
  vi.spyOn(CollectionsApi.prototype,'comparison').mockResolvedValue({summary:{},changes:[],ambiguities:[],coverage:{complete:false},total:0,offset:0,limit:50});
  const save=vi.spyOn(CollectionsApi.prototype,'reviewComparison').mockResolvedValue(collection),onChange=vi.fn(async fn=>{await fn();}),user=userEvent.setup();
  render(<ChangesPanel collection={{...collection,comparisons:[{id:'comparison-1',document_id:'doc-1',before_revision_id:'file-1',after_revision_id:'file-2',status:'NEEDS_REVIEW',summary:{}}]}} api={new CollectionsApi('test')} pending={false} canManage onChange={onChange} onError={vi.fn()}/>);
  expect(screen.getByRole('button',{name:'Record comparison review'})).toBeDisabled();await user.click(screen.getByRole('checkbox',{name:'I compared the original versions and reviewed the unresolved differences'}));await user.type(screen.getByRole('textbox',{name:'Comparison review notes'}),'Compared both original pages and checked the changed amount.');await user.click(screen.getByRole('button',{name:'Record comparison review'}));
  await waitFor(()=>expect(save).toHaveBeenCalledWith('collection-1',2,'comparison-1','Compared both original pages and checked the changed amount.'));
 });

});

