import type { Page } from '@playwright/test';
import { test, expect } from './fixtures';
import { createRequire } from 'node:module';
const require=createRequire(import.meta.url);
const storyOrigin=process.env.CLOSEGRAPH_STORYBOOK_URL??'http://127.0.0.1:24174';
const axePath=require.resolve('axe-core/axe.min.js');
const scenarios=[
 ['fee-correction','correction','Fee correction — start here'],
 ['missing-agreement','missing','Missing fee agreement'],
 ['reader-disagreement','disagreement','Document readers disagree'],
 ['unknown-dependency','dependency','Unknown effect on a statement'],
 ['provider-unavailable','provider','PDF processing unavailable'],
 ['ready-for-review','ready','Ready for independent review'],
 ['stale-approval','stale','Source changed after approval'],
 ['unsupported-workbook','template','Unsupported workbook feature'],
] as const;
async function openStory(page:Page,id:string){await page.goto(storyOrigin+'/iframe.html?id='+id+'&viewMode=story');await expect(page.locator('#storybook-root')).not.toBeEmpty();await expect(page.locator('#storybook-root main')).toBeVisible();}
async function accessibility(page:Page){await page.addScriptTag({path:axePath});const violations=await page.evaluate(async()=>{const axe=(window as unknown as {axe:{run:(context:Element,options:unknown)=>Promise<{violations:unknown[]}>}}).axe;return (await axe.run(document.querySelector('#storybook-root')!,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}})).violations;});expect(violations).toEqual([]);}
for(const [id,value,name] of scenarios){
 test(name+' exposes separate state and accessible pages',async({page})=>{
  await openStory(page,'closegraph-workflows--'+id);
  await expect(page.getByRole('combobox',{name:'Scenario'})).toHaveValue(value);
  for(const name of ['Overview','Correction','Checks','Approval']){
   await page.getByRole('link',{name,exact:true}).click();
   await expect(page.getByRole('link',{name,exact:true})).toHaveAttribute('aria-current','page');
   await accessibility(page);
  }
  if(value!=='ready'){
   const approve=page.getByRole('button',{name:/^Approve version/});
   if(await approve.count())await expect(approve).toBeDisabled();
  }
 });
}
test('complete synthetic failed correction, repair and separate independent approval',async({page})=>{
 await openStory(page,'closegraph-workflows--fee-correction');
 await page.getByRole('link',{name:'Correction',exact:true}).click();
 await page.getByRole('button',{name:'Save correction'}).click();
 await expect(page.getByRole('textbox',{name:'Corrected amount (USD)'})).toBeFocused();
 await page.getByRole('textbox',{name:'Corrected amount (USD)'}).fill('60000.00');
 await page.getByRole('textbox',{name:'Why are you changing it?'}).fill('Synthetic FT-002 supports 60000.00.');
 await page.getByRole('combobox',{name:'Supporting source'}).selectOption('rule');
 await page.getByRole('button',{name:'Save correction'}).click();
 await expect(page.locator('.page-head .version').filter({hasText:'Version 3'})).toBeVisible();
 await expect(page.getByText('× Failed',{exact:true})).toBeVisible();
 await page.getByRole('button',{name:'Update capital statement'}).click();
 await expect(page.locator('.page-head .version').filter({hasText:'Version 4'})).toBeVisible();
 await page.getByRole('combobox',{name:'Person using the example'}).selectOption('reviewer');
 await page.getByRole('link',{name:'Approval',exact:true}).click();
 await expect(page.getByRole('button',{name:'Approve version 4'})).toBeDisabled();
 await page.getByRole('textbox',{name:'Review note'}).fill('Reviewed the synthetic source, revised workbook and all required checks.');
 await page.getByRole('checkbox').check();
 await page.getByRole('button',{name:'Approve version 4'}).click();
 await expect(page.getByRole('button',{name:'Preview export contents'})).toBeEnabled();
 await page.getByRole('button',{name:'Version and review history'}).click();
 await expect(page.getByText('Correction saved by Jamie Park',{exact:false})).toBeVisible();
 await accessibility(page);
});
test('reader resolution remains separate from approval and retains both readings',async({page})=>{
 await openStory(page,'closegraph-workflows--reader-disagreement');
 await page.getByRole('textbox',{name:'Evidence and reason for accepting the reading'}).fill('FT-002 and Capital!B4 support reader A.');
 await page.getByRole('combobox',{name:'Resolution evidence'}).selectOption('rule');
 await page.getByRole('button',{name:'Record review resolution'}).click();
 await expect(page.getByText('Evidence-backed resolution recorded')).toBeVisible();
 await page.getByRole('link',{name:'Approval',exact:true}).click();
 await expect(page.getByRole('button',{name:'Approve version 4'})).toBeDisabled();
 await page.getByRole('link',{name:'Correction',exact:true}).click();
 await page.getByRole('button',{name:'Source and extraction details'}).click();
 await expect(page.getByText('Reader A (synthetic replay)',{exact:false})).toBeVisible();
 await expect(page.getByText('Reader B (synthetic replay)',{exact:false})).toBeVisible();
});
test('shared primitives keyboard, focus, multiple-open accordion and dialog',async({page})=>{
 await openStory(page,'closegraph-components-catalogue--all-states');
 await accessibility(page);
 await page.getByRole('tab',{name:'Fee rule',exact:true}).focus();
 await page.keyboard.press('End');await expect(page.getByRole('tab',{name:'Original pack',exact:true})).toBeFocused();
 await page.keyboard.press('Home');await expect(page.getByRole('tab',{name:'Fee rule',exact:true})).toBeFocused();
 const trigger=page.getByRole('button',{name:'Open evidence dialog'});await trigger.click();
 await expect(page.getByRole('dialog',{name:'Source evidence'})).toBeVisible();
 await page.keyboard.press('Escape');await expect(trigger).toBeFocused();
 await page.getByText('unchecked: I inspected version 4 and its supporting evidence.').click();
 await expect(page.locator('#checkbox-unchecked')).toBeChecked();
});
test('200% equivalent reflow and narrow viewport keep navigation and actions reachable',async({page})=>{
 await page.setViewportSize({width:640,height:540});
 await openStory(page,'closegraph-workflows--ready-for-review');
 await page.getByRole('link',{name:'Approval',exact:true}).click();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await accessibility(page);
 await page.setViewportSize({width:390,height:844});
 for(const name of ['Overview','Correction','Checks','Approval']){
  await page.getByRole('link',{name,exact:true}).click();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 }
 await page.screenshot({path:'test-results/narrow-approval.png',fullPage:true});
});

test('PDF citation renders original page, visible bounding box and accessible source text',async({page})=>{
 await openStory(page,'closegraph-evidence-pdf-original-page--cited-original-page');
 await expect(page.getByText('Loading the cited original page…')).toHaveCount(0);
 await expect(page.locator('.pdf-highlight')).toBeVisible();
 await expect(page.locator('canvas')).toHaveAttribute('height',/^[1-9]\d+/);
 await page.getByText('Read original page text',{exact:true}).click();
 await expect(page.getByText('Synthetic fee evidence: 60,000.00',{exact:true})).toBeVisible();
 await expect(page.getByText('Synthetic cover page - not the citation',{exact:true})).toHaveCount(0);
 await accessibility(page);
 await page.screenshot({path:'test-results/pdf-original-citation.png',fullPage:true});
});
