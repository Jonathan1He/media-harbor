const $=id=>document.getElementById(id);
const send=async m=>{const r=await chrome.runtime.sendMessage(m);if(r?.error)throw Error(r.error);return r;};
let state={list:[]},mode="media";
function report(text){$("status").textContent=text;}
function submitted(result){report(result.pending?"请在拾流窗口确认保存位置":"已加入桌面队列");}
function action(id,fn){$(id).onclick=async()=>{const b=$(id);b.disabled=true;try{await fn();}catch(e){report(e.message);}finally{b.disabled=false;}};}
async function load(){
  state=await send({op:"list"});$("platform").hidden=!state.site;$("title").textContent=state.title || "";
  render();
}
function render(){
  $("mediaTab").setAttribute("aria-pressed",String(mode==="media"));$("imageTab").setAttribute("aria-pressed",String(mode==="image"));
  const rows=state.list.filter(x=>(x.kind==="image")===(mode==="image"));
  const list=$("items");list.replaceChildren();$("batch").hidden=mode!=="image" || !rows.length;$("all").checked=false;
  if(!rows.length){list.textContent=mode==="image"?"尚未发现图片。":"尚未发现影音，可先播放再刷新。";return;}
  for(const r of rows){
    const line=document.createElement("div");line.className="asset";
    const label=document.createElement("span");
    const u=new URL(r.source);label.textContent=(u.pathname.split("/").pop() || u.host).slice(0,80);
    const sub=document.createElement("small");sub.textContent=r.width? r.width+" × "+r.height : (r.mime || u.host);label.append(sub);
    if(mode==="image"){
      const cb=document.createElement("input");cb.type="checkbox";cb.value=r.source;cb.setAttribute("aria-label",label.textContent);
      const img=document.createElement("img");img.src=r.source;img.alt="";img.loading="lazy";img.referrerPolicy="no-referrer";
      line.append(cb,img,label);
    }else{
      const b=document.createElement("button");b.textContent="下载";
      b.onclick=async()=>{b.disabled=true;try{submitted(await send({op:"enqueue",source:r.source}));}catch(e){report(e.message);}finally{b.disabled=false;}};
      line.append(label,b);
    }
    list.append(line);
  }
}
action("inspect",async()=>{report("正在解析…");const {info}=await send({op:"inspect"});$("quality").replaceChildren(new Option("自动 · "+info.default,"auto"),...info.choices.map(x=>new Option(x.label,"id:"+x.id)));report(info.title);});
for(const [id,op] of [["download","enqueue"],["audio","enqueue"],["session","session"]])action(id,async()=>{submitted(await send({op,choice:id==="audio"?"audio":id==="session"?"auto":$("quality").value}));});
action("refresh",load);action("imageTab",()=>{mode="image";render();});action("mediaTab",()=>{mode="media";render();});
$("all").onchange=()=>document.querySelectorAll("#items input").forEach(c=>{c.checked=$("all").checked;});
action("save",async()=>{
  const boxes=[...document.querySelectorAll("#items input:checked")];
  if(!boxes.length){report("请先选择图片");return;}
  submitted(await send({op:"enqueueImages",sources:boxes.map(b=>b.value)}));
  for(const box of boxes)box.checked=false;
  $("all").checked=false;
});
load().catch(e=>report(e.message));

