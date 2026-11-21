const HOST = "app.mediaharbor.desktop";
const buckets = new Map();
const locks = new Map();
const bucket = id => "tab-" + id;
function transaction(id, fn) {
  const previous = locks.get(id) || Promise.resolve();
  const next = previous.catch(() => {}).then(async () => {
    const key = bucket(id);
    let entries = buckets.get(id);
    if (!entries) entries = (await chrome.storage.session.get(key))[key] || [];
    entries = fn(entries);
    buckets.set(id, entries);
    await chrome.storage.session.set({[key]:entries});
    await chrome.action.setBadgeText({tabId:id, text:entries.length ? String(entries.length) : ""}).catch(()=>{});
    return entries;
  });
  locks.set(id,next);
  next.finally(()=>{if (locks.get(id)===next) locks.delete(id);}).catch(()=>{});
  return next;
}
function safeUrl(raw) {
  try {const u=new URL(raw);return ["http:","https:"].includes(u.protocol) && !u.username && !u.password ? u.href : "";} catch {return "";}
}
function siteLink(raw) {
  const url = safeUrl(raw);
  if (!url) return false;
  const u = new URL(url);
  return ((u.hostname==="www.bilibili.com" || u.hostname==="m.bilibili.com") && /^\/video\/(BV\w+|av\d+)/i.test(u.pathname)) ||
         ((u.hostname==="www.youtube.com" || u.hostname==="m.youtube.com") && ((u.pathname==="/watch" && u.searchParams.has("v")) || /^\/shorts\/[\w-]+/.test(u.pathname)));
}
function classify(u, mime="", type="") {
  const path=new URL(u).pathname.toLowerCase();
  if (/(\.m3u8|\.mpd)$/.test(path) || /mpegurl|dash\+xml/i.test(mime)) return "stream";
  if (/\.(ts|m4s|cmfv|cmfa)$/.test(path) || /mp2t/i.test(mime)) return "";
  if (/^image\//.test(mime) || type==="image") return "image";
  if (/^audio\//.test(mime) || /\.(mp3|m4a|aac|flac|wav|ogg)$/.test(path)) return "audio";
  if (/^video\//.test(mime) || /\.(mp4|webm|mov|mkv)$/.test(path)) return "video";
  return "";
}
function add(id, items) {
  if (!items.length) return;
  return transaction(id, entries=>{
    const byUrl=new Map(entries.map(e=>[e.source,e]));
    for (const item of items) {
      if (!safeUrl(item.source)) continue;
      byUrl.set(item.source,{...byUrl.get(item.source),...item});
    }
    return [...byUrl.values()].slice(-350);
  });
}
chrome.webRequest.onHeadersReceived.addListener(d=>{
  if(d.tabId<0 || d.statusCode<200 || d.statusCode>=300 || !safeUrl(d.url))return;
  const mime=(d.responseHeaders || []).find(h=>h.name.toLowerCase()==="content-type")?.value?.split(";")[0] || "";
  const kind=classify(d.url,mime,d.type);
  if(kind) add(d.tabId,[{source:d.url,kind,mime,frame:d.frameId}])?.catch(()=>{});
},{urls:["http://*/*","https://*/*"]},["responseHeaders"]);
function clearPage(d){if (!d.frameId && d.tabId>=0) transaction(d.tabId,()=>[]).catch(()=>{});}
chrome.webNavigation.onCommitted.addListener(clearPage);
chrome.webNavigation.onHistoryStateUpdated.addListener(clearPage);
chrome.tabs.onRemoved.addListener(id=>{buckets.delete(id);chrome.storage.session.remove(bucket(id));});
function native(msg){
  return chrome.runtime.sendNativeMessage(HOST,msg).catch(()=>{
    throw Error("无法连接拾流。请安装 Windows 客户端并从安装目录加载扩展。");
  });
}
// Executed only on an explicit popup click, in the selected platform tab.
// The page uses its own session. Only playable track URLs cross the boundary.
async function playerTracks() {
  const u=new URL(location.href);
  const out=[];
  if (/(^|\.)bilibili\.com$/.test(u.hostname)) {
    const bvid=u.pathname.match(/\/video\/(BV\w+)/i)?.[1];
    if (!bvid) throw Error("请打开具体的 BV 播放页");
    const part=Number(u.searchParams.get("p") || 1);
    const read=async(path)=>{
      const r=await fetch(new URL(path,"https://api.bilibili.com"),{credentials:"include"});
      if (!r.ok) throw Error("官网返回 HTTP "+r.status);
      const payload=await r.json();
      if(payload.code!==0) throw Error("官网未提供此媒体："+(payload.message || payload.code));
      return payload.data;
    };
    const initial=window.__INITIAL_STATE__?.videoData;
    const original=new URL(performance.getEntriesByType("navigation")[0]?.name || u.href);
    const sameEntry=original.pathname===u.pathname && Number(original.searchParams.get("p") || 1)===part;
    const view=initial?.bvid===bvid && sameEntry ? initial : await read("/x/web-interface/view?bvid="+encodeURIComponent(bvid));
    const p=view.pages?.find(x=>x.page===part);
    if(!p) throw Error("当前分 P 已变更");
    const loaded=view===initial && window.__playinfo__?.data;
    const play=loaded && (loaded.dash || loaded.durl) ? loaded :
      await read("/x/player/playurl?"+new URLSearchParams({bvid,cid:p.cid,qn:127,fnval:4048,fourk:1}));
    if(location.href!==u.href) throw Error("页面已切换，请重试");
    for(const kind of ["video","audio"]) for(const f of play.dash?.[kind] || []) {
      const rate=String(f.frameRate || f.frame_rate || "0").split("/").map(Number);
      out.push({id:String(f.id),url:f.baseUrl || f.base_url,kind,height:f.height||0,fps:rate[0]/(rate[1]||1),ext:"mp4"});
    }
    for(const f of (play.durl?.length===1?play.durl:[]) || []) out.push({id:"direct",url:f.url,kind:"both",height:0});
    return {name:view.title+(view.pages.length>1?" · P"+part+" "+p.part:""),tracks:out};
  }
  const player=document.getElementById("movie_player");
  const info=player?.getPlayerResponse?.();
  const expected=u.searchParams.get("v") || u.pathname.split("/")[2];
  if(!info || info.videoDetails?.videoId!==expected) throw Error("请先让当前视频开始播放");
  for(const f of [...(info.streamingData?.formats||[]),...(info.streamingData?.adaptiveFormats||[])]) {
    if(!f.url || f.drmFamilies?.length) continue;
    out.push({id:String(f.itag),url:f.url,kind:f.mimeType.startsWith("audio/")?"audio":f.audioQuality?"both":"video",
              height:f.height||0,fps:f.fps||0,ext:f.mimeType.includes("webm")?"webm":"mp4"});
  }
  return {name:info.videoDetails.title,tracks:out};
}
async function handle(msg,sender) {
  const popup=sender.url===chrome.runtime.getURL("popup.html");
  const tab=popup?(await chrome.tabs.query({active:true,currentWindow:true}))[0]:sender.tab;
  if(!tab?.id || !safeUrl(tab.url))throw Error("请打开一个网页");
  const page=tab.url, frame=sender.frameId || 0;
  if(msg.op==="seen" && !popup) {
    const valid=(msg.items || []).slice(0,100).filter(i=>["image","video","audio"].includes(i.kind) && safeUrl(i.source))
      .map(i=>({source:i.source,kind:i.kind,width:Number(i.width)||0,height:Number(i.height)||0,frame}));
    await add(tab.id,valid);return {ok:true};
  }
  const list=await transaction(tab.id,x=>x);
  if(msg.op==="list" && popup)return {list,site:siteLink(page),page,title:tab.title};
  if(msg.op==="enqueueImages" && popup){
    const urls=new Set(msg.sources);
    const items=list.filter(e=>e.kind==="image" && urls.has(e.source)).map(e=>({
      ...e,page,name:new URL(e.source).pathname.split("/").pop() || tab.title,choice:"auto"
    }));
    if(!items.length || items.length!==urls.size)throw Error("图片清单已变化，请刷新后重新选择");
    return native({op:"offer",items});
  }
  if(!["enqueue","inspect","session"].includes(msg.op))throw Error("无效操作");
  const livePage=safeUrl(msg.documentPage);
  const sameOrigin=!popup && livePage && safeUrl(sender.url) && new URL(livePage).origin===new URL(sender.url).origin;
  const framePage=sameOrigin?livePage:(!popup && siteLink(sender.url)?sender.url:page);
  let item;
  if(siteLink(framePage) && (!msg.source || msg.source===framePage)){
    item={source:framePage,page:framePage,name:tab.title,kind:"page"};
  } else {
    item=list.find(e=>e.source===msg.source);
    if(!item && !popup && !msg.source){
      const candidates=list.filter(e=>e.kind!=="image" && e.frame===frame);
      if(candidates.length===1)item=candidates[0];
    }
    if(!item)throw Error("发现多个资源或地址尚未载入，请点工具栏「拾流」选择");
    item={...item,page,name:new URL(item.source).pathname.split("/").pop() || tab.title};
  }
  if(msg.op==="session"){
    if(!popup || !siteLink(page))throw Error("请在平台播放页点击此按钮");
    const result=await chrome.scripting.executeScript({target:{tabId:tab.id},world:"MAIN",func:playerTracks});
    const data=result[0]?.result;
    if(!data?.tracks?.length)throw Error("官网播放器未提供可直接保存的音视频地址");
    return native({op:"offer",items:[{...item,...data,choice:msg.choice || "auto"}]});
  }
  if(msg.op==="inspect")return native({...item,op:"inspect",passive:!popup});
  return native({op:"offer",items:[{...item,choice:msg.choice || "auto"}]});
}
chrome.runtime.onMessage.addListener((msg,sender,answer)=>{
  handle(msg,sender).then(answer).catch(e=>answer({error:e.message}));
  return true;
});

