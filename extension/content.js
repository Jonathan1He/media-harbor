(() => {
  const current=new Map(), observed=new WeakMap();
  let previousPage="",timer=0;
  const http=v=>/^https?:\/\//i.test(v||"");
  function isSite(){
    return /(^|\.)bilibili\.com$/.test(location.hostname) && /^\/video\//.test(location.pathname) ||
      /(^|\.)youtube\.com$/.test(location.hostname) && (location.pathname==="/watch" || location.pathname.startsWith("/shorts/"));
  }
  function create(el) {
    const box=document.createElement("div");
    box.style.cssText="position:fixed;z-index:2147483646;pointer-events:none;display:none";
    const shadow=box.attachShadow({mode:"closed"});
    const button=document.createElement("button");
    button.textContent="↓ 下载"+(el.tagName==="AUDIO"?"音频":"视频");
    button.style.cssText="pointer-events:auto;cursor:pointer;border:1px solid #57948d;border-radius:6px;background:#124b48;color:white;padding:6px 10px;font:600 13px system-ui;box-shadow:0 2px 5px #0003";
    button.title="保存到拾流 · 默认最高 1080p";
    let previewUrl="",preview,preferred="auto";
    function quality(){
      const current=location.href;
      if(current===previewUrl && preview)return preview;
      previewUrl=current;
      preferred="auto";
      preview=chrome.runtime.sendMessage({op:"inspect",documentPage:current,source:""}).then(result=>{
        if(result.error)throw Error(result.error);
        if(current===location.href){
          const chosen=result.info.choices.find(x=>x.height<=1080);
          preferred=chosen?"id:"+chosen.id:"auto";
          button.textContent="↓ "+result.info.default;
          button.title=result.info.title+" · "+result.info.default;
        }
        return result.info;
      }).catch(err=>{preview=null;throw err;});
      return preview;
    }
    for(const event of ["pointerenter","focus"])button.addEventListener(event,()=>{
      if(isSite() && !button.disabled)quality().catch(()=>{});
    });
    button.addEventListener("click",async e=>{
      if(!e.isTrusted)return;
      e.stopPropagation();button.disabled=true;
      const activeUrl=location.href;
      try {
        const choice=isSite() && activeUrl===previewUrl?preferred:"auto";
        const media=http(el.currentSrc)?el.currentSrc:"";
        if(!isSite() && media) await chrome.runtime.sendMessage({op:"seen",items:[{source:media,kind:el.tagName.toLowerCase()}]});
        const r=await chrome.runtime.sendMessage({op:"enqueue",documentPage:activeUrl,source:isSite()?"":media,choice});
        if(r.error)throw Error(r.error);
        button.textContent=r.pending?"请在拾流确认":"✓ 已加入队列";
      } catch(ex){button.textContent="请查看资源列表";button.title=ex.message;}
      finally {setTimeout(()=>{button.disabled=false;button.textContent="↓ 下载"+(el.tagName==="AUDIO"?"音频":"视频");},1800);}
    });
    shadow.append(button);document.documentElement.append(box);
    return box;
  }
  function position(){
    for(const [el,box] of current) {
      if(!el.isConnected){box.remove();current.delete(el);continue;}
      const r=el.getBoundingClientRect();
      const visible=r.width>=150 && r.height>=22 && r.bottom>0 && r.top<innerHeight && r.right>0 && r.left<innerWidth;
      box.style.display=visible?"block":"none";
      if(visible) {box.style.left=Math.max(0,Math.min(innerWidth-95,r.right-98))+"px";box.style.top=Math.max(0,r.top+5)+"px";}
    }
  }
  let scanning=false;
  function scan(){
    if(scanning)return;
    scanning=true;
    try {
      const changed=location.href!==previousPage;
      previousPage=location.href;
      const items=[];
      for(const el of document.querySelectorAll("video,audio,img")){
        const kind=el.tagName==="IMG"?"image":el.tagName.toLowerCase();
        const src=el.currentSrc || el.src;
        const width=el.naturalWidth || el.videoWidth || 0, height=el.naturalHeight || el.videoHeight || 0;
        if(http(src) && (changed || observed.get(el)!==src+"|"+width+"|"+height)){
          observed.set(el,src+"|"+width+"|"+height);items.push({source:src,kind,width,height});
        }
        if(kind!=="image" && !current.has(el))current.set(el,create(el));
      }
      for(let i=0;i<items.length;i+=100)chrome.runtime.sendMessage({op:"seen",items:items.slice(i,i+100)}).catch(()=>{});
      position();
    } finally {scanning=false;}
  }
  function schedule(){if(!timer)timer=setTimeout(()=>{timer=0;scan();},150);}
  new MutationObserver(schedule).observe(document.documentElement,{childList:true,subtree:true,attributes:true,attributeFilter:["src","srcset","poster"]});
  addEventListener("scroll",position,{capture:true,passive:true});addEventListener("resize",position);
  document.addEventListener("load",schedule,true);document.addEventListener("loadedmetadata",schedule,true);
  addEventListener("popstate",schedule);document.addEventListener("yt-navigate-finish",schedule);
  scan();
})();

