import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { PackReview, type PackActions } from './PackReview';
import { initialScenario, snapshot } from '../../lib/synthetic';
const actions=():PackActions=>({correct:vi.fn().mockResolvedValue(undefined),recompute:vi.fn().mockResolvedValue(undefined),resolve:vi.fn().mockResolvedValue(undefined),review:vi.fn().mockResolvedValue(undefined),publish:vi.fn().mockResolvedValue(undefined)});
const preparer={username:'preparer',role:'preparer',csrf_token:'test'},reviewer={username:'reviewer',role:'reviewer',csrf_token:'test'};
describe('reviewer workspace',()=>{
 it('preserves a failed repair and separates completion from approval',async()=>{
  const user=userEvent.setup(),calls=actions();
  render(<PackReview pack={snapshot(initialScenario('correction'))} session={preparer} actions={calls} synthetic/>);
  await user.click(screen.getByRole('link',{name:'Checks'}));
  expect(screen.getByRole('main')).toHaveFocus();
  expect(screen.getAllByText('× Failed').length).toBeGreaterThan(0);
  await user.click(screen.getByRole('button',{name:'Processing and review details'}));
  expect(screen.getByText('Completed')).toBeVisible();
  expect(screen.getAllByText('Blocked').length).toBeGreaterThan(0);
  expect(calls.review).not.toHaveBeenCalled();
 });
 it('focuses invalid fields and preserves entered reason after an action failure',async()=>{
  const user=userEvent.setup(),calls=actions();calls.correct=vi.fn().mockRejectedValue(new Error('Version changed'));
  render(<PackReview pack={snapshot(initialScenario('correction'))} session={preparer} actions={calls} initialPage="correction" synthetic/>);
  await user.click(screen.getByRole('button',{name:'Save correction'}));
  const amount=screen.getByRole('textbox',{name:'Corrected amount (USD)'});
  expect(amount).toHaveFocus();expect(amount).toHaveAttribute('aria-invalid','true');
  await user.type(amount,'60000.00');
  await user.type(screen.getByRole('textbox',{name:'Why are you changing it?'}),'FT-002 supports the correction.');
  await user.selectOptions(screen.getByRole('combobox',{name:'Supporting source'}),'rule');
  await user.click(screen.getByRole('button',{name:'Save correction'}));
  expect(calls.correct).toHaveBeenCalledWith(expect.objectContaining({expected_version:2,value_decimal:'60000.00',source_id:'rule'}));
  expect(screen.getByRole('textbox',{name:'Why are you changing it?'})).toHaveValue('FT-002 supports the correction.');
 });
 it('requires an independent session, exact version attestation and review note',async()=>{
  const user=userEvent.setup(),calls=actions(),pack=snapshot(initialScenario('ready'));
  const {rerender}=render(<PackReview pack={pack} session={preparer} actions={calls} initialPage="review" synthetic/>);
  expect(screen.queryByRole('button',{name:'Approve version 4'})).not.toBeInTheDocument();
  rerender(<PackReview pack={pack} session={reviewer} actions={calls} initialPage="review" synthetic/>);
  const approve=screen.getByRole('button',{name:'Approve version 4'});expect(approve).toBeDisabled();
  await user.click(screen.getByText('I have reviewed version 4, the candidate workbook and its supporting evidence.'));
  await user.click(approve);expect(screen.getByRole('textbox',{name:'Review note'})).toHaveFocus();
  await user.type(screen.getByRole('textbox',{name:'Review note'}),'Inspected source and candidate.');
  await user.click(approve);expect(calls.review).toHaveBeenCalledWith({expected_version:4,note:'Inspected source and candidate.',attested:true});
 });
 it('does not permit stale approval or unknown required evidence',()=>{
  for(const scenario of ['missing','dependency','provider','stale','template'] as const){
   const {unmount}=render(<PackReview pack={snapshot(initialScenario(scenario))} session={reviewer} actions={actions()} initialPage="review" synthetic/>);
   expect(screen.getByRole('button',{name:/Approve version/})).toBeDisabled();
   expect(screen.getByRole('button',{name:'Preview export contents'})).toBeDisabled();
   unmount();
  }
 });
 it('opens source tabs with keyboard and allows inspecting unflagged values',async()=>{
  const user=userEvent.setup();
  render(<PackReview pack={snapshot(initialScenario('ready'))} session={reviewer} actions={actions()} initialPage="correction" synthetic/>);
  const rule=screen.getByRole('tab',{name:'Fee rule'});rule.focus();await user.keyboard('{ArrowRight}');
  expect(screen.getByRole('tab',{name:'Capital'})).toHaveAttribute('aria-selected','true');
  await user.keyboard('{End}');expect(screen.getByRole('tab',{name:'Original pack'})).toHaveAttribute('aria-selected','true');
  expect(screen.getByText('$75,000.00')).toBeVisible();
 });
});

