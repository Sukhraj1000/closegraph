import {render,screen,within,waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach,it,expect,vi} from 'vitest';
import {FundReviewWorkspace} from './Workspace';
import {RequestInbox} from './RequestInbox';
import {ReviewHistory} from './ReviewHistory';
import {findingTitle,fileFailure} from './presentation';
import {TasksPanel} from '../collections/TasksPanel';
import {CollectionsApi} from '../collections/api';
import type {FundWork} from './api';

const task={id:'question',title:'Confirm the quarter',status:'acknowledged',kind:'manual' as const,owner_actor_id:'account_manager',owner_party:'account_manager' as const,allowed_actions:['reply','evidence_received'],events:[]};
const work={id:'review-one',title:'Quarterly review',version:2,status:'NEEDS_REVIEW',sources:[],datasets:[],issues:[],tasks:[task],notifications:[],members:[],history:[],access:{actor_id:'account_manager',party:'account_manager',can_manage:true,can_prepare:false,restricted:false}} as unknown as FundWork;
afterEach(()=>{vi.restoreAllMocks();sessionStorage.clear();});

it('opens assigned work across reviews immediately, with no review selection',async()=>{
 const second={...work,id:'review-two',title:'Second review',tasks:[{...task,id:'second-question',title:'Confirm another quarter'}]};
 vi.spyOn(globalThis,'fetch').mockImplementation(async input=>new Response(JSON.stringify(String(input)==='/api/collections'?[work,second]:String(input).endsWith('review-two')?second:work)));
 render(<FundReviewWorkspace session={{username:'account_manager',role:'ACCOUNT_MANAGER',csrf_token:'test'}} notice="" onLogout={()=>{}} onSessionChange={()=>{}}/>);
 const user=userEvent.setup();await user.click(screen.getByRole('button',{name:'Requests'}));
 expect(await screen.findByRole('button',{name:/Confirm the quarter/})).toBeVisible();
 expect(screen.getByRole('button',{name:/Confirm another quarter/})).toBeVisible();
 expect(screen.getByLabelText('Review requests')).toHaveValue('');
 await user.click(screen.getByRole('button',{name:/Confirm another quarter/}));
 expect(await screen.findByRole('button',{name:'Send reply'})).toBeVisible();
});

it('keeps read state and request state separate and shows the event in updates',async()=>{
 const onRead=vi.fn(),onOpen=vi.fn();
 render(<RequestInbox works={[{...work,notifications:[{id:'notice',task_id:'question',event:'evidence_received',actor_id:'fund_manager',created_at:'2026-09-06T10:00:00Z',title:'Confirm the quarter'}]}]} username="account_manager" loading={false} pending={false} onRead={onRead} onOpen={onOpen}/>);
 const updates=screen.getByRole('region',{name:'Notification updates'});
 expect(within(updates).getByText(/Fund manager · Attached evidence/)).toBeVisible();
 await userEvent.setup().click(within(updates).getByRole('button',{name:'Mark read'}));
 expect(onRead).toHaveBeenCalledWith(expect.objectContaining({id:work.id}),['notice']);
 expect(task.status).toBe('acknowledged');expect(onOpen).not.toHaveBeenCalled();
});

it('sends a reply without changing status and offers clear evidence controls',async()=>{
 const api=new CollectionsApi('test');vi.spyOn(api,'taskAction').mockResolvedValue(work);
 render(<TasksPanel collection={work} api={api} pending={false} actor="account_manager" restricted={false} canFlag={false} onChange={async action=>{await action();}} onUpload={async()=>{}} onDocument={()=>{}}/>);
 const user=userEvent.setup();await user.type(screen.getByLabelText('Response or action note'),'The quarter is awaiting confirmation.');await user.click(screen.getByRole('button',{name:'Send reply'}));
 await waitFor(()=>expect(api.taskAction).toHaveBeenCalledWith(work.id,work.version,task.id,'reply','The quarter is awaiting confirmation.'));
 expect(await screen.findByText('Reply sent. The request remains open.')).toBeVisible();
 expect(screen.getByLabelText('Choose evidence file')).toBeVisible();expect(screen.getByRole('button',{name:'Attach evidence'})).toBeDisabled();
});

it('uses observed reference keys and counts without guessing an entity for other checks',()=>{
 const finding={id:'x',match_key:'x',title:'Mapping coverage',kind:'reference',status:'difference' as const,explanation:'Missing reference',observed:['Entity A'],affected_count:1860,evidence:[]};
 expect(findingTitle(finding)).toBe('Mapping coverage · Entity A · 1,860 affected records');
 expect(findingTitle({...finding,kind:'totals',observed:'12.30'})).toBe('Mapping coverage · 1,860 affected records');
});

it('recognises old stored disk errors without exposing diagnostic paths',()=>{
 const source={id:'source',filename:'Real workbook.xlsx',media_type:'xlsx',status:'FAILED'};
 const text=fileFailure(source,[{id:'issue',source_id:'source',severity:'error',code:'extraction_failed',message:'[Errno 28] No space left on device: /private/path'}]);
 expect(text).toMatch(/Storage is full/);expect(text).not.toContain('/private/path');
});

it('shows newest material changes first while retaining routine activity',async()=>{
 render(<ReviewHistory work={work} events={[
  {event:'source_uploaded',actor_id:'accountant',at:'2026-09-05T12:00:00Z',detail:{reason:'Original submission'}},
  {event:'task_updated',actor_id:'account_manager',at:'2026-09-06T12:00:00Z',detail:{action:'reply',reason:'Latest answer'}},
  {event:'processing_completed',actor_id:'system',at:'2026-09-06T13:00:00Z',detail:{status:'COMPLETED'}},
 ]}/>);
 expect(screen.getAllByRole('article')[0]).toHaveTextContent('Latest answer');
 expect(screen.queryByText('Processing Completed')).not.toBeInTheDocument();
 await userEvent.setup().click(screen.getByRole('button',{name:'Show complete activity'}));
 expect(screen.getAllByRole('article')[0]).toHaveTextContent('System');
});
