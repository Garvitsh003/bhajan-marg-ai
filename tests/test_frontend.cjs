const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const elements = {};
for (const id of ['chat','form','q','ask','new-chat','status']) elements[id] = {
  value:'', textContent:'', disabled:false, children:[], handlers:{}, html:'',
  addEventListener(k,f){this.handlers[k]=f}, appendChild(x){this.children.push(x)},
  replaceChildren(){this.children=[]}, focus(){}, insertAdjacentHTML(_,x){this.html+=x}
};
let resolveFetch;
const sandbox = {console, URL, AbortController, setTimeout, clearTimeout,
  window:{BHAJAN_API_BASE:'https://example.test',scrollTo(){}},
  document:{body:{scrollHeight:0}, getElementById:id=>elements[id], createElement:()=>({
    classList:{add(){}},textContent:'',get innerHTML(){return this.textContent.replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;')}
  })}, localStorage:{getItem(){throw Error('blocked')},setItem(){throw Error('blocked')},removeItem(){throw Error('blocked')}},
  fetch:()=>new Promise(r=>{resolveFetch=r})};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('web/app.js','utf8'),sandbox);
(async()=>{
  elements.q.value='भगवान पर विश्वास कैसे बढ़ाएं?';
  const pending=elements.form.handlers.submit({preventDefault(){}});
  assert.equal(elements.ask.disabled,true);
  await elements.form.handlers.submit({preventDefault(){}});
  assert.equal(elements.chat.children.length,1);
  resolveFetch({ok:false,status:503,headers:{get:()=>null},json:async()=>({error:{message:'Retry',request_id:'trace-1'}})});
  await pending;
  assert.match(elements.q.value,/भगवान/);
  assert.match(elements.status.textContent,/trace-1/);
  assert.equal(elements.ask.disabled,false);
  const success=elements.form.handlers.submit({preventDefault(){}});
  resolveFetch({ok:true,json:async()=>({answer:'स्रोत देखें',conversation_id:'one',answer_status:'source_only',sources:[{url:'javascript:bad',title:'<bad>'}]})});
  await success;
  assert.match(elements.chat.html,/answer excerpt unavailable/);
  assert.ok(!elements.chat.html.includes('href="javascript:'));
  assert.ok(elements.chat.html.includes('&lt;bad>'));
  elements['new-chat'].handlers.click();
  assert.equal(elements.chat.children.length,0);
  assert.equal(elements.q.value,'');
  assert.equal(vm.runInContext('conversationId',sandbox),null);
  assert.equal(fs.readFileSync('web/app.js','utf8'),fs.readFileSync('app/static/app.js','utf8'));
  console.log('Frontend recovery, duplicate prevention, source safety, storage failure and new-chat checks passed');
})().catch(e=>{console.error(e);process.exitCode=1});