describe('computed snapshot versus state revision',()=>{
 it('attests the checked candidate while sending the latest concurrency revision',async()=>{
  const user=userEvent.setup(),calls=actions(),pack=snapshot(initialScenario('ready'));
  pack.version=9;pack.candidate!.checked_version=7;
  render(<PackReview pack={pack} session={reviewer} actions={calls} initialPage="review" synthetic/>);
  await user.type(screen.getByRole('textbox',{name:'Review note'}),'Reviewed snapshot 7.');
  await user.click(screen.getByRole('checkbox'));
  await user.click(screen.getByRole('button',{name:'Approve version 7'}));
  expect(calls.review).toHaveBeenCalledWith({expected_version:9,note:'Reviewed snapshot 7.',attested:true});
 });
});

describe('immutable document citations',()=>{
 it('allows a correction when the original citation uses a document version ID',()=>{
  const pack=snapshot(initialScenario('correction'));
  pack.facts[0].source={document_version_id:'original-document-v1',locator:'Fees!F18'};
  render(<PackReview pack={pack} session={preparer} actions={actions()} initialPage="correction" synthetic/>);
  expect(screen.getByRole('button',{name:'Save correction'})).toBeEnabled();
 });
});

describe('alternative source readings',()=>{
 it('lets the preparer correct a disputed amount into a new snapshot',async()=>{
  const user=userEvent.setup(),calls=actions();
  render(<PackReview pack={snapshot(initialScenario('disagreement'))} session={preparer} actions={calls} initialPage="correction" synthetic/>);
  await user.type(screen.getByRole('textbox',{name:'Corrected amount (USD)'}),'60000.00');
  await user.type(screen.getByRole('textbox',{name:'Why are you changing it?'}),'Use the original approved source instead of the other reader.');
  await user.selectOptions(screen.getByRole('combobox',{name:'Supporting source'}),'rule');
  await user.click(screen.getByRole('button',{name:'Save correction'}));
  expect(calls.correct).toHaveBeenCalledWith(expect.objectContaining({expected_version:4,value_decimal:'60000.00'}));
 });
});

describe('observed review sampling',()=>{
 it('pins a ready sample to loaded state revision and opens that value without approving it',async()=>{
  const user=userEvent.setup(),calls=actions(),pack=snapshot(initialScenario('ready'));calls.observe=vi.fn().mockResolvedValue(undefined);pack.version=9;pack.candidate!.checked_version=7;
  render(<PackReview pack={pack} session={reviewer} actions={calls} initialPage="review" synthetic/>);
  await user.click(screen.getAllByRole('button',{name:/^Sample /})[0]);
  expect(calls.observe).toHaveBeenCalledWith({event_type:'READY_ITEM_SAMPLED',observed_snapshot_version:9,fact_id:pack.facts[0].fact_id});
  expect(screen.getByRole('link',{name:'Correction'})).toHaveAttribute('aria-current','page');
  expect(calls.review).not.toHaveBeenCalled();
 });
 it('routes source context/treatment changes through a new source version',async()=>{
  const user=userEvent.setup(),calls=actions();calls.replaceSource=vi.fn();
  render(<PackReview pack={snapshot(initialScenario('disagreement'))} session={preparer} actions={calls} initialPage="correction" synthetic/>);
  await user.click(screen.getByRole('button',{name:'Replace source or authorised rule'}));
  expect(calls.replaceSource).toHaveBeenCalledOnce();expect(calls.correct).not.toHaveBeenCalled();expect(calls.review).not.toHaveBeenCalled();
 });
});

