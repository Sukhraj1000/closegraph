import {act,render,screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {it,expect,vi} from 'vitest';
import {DatasetReview} from '../collections/DatasetReview';
import {CollectionsApi} from '../collections/api';
import type {Collection,Dataset,RowPage} from '../collections/model';
it('keeps correction input and submission disabled until the cited row is loaded',async()=>{
 let resolve!:(page:RowPage)=>void;const waiting=new Promise<RowPage>(r=>{resolve=r;});const api=new CollectionsApi('csrf');vi.spyOn(api,'rows').mockImplementation(()=>waiting);const dataset:Dataset={id:'d',table_id:'t',source_id:'s',title:'Source table',kind:'extraction',columns:[{key:'c1',label:'Investor'}],row_count:1,accepted:false,version:1};const work={id:'review',version:1,sources:[{id:'s',filename:'source.xlsx',media_type:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}],datasets:[dataset]} as unknown as Collection;
 render(<DatasetReview collection={work} dataset={dataset} api={api} pending={false} canEdit={true} issue={{id:'finding',table_id:'d',row_id:'r1',column_key:'c1',code:'REVIEW_EVIDENCE',severity:'info',message:'Inspect this source'}} onChange={async()=>{}} onError={()=>{}}/>);expect(screen.getByLabelText('Corrected value')).toBeDisabled();expect(screen.getByRole('button',{name:'Save extraction decision'})).toBeDisabled();await act(async()=>resolve({dataset_id:'d',columns:dataset.columns,rows:[{row_id:'r1',values:{c1:'Investor A'}}],total:1,offset:0,limit:50}));expect(screen.getByLabelText('Corrected value')).toBeEnabled();expect(screen.getByLabelText('Corrected value')).toHaveValue('Investor A');await userEvent.setup().clear(screen.getByLabelText('Corrected value'));await userEvent.setup().type(screen.getByLabelText('Corrected value'),'Investor B');expect(screen.getByLabelText('Corrected value')).toHaveValue('Investor B');
});
