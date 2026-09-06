import {test,expect} from './fixtures';
test.use({trace:'off'});
test('four business accounts preserve their actual access',async({page},info)=>{
 const roles=[['Accountant','accountant','ACCOUNTANT'],['Account manager','account_manager','ACCOUNT_MANAGER'],['Fund manager','fund_manager','FUND_MANAGER'],['Investor','investor','INVESTOR']];
 for(const [label,username,key] of roles){
  await page.goto('/');await expect(page.getByRole('heading',{name:'Sign in to CloseGraph'})).toBeVisible();
  if(key==='ACCOUNTANT')await page.screenshot({path:info.outputPath('business-account-login.png')});
  await expect(page.getByRole('group')).toHaveCount(0);
  await page.getByLabel('Username',{exact:true}).fill(username);
  await page.getByLabel('Password',{exact:true}).fill(process.env['CLOSEGRAPH_TEST_'+key+'_PASSWORD']!);
  await page.getByRole('button',{name:'Sign in',exact:true}).click();await expect(page.locator('.fr-identity')).toHaveText(label);
  const nav=page.getByRole('navigation',{name:'Main navigation'});
  if(['INVESTOR','FUND_MANAGER'].includes(key)){await expect(nav.getByRole('button',{name:'New review',exact:true})).toHaveCount(0);await expect(page.getByRole('heading',{name:'Requests',exact:true}).first()).toBeVisible();}
  await expect(page.locator('body')).not.toContainText(/\b(preparer|reviewer)\b/i);
  const session=await page.evaluate(async()=>await (await fetch('/api/session')).json());expect(session.actor.actor_id).toBe(username);
  await page.screenshot({path:info.outputPath(username+'-workspace.png'),fullPage:true});
  await page.getByRole('button',{name:'Sign out',exact:true}).click();
 }
 for(const [old,key] of [['preparer','ACCOUNTANT'],['reviewer','ACCOUNT_MANAGER']]){
  await page.getByLabel('Username',{exact:true}).fill(old);
  await page.getByLabel('Password',{exact:true}).fill(process.env['CLOSEGRAPH_TEST_'+key+'_PASSWORD']!);
  await page.getByRole('button',{name:'Sign in',exact:true}).click();
  await expect(page.getByRole('alert').first()).toBeVisible();
  await expect(page.getByRole('heading',{name:'Sign in to CloseGraph'})).toBeVisible();
 }
});