it('uses fact-bound evidence for corrections and shows one tab per source document',()=>{
 const pack=snapshot(initialScenario('correction'));
 const evidence={source_id:'fee-rule',document_version_id:'rule-v1',filename:'fee-rule.csv',locator:'Rules!B2'};
 pack.evidence={'fee-rule:occurrence':{...evidence,fact_ids:[pack.facts[0].fact_id]},'fee-rule':{...evidence,document_version_id:'older-rule-v0'}};
 render(<PackReview pack={pack} session={preparer} actions={actions()} initialPage="correction" synthetic/>);
 const options=within(screen.getByRole('combobox',{name:'Supporting source'})).getAllByRole('option');
 expect(options).toHaveLength(2);expect(options[1]).toHaveValue('fee-rule:occurrence');
 expect(screen.getAllByRole('tab',{name:'Fee rule'})).toHaveLength(1);
});

it('clears review attestation when switching packs with the same revision number',async()=>{
 const user=userEvent.setup(),pack=snapshot(initialScenario('ready')),calls=actions();
 const {rerender}=render(<PackReview pack={pack} session={reviewer} actions={calls} initialPage="review" synthetic/>);
 await user.type(screen.getByRole('textbox',{name:'Review note'}),'Inspected this pack.');await user.click(screen.getByRole('checkbox'));
 expect(screen.getByRole('button',{name:'Approve version 4'})).toBeEnabled();
 rerender(<PackReview pack={{...pack,pack_id:'different-pack'}} session={reviewer} actions={calls} initialPage="review" synthetic/>);
 expect(screen.getByRole('button',{name:'Approve version 4'})).toBeDisabled();expect(screen.getByRole('textbox',{name:'Review note'})).toHaveValue('');
});

it('displays the known fee rate as an exact decimal without a currency in preview, checks and correction',async()=>{
 const user=userEvent.setup(),pack=snapshot(initialScenario('ready'));
 pack.facts[0].currency='GBP';
 pack.facts.push({...pack.facts[0],fact_id:'fee-rate',metric:'fee_rate',value_decimal:'0.005',raw_value:'0.005'});
 render(<PackReview pack={pack} session={preparer} actions={actions()} initialPage="review" synthetic/>);
 const ratePreview=screen.getByText('fee_rate',{exact:true}).closest('.paper-row')!;
 expect(within(ratePreview as HTMLElement).getByText('0.005',{exact:true})).toBeVisible();
 expect(screen.queryByText('GBP 0.005',{exact:true})).not.toBeInTheDocument();
 expect(screen.getAllByText('GBP 60,000.00',{exact:true}).length).toBeGreaterThan(0);
 await user.click(screen.getByRole('link',{name:'Checks'}));
 const row=screen.getByRole('row',{name:/fee_rate/});
 expect(within(row).getAllByRole('cell')[2]).toHaveTextContent(/^0\.005$/);
 await user.click(screen.getByRole('link',{name:'Correction'}));
 await user.selectOptions(screen.getByRole('combobox',{name:'Pack value'}),'fee-rate');
 expect(screen.getByRole('textbox',{name:'Corrected fee rate'})).toBeVisible();
 expect(screen.queryByText('GBP 0.005',{exact:true})).not.toBeInTheDocument();
});

