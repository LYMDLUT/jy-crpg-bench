const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const html = fs.readFileSync(path.join(__dirname, 'index.html'), 'utf8');
const begin = html.indexOf('// Game keyboard routing.');
const end = html.indexOf('// End game keyboard routing.');
assert(begin >= 0 && end > begin);
const source = html.slice(begin, end);

function fixture() {
  const handlers={}, docHandlers={}, sent=[];
  let replay=false, slot=false, observer;
  const context={MAP:{ArrowRight:'right',Enter:'enter',' ':'space',Escape:'esc'},escSwallow:false,
    send:e=>sent.push({...e}),slotOpen:()=>slot,
    addEventListener:(name,fn)=>handlers[name]=fn,
    document:{hidden:false,getElementById:id=>({classList:{contains:()=>id==='vcr'?replay:slot}}),
      addEventListener:(name,fn)=>docHandlers[name]=fn},
    MutationObserver:class {constructor(fn){observer=fn;}observe(){}},
  };
  vm.runInNewContext(source,context);
  const target=(kind='canvas')=>({isContentEditable:kind==='editable',closest:()=>kind==='canvas'||kind==='game-button'?null:{}});
  function event(key,kind='canvas',extra={}) {return {key,target:target(kind),prevented:false,preventDefault(){this.prevented=true;},...extra};}
  return {handlers,docHandlers,sent,event,context,openReplay(){replay=true;observer();},openSlot(){slot=true;observer();}};
}

test('replay controls keep native arrow/space/enter behavior without game messages',()=>{
  const f=fixture();f.openReplay();
  for(const key of ['ArrowRight',' ','Enter']) {const e=f.event(key,'slider');f.handlers.keydown(e);f.handlers.keyup(e);assert.equal(e.prevented,false);}
  assert.deepEqual(f.sent,[]);
});
test('history buttons, links, form controls, and shortcuts do not reach the game',()=>{
  const f=fixture();
  for(const target of ['button','link','input','select','editable']) {const e=f.event('Enter',target);f.handlers.keydown(e);assert.equal(e.prevented,false);}
  f.handlers.keydown(f.event('c','canvas',{metaKey:true}));assert.deepEqual(f.sent,[]);
});
test('opening a replay or save modal releases a held key once',()=>{
  for(const open of ['openReplay','openSlot']) {const f=fixture();f.handlers.keydown(f.event('ArrowRight'));f[open]();f.handlers.keyup(f.event('ArrowRight','slider'));assert.deepEqual(f.sent,[{t:'key',k:'right',down:true},{t:'key',k:'right',down:false}]);}
});
test('game keys retain repeat suppression and release across focus changes',()=>{
  const f=fixture();f.handlers.keydown(f.event('ArrowRight'));f.handlers.keydown(f.event('ArrowRight'));f.docHandlers.focusin(f.event('Enter','input'));f.handlers.keyup(f.event('ArrowRight','input'));assert.equal(f.sent.length,2);assert.equal(f.sent[1].down,false);
});
test('window blur and hidden page release active game keys',()=>{
  const f=fixture();f.handlers.keydown(f.event('ArrowRight'));f.handlers.blur();f.handlers.keydown(f.event('Enter'));f.context.document.hidden=true;f.docHandlers.visibilitychange();assert.deepEqual(f.sent.map(e=>e.down),[true,false,true,false]);
});
