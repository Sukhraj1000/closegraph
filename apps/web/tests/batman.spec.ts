import {test,expect} from './fixtures';
test.use({trace:'off'});
test('four minute visits, readable login and reduced-motion fallback',async({page},info)=>{
 await page.addInitScript(()=>{Math.random=()=>0;localStorage.removeItem('closegraph.batman');});
 await page.clock.install();await page.goto('/');await expect(page.getByRole('heading',{name:'Sign in to CloseGraph'})).toBeVisible();
 for(const move of ['run','flip','glide','grapple']){
  await page.clock.fastForward(60_000);const pet=page.getByTestId('batman-visit');await expect(pet).toHaveAttribute('data-move',move);
  await pet.evaluate(el=>{for(const animation of el.getAnimations())animation.currentTime=2800;});
  await expect(pet).toHaveCSS('pointer-events','none');await page.getByLabel('Username',{exact:true}).fill('accountant');
  await page.screenshot({path:info.outputPath('batman-'+move+'.png')});
 }
 await page.getByRole('button',{name:'Pause Batman visits'}).click();await expect(page.getByTestId('batman-visit')).toHaveCount(0);
 await page.emulateMedia({reducedMotion:'reduce'});await expect(page.getByRole('button',{name:'Resume Batman visits'})).toHaveCount(0);
});