function distinctSourceOccurrences(withAnchor:boolean) {
 const pack=snapshot(initialScenario('ready')),base=pack.facts[0];
 const original={source_id:'original',filename:'original.xlsx',document_version_id:'original-v1',content_hash:'original-hash'};
 const capital={source_id:'capital',filename:'capital.csv',document_version_id:'capital-v1',content_hash:'capital-hash',locator:{kind:'csv',row:2,column:'value'}};
 const feeLocator={kind:'xlsx',sheet:'Pack',cell:'B6'},statementLocator={kind:'xlsx',sheet:'Pack',cell:'B7'};
 pack.evidence={
  'capital:row2':{...capital,fact_ids:['capital'],preview_rows:[{label:'capital',value:'12000000'}]},
  'original:fee':{...original,locator:feeLocator,fact_ids:['fee'],preview_rows:[{label:'fee',value:'75000'}]},
  'original:statement':{...original,locator:statementLocator,fact_ids:['statement_fee'],preview_rows:[{label:'statement_fee',value:'80000'}]},
 };
 pack.facts=[
  {...base,fact_id:'capital',metric:'capital',value_decimal:'12000000',raw_value:'12000000',source:{document_version_id:capital.document_version_id,content_hash:capital.content_hash,locator:{...capital.locator,byte_offset:null},...(withAnchor?{source_id:'capital:row2'}:{})}},
  {...base,fact_id:'fee',metric:'fee',value_decimal:'75000',raw_value:'75000',source:{document_version_id:original.document_version_id,content_hash:original.content_hash,locator:{...feeLocator,formula:null,cached_value:null,cache_status:'UNKNOWN'},...(withAnchor?{source_id:'original:fee'}:{})}},
  {...base,fact_id:'statement_fee',metric:'statement_fee',value_decimal:'80000',raw_value:'80000',source:{document_version_id:original.document_version_id,content_hash:original.content_hash,locator:{...statementLocator,formula:null,cached_value:null,cache_status:'UNKNOWN'},...(withAnchor?{source_id:'original:statement'}:{})}},
 ];
 return pack;
}
it.each([true,false])('keeps exact occurrence content and citation together across evidence links and fact selection (anchor=%s)',async withAnchor=>{
 const user=userEvent.setup(),pack=distinctSourceOccurrences(withAnchor);
 render(<PackReview pack={pack} session={preparer} actions={actions()} initialPage="checks" synthetic/>);
 await user.click(screen.getByRole('button',{name:'Pack!B7'}));
 const originalTab=screen.getByRole('tab',{name:'Original pack'}),stableTabId=originalTab.id;
 expect(originalTab).toHaveAttribute('aria-selected','true');
 let evidence=within(screen.getByRole('tabpanel'));
 expect(evidence.getByText('statement_fee',{exact:true})).toBeVisible();
 expect(evidence.getByText('80000',{exact:true})).toBeVisible();
 expect(evidence.getByText('Pack!B7',{exact:true})).toBeVisible();
 expect(evidence.queryByText('75000',{exact:true})).not.toBeInTheDocument();
 await user.selectOptions(screen.getByRole('combobox',{name:'Pack value'}),'fee');
 expect(screen.getByRole('tab',{name:'Original pack'})).toHaveAttribute('id',stableTabId);
 evidence=within(screen.getByRole('tabpanel'));
 expect(evidence.getByText('fee',{exact:true})).toBeVisible();
 expect(evidence.getByText('75000',{exact:true})).toBeVisible();
 expect(evidence.getByText('Pack!B6',{exact:true})).toBeVisible();
 expect(evidence.queryByText('80000',{exact:true})).not.toBeInTheDocument();
 await user.selectOptions(screen.getByRole('combobox',{name:'Pack value'}),'capital');
 expect(screen.getByRole('tab',{name:'Capital'})).toHaveAttribute('aria-selected','true');
 evidence=within(screen.getByRole('tabpanel'));
 expect(evidence.getByText('12000000',{exact:true})).toBeVisible();
 expect(evidence.queryByText('75000',{exact:true})).not.toBeInTheDocument();
 await user.click(screen.getByRole('link',{name:'Checks'}));
 await user.click(screen.getByRole('button',{name:'Pack!B6'}));
 expect(screen.getByRole('tab',{name:'Original pack'})).toHaveAttribute('aria-selected','true');
 expect(within(screen.getByRole('tabpanel')).getByText('75000',{exact:true})).toBeVisible();
 expect(screen.getAllByRole('tab',{name:'Original pack'})).toHaveLength(1);
});
it('shows a missing exact occurrence citation without borrowing another cell preview',async()=>{
 const user=userEvent.setup(),pack=distinctSourceOccurrences(true);
 delete pack.evidence!['original:statement'];
 render(<PackReview pack={pack} session={preparer} actions={actions()} initialPage="checks" synthetic/>);
 await user.click(screen.getByRole('button',{name:'Pack!B7'}));
 expect(screen.getByRole('tab',{name:'Original pack'})).toHaveAttribute('aria-selected','true');
 const evidence=within(screen.getByRole('tabpanel'));
 expect(evidence.getByText('Pack!B7',{exact:true})).toBeVisible();
 expect(evidence.queryByText('75000',{exact:true})).not.toBeInTheDocument();
 expect(evidence.queryByText('80000',{exact:true})).not.toBeInTheDocument();
});
