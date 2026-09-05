import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../../lib/api';
import type { Session } from '../../lib/model';
import { CollectionsApi } from './api';
import { CollectionsWorkspace } from './CollectionsWorkspace';
import { RecipeEditor, emptyRecipe, parseRecipe } from './RecipeEditor';
import type { Collection, RowPage } from './model';
const session:Session={username:'fictional-preparer',role:'PREPARER',csrf_token:'test-csrf',collection_funds:[{tenant_id:'fictional',fund_id:'review-fund'}]};
const base:Collection={id:'col-test',title:'Fictional source review',fund_id:'review-fund',version:3,status:'NEEDS_REVIEW',sources:[{id:'source-1',filename:'unfamiliar-layout.csv',media_type:'text/csv',status:'EXTRACTED'}],datasets:[{id:'data-1',table_id:'table-1',source_id:'source-1',title:'Unfamiliar table',columns:[{key:'c1',label:'Name'},{key:'c2',label:'Amount'}],row_count:2,accepted:false,kind:'extraction',version:3}],issues:[],recipe:null,steps:[],history:[],review:null,artifacts:[],summary:{}};
const page:RowPage={dataset_id:'data-1',columns:base.datasets[0].columns,rows:[{row_id:'r1',values:{c1:'North',c2:'12.20'},raw_values:{c1:'North',c2:'12.20'},locators:{c2:{kind:'csv',row:2,column:2}}},{row_id:'r2',values:{c1:'South',c2:'8.10'},raw_values:{c2:'8.10'},locators:{c2:{kind:'csv',row:3,column:2}}}],total:2,offset:0,limit:50};
function mock(collection=base){vi.spyOn(CollectionsApi.prototype,'list').mockResolvedValue([collection]);vi.spyOn(CollectionsApi.prototype,'get').mockResolvedValue(collection);vi.spyOn(CollectionsApi.prototype,'rows').mockResolvedValue(page);}
function mount(principal=session){return render(<CollectionsWorkspace session={principal} onReports={vi.fn()} onLogout={vi.fn()} onUnauthorized={vi.fn()}/>);}
afterEach(()=>vi.restoreAllMocks());
describe('collection evidence review',()=>{
 it('shows source coordinates and sends a reasoned correction for the exact revision',async()=>{
  mock();const edit=vi.spyOn(CollectionsApi.prototype,'edit').mockResolvedValue({...base,version:4});const user=userEvent.setup();mount();
  await user.click(await screen.findByRole('button',{name:'Amount, row 1: 12.20'}));
  expect(screen.getByText('row: 2 · column: 2',{exact:false})).toBeVisible();
  await user.clear(screen.getByRole('textbox',{name:'Corrected value'}));await user.type(screen.getByRole('textbox',{name:'Corrected value'}),'12.25');
  await user.type(screen.getByRole('textbox',{name:'Reason and source evidence'}),'Original source row 2 shows 12.25.');await user.click(screen.getByRole('button',{name:'Save extraction decision'}));
  await waitFor(()=>expect(edit).toHaveBeenCalledWith('col-test',3,'data-1',[{op:'set_cell',row_id:'r1',column_key:'c2',value:'12.25'}],'Original source row 2 shows 12.25.'));
 });
 it('jumps to a flagged row through server pagination without guessing source coordinates',async()=>{
  mock({...base,issues:[{id:'issue-1',severity:'warning',code:'missing_value',message:'Inspect a missing value',table_id:'table-1',row_id:'r2',column_key:'c2'}]});const user=userEvent.setup();mount();
  await user.click(await screen.findByRole('button',{name:/Inspect a missing value/}));
  await waitFor(()=>expect(CollectionsApi.prototype.rows).toHaveBeenLastCalledWith('col-test','data-1',0,50,expect.any(AbortSignal),'r2'));
  expect(await screen.findByRole('button',{name:'Amount, row 2: 8.10'})).toHaveAttribute('aria-pressed','true');
 });
 it('records unresolved concerns rather than relabelling extraction as accepted',async()=>{
  mock();const edit=vi.spyOn(CollectionsApi.prototype,'edit').mockResolvedValue({...base,version:4}),accept=vi.spyOn(CollectionsApi.prototype,'accept');const user=userEvent.setup();mount();await screen.findByRole('heading',{name:'Fictional source review'});
  await user.selectOptions(screen.getByRole('combobox',{name:'Action'}),'mark_unresolved');await user.type(screen.getByRole('textbox',{name:'Unresolved concern'}),'Missing last page');await user.type(screen.getByRole('textbox',{name:'Reason and source evidence'}),'Page count differs from the original.');await user.click(screen.getByRole('button',{name:'Save extraction decision'}));
  await waitFor(()=>expect(edit).toHaveBeenCalledWith('col-test',3,'data-1',[{op:'mark_unresolved',message:'Missing last page'}],'Page count differs from the original.'));expect(accept).not.toHaveBeenCalled();
 });
 it('refreshes a conflicting revision and never silently retries a correction',async()=>{
  mock();const edit=vi.spyOn(CollectionsApi.prototype,'edit').mockRejectedValue(new ApiError(409,'Stale revision'));const user=userEvent.setup();mount();await user.click(await screen.findByRole('button',{name:'Amount, row 1: 12.20'}));await user.type(screen.getByRole('textbox',{name:'Reason and source evidence'}),'Inspect original row');await user.click(screen.getByRole('button',{name:'Save extraction decision'}));
  expect(await screen.findByText(/latest revision is loaded/)).toBeVisible();expect(edit).toHaveBeenCalledTimes(1);
 });
 it('requires an independent reviewer and inspection before approval, and keeps exports gated',async()=>{
  const ready:Collection={...base,status:'READY_FOR_REVIEW',datasets:[{...base.datasets[0],accepted:true},{...base.datasets[0],id:'output-1',table_id:'output',kind:'output',accepted:false}],candidates:[{candidate_id:'candidate-1',dataset_id:'output-1',format:'csv',filename:'table.csv',media_type:'text/csv',byte_size:34,verification:{verified:true},url:'/api/collections/col-test/candidates/candidate-1'}]};
  mock(ready);const approve=vi.spyOn(CollectionsApi.prototype,'review').mockResolvedValue({...ready,status:'APPROVED',version:4});const user=userEvent.setup();mount({...session,username:'fictional-reviewer',role:'REVIEWER'});await user.click(await screen.findByRole('button',{name:/Output & release/}));
  expect(screen.getByRole('button',{name:'Approve exact output'})).toBeDisabled();expect(screen.getByRole('button',{name:'Export CSV'})).toBeDisabled();expect(screen.getByRole('link',{name:'Inspect draft CSV'})).toHaveAttribute('href','/api/collections/col-test/candidates/candidate-1');
  await user.type(screen.getByRole('textbox',{name:'Independent review reason'}),'Compared original evidence, output and required checks.');await user.click(screen.getByRole('checkbox',{name:/I inspected the source evidence/}));await user.click(screen.getByRole('button',{name:'Approve exact output'}));
  await waitFor(()=>expect(approve).toHaveBeenCalledWith('col-test',3,'APPROVE','Compared original evidence, output and required checks.'));expect(await screen.findByRole('button',{name:'Export CSV'})).toBeEnabled();
 });
 it('does not expose approval controls to the preparer',async()=>{
  mock({...base,status:'READY_FOR_REVIEW',datasets:[{...base.datasets[0],kind:'output'}]});const user=userEvent.setup();mount();await user.click(await screen.findByRole('button',{name:/Output & release/}));expect(screen.queryByRole('button',{name:'Approve exact output'})).not.toBeInTheDocument();expect(screen.getByRole('button',{name:'Export XLSX'})).toBeDisabled();
 });
 it('uses collection grants when no reporting pack scope exists',async()=>{vi.spyOn(CollectionsApi.prototype,'list').mockResolvedValue([]);mount();await screen.findByText('Review the data.',{exact:false});expect(screen.getByRole('combobox',{name:'Fund'})).toHaveValue('review-fund');expect(screen.getByRole('button',{name:'Create collection'})).toBeEnabled();});
 it('ignores an obsolete session list response after unmount',async()=>{
  let resolve!:(value:Collection[])=>void;vi.spyOn(CollectionsApi.prototype,'list').mockReturnValue(new Promise(r=>{resolve=r;}));const get=vi.spyOn(CollectionsApi.prototype,'get');const view=mount();view.unmount();await act(async()=>resolve([base]));expect(get).not.toHaveBeenCalled();
 });
});
describe('explicit recipe configuration',()=>{
 it('allows a saved draft but blocks running before all inputs are accepted',async()=>{
  const save=vi.fn().mockResolvedValue(undefined),run=vi.fn(),user=userEvent.setup();render(<RecipeEditor collection={base} pending={false} canEdit onSave={save} onRun={run}/>);expect(screen.getByRole('button',{name:'Save and transform'})).toBeDisabled();await user.click(screen.getByRole('button',{name:'Save recipe'}));expect(save).toHaveBeenCalledWith(emptyRecipe('table-1'));expect(run).not.toHaveBeenCalled();
 });
 it('builds a visible operation draft without executing or inventing financial rules',async()=>{
  const user=userEvent.setup();render(<RecipeEditor collection={{...base,datasets:[{...base.datasets[0],accepted:true}]}} pending={false} canEdit onSave={vi.fn()} onRun={vi.fn()}/>);await user.click(screen.getByRole('button',{name:'Configure select step'}));await user.click(screen.getByRole('button',{name:'Add configured step'}));const recipe=parseRecipe((screen.getByRole('textbox',{name:'Complete recipe'}) as HTMLTextAreaElement).value);expect(recipe).toEqual({version:1,steps:[{id:'step_1',op:'select',input:'table-1',columns:['c1','c2']}],output:'step_1',checks:[]});
 });
});
