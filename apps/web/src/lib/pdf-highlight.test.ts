import { describe,it,expect } from 'vitest';
import { pdfHighlight } from './pdf-highlight';
describe('original PDF citation projection',()=>{
 it('projects normalised top-left bounds on the original page',()=>{expect(pdfHighlight({bbox:[.1,.2,.3,.4],coordinate_system:'normalised-0-1'},[0,0,600,800],[1,0,0,-1,0,800],600,800)).toEqual({left:10,top:20,width:20,height:20});});
 it('accounts for bottom-left origin and rotated page',()=>{expect(pdfHighlight({bbox:[60,160,180,320],coordinate_system:'points-bottom-left'},[0,0,600,800],[0,1,1,0,0,0],800,600)).toEqual({left:20,top:10,width:20,height:20});});
 it('rejects guessed coordinate systems, inverted and out-of-page bounds',()=>{for(const locator of [{bbox:[0,0,1,1]}, {bbox:[.4,.1,.2,.3],coordinate_system:'normalised-0-1'}, {bbox:[0,0,700,10],coordinate_system:'points-top-left'}])expect(pdfHighlight(locator,[0,0,600,800],[1,0,0,-1,0,800],600,800)).toBeNull();});
});
