import {act,fireEvent,render,screen,cleanup} from '@testing-library/react';
import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import {BatmanPet,BATMAN_VISIT_MS,BATMAN_VISIT_DURATION_MS} from './Batman';
import {Loading} from '../../features/reconciliation/Loading';
beforeEach(()=>{vi.useFakeTimers();const saved=new Map<string,string>();vi.stubGlobal('localStorage',{getItem:(key:string)=>saved.get(key)??null,setItem:(key:string,value:string)=>saved.set(key,value)});vi.spyOn(Math,'random').mockReturnValue(0);Object.defineProperty(document,'visibilityState',{configurable:true,value:'visible'});vi.stubGlobal('matchMedia',()=>({matches:false,addEventListener:vi.fn(),removeEventListener:vi.fn()}));});
afterEach(()=>{cleanup();vi.useRealTimers();vi.restoreAllMocks();vi.unstubAllGlobals();});
function advance(ms:number){act(()=>vi.advanceTimersByTime(ms));}
describe('Batman visits',()=>{
 it('waits one minute, shows only four movements in a repeating cycle, then leaves',()=>{
  render(<BatmanPet/>);expect(screen.queryByTestId('batman-visit')).toBeNull();advance(BATMAN_VISIT_MS-1);expect(screen.queryByTestId('batman-visit')).toBeNull();advance(1);
  for(const move of ['run','flip','glide','grapple','run']){expect(screen.getByTestId('batman-visit')).toHaveAttribute('data-move',move);advance(BATMAN_VISIT_DURATION_MS);expect(screen.queryByTestId('batman-visit')).toBeNull();advance(BATMAN_VISIT_MS-BATMAN_VISIT_DURATION_MS);}
 });
 it('can be paused and remembers that preference',()=>{
  const view=render(<BatmanPet/>);advance(BATMAN_VISIT_MS);fireEvent.click(screen.getByRole('button',{name:'Pause Batman visits'}));expect(screen.queryByTestId('batman-visit')).toBeNull();view.unmount();render(<BatmanPet/>);advance(BATMAN_VISIT_MS*2);expect(screen.queryByTestId('batman-visit')).toBeNull();fireEvent.click(screen.getByRole('button',{name:'Resume Batman visits'}));advance(BATMAN_VISIT_MS);expect(screen.getByTestId('batman-visit')).toBeVisible();
 });
 it('pauses hidden tabs and starts a fresh minute on return',()=>{
  render(<BatmanPet/>);advance(30_000);Object.defineProperty(document,'visibilityState',{configurable:true,value:'hidden'});fireEvent(document,new Event('visibilitychange'));advance(BATMAN_VISIT_MS*5);expect(screen.queryByTestId('batman-visit')).toBeNull();Object.defineProperty(document,'visibilityState',{configurable:true,value:'visible'});fireEvent(document,new Event('visibilitychange'));advance(BATMAN_VISIT_MS-1);expect(screen.queryByTestId('batman-visit')).toBeNull();advance(1);expect(screen.getByTestId('batman-visit')).toBeVisible();
 });
 it('does not schedule visits under reduced motion and retains readable processing status',()=>{
  vi.stubGlobal('matchMedia',()=>({matches:true,addEventListener:vi.fn(),removeEventListener:vi.fn()}));render(<><BatmanPet/><Loading text="Reading 1 of 2 documents"/></>);advance(BATMAN_VISIT_MS*3);expect(screen.queryByTestId('batman-visit')).toBeNull();expect(screen.queryByRole('button')).toBeNull();expect(screen.getByRole('status')).toHaveTextContent('Reading 1 of 2 documents');
 });
});
