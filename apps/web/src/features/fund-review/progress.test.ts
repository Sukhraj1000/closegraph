import {describe,it,expect} from 'vitest';
import {progressLabel} from './progress';
import {accountLabel} from '../../lib/roles';
describe('business roles and saved-job progress',()=>{
 it.each([undefined,{}, {job_id:'old',kind:'fund_review',status:'COMPLETED'}, {stage:'Reading documents',completed_documents:1}, {completed_documents:NaN,total_documents:2}, {completed_documents:3,total_documents:2}])('never invents document counts from incomplete metadata %j',value=>{expect(progressLabel(value)).not.toMatch(/undefined|NaN|null| of /);});
 it('shows available counts including a real zero',()=>{expect(progressLabel({stage:'Reading documents',completed_documents:0,total_documents:3})).toBe('Reading documents · 0 of 3 documents');});
 it.each([['preparer','PREPARER','Accountant'],['reviewer','REVIEWER','Account manager'],['fund_manager','FUND_MANAGER','Fund manager'],['investor','INVESTOR','Investor'],['Sam','REVIEWER','Sam · Account manager']])('uses the actual role for %s',(id,role,label)=>expect(accountLabel(id,role)).toBe(label));
});
