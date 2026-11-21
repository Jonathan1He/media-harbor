/* Use disposable profiles and a local fixture. Never attach to a user's browser. */
const path=require("node:path"), fs=require("node:fs"), http=require("node:http");
const {chromium}=require(process.env.PLAYWRIGHT_DIR || "playwright");
const [exe, dir]=process.argv.slice(2);
const ext=path.resolve(__dirname,"../extension");
const manual=process.argv.includes("--manual");
(async()=>{
  const srv=http.createServer((req,res)=>{
    if(req.url==="/media.png"){
      res.setHeader("content-type","image/png");
      res.end(Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+hGXYAAAAASUVORK5CYII=","base64"));return;
    }
    if(req.url==="/video.mp4"){res.setHeader("content-type","video/mp4");res.end();return;}
    res.setHeader("content-type","text/html");
    res.end('<title>拾流测试页</title><video controls width="480" height="270" src="/video.mp4"></video><img src="/media.png">');
  });
  await new Promise(r=>srv.listen(0,"127.0.0.1",r));
  let ctx;
  try {
    fs.mkdirSync(dir,{recursive:true});
    ctx=await chromium.launchPersistentContext(fs.mkdtempSync(path.join(dir,"qa-")),{executablePath:exe,headless:!manual,
      chromiumSandbox:true,ignoreDefaultArgs:["--disable-extensions"],
      args:["--enable-unsafe-extension-debugging","--disable-extensions-except="+ext,"--load-extension="+ext]});
    const page=ctx.pages()[0];const cdp=await ctx.newCDPSession(page);
    if(manual)await page.goto("chrome://extensions/");
    if(!manual && !ctx.serviceWorkers().length){
      try{await cdp.send("Extensions.loadUnpacked",{path:ext});}
      catch(e){console.log("CDP install:",e.message);}
    }
    const sw=ctx.serviceWorkers()[0] || await ctx.waitForEvent("serviceworker",{timeout:manual?480000:12000});
    const origin="http://127.0.0.1:"+srv.address().port;
    await page.goto(origin);
    await page.waitForTimeout(900);
    const assets=await sw.evaluate(async()=>{
      const t=(await chrome.tabs.query({active:true,currentWindow:true}))[0];
      return (await chrome.storage.session.get("tab-"+t.id))["tab-"+t.id] || [];
    });
    if(!assets.some(x=>x.kind==="image" && x.width===1) || !assets.some(x=>x.kind==="video"))throw Error("媒体识别未通过："+JSON.stringify(assets));
    const overlays=await page.locator("div[style*='2147483646']").count();
    if(!overlays)throw Error("播放器按钮未出现");
    const identity=await sw.evaluate(()=>[siteLink("https://www.bilibili.com/video/BV123?p=2"),siteLink("https://www.youtube.com/watch?v=one")]);
    if(!identity.every(Boolean))throw Error("站点识别失败");
    console.log("PASS",path.basename(exe),sw.url(),"media",assets.length,"overlay",overlays);
    // Fixture transport isolates SPA target selection. Real native framing is checked separately.
    await sw.evaluate(()=>{
      globalThis.testMessages=[];
      chrome.runtime.sendNativeMessage=async (_host,msg)=>{
        testMessages.push({op:msg.op,source:msg.items?.[0].source,choice:msg.items?.[0].choice});
        return msg.op==="inspect"?{error:"HTTP 412"}:{ok:true,pending:true};
      };
    });
    const fixture='<title>QA</title><video controls width="480" height="270"></video>';
    for(const [start,next] of [["https://www.bilibili.com/video/BV123/?p=1","/video/BV123/?p=2"],["https://www.youtube.com/watch?v=first","/watch?v=second"]]){
      await ctx.route(start,route=>route.fulfill({contentType:"text/html",body:fixture}));
      await page.goto(start);
      await page.evaluate(p=>{history.pushState(null,"",p);window.dispatchEvent(new PopStateEvent("popstate"));},next);
      const overlay=page.locator("div[style*='2147483646']").first();
      await overlay.waitFor({state:"visible"});
      const box=await overlay.boundingBox();
      await page.mouse.click(box.x+box.width/2,box.y+box.height/2);
      for(let i=0;i<25;i++){
        const last=await sw.evaluate(()=>testMessages.filter(x=>x.op==="offer").at(-1));
        if(last?.source===new URL(next,start).href && last.choice==="auto")break;
        if(i===24)throw Error("SPA 下载目标错误 "+JSON.stringify(last));
        await page.waitForTimeout(100);
      }
      console.log("PASS SPA",new URL(next,start).href);
    }
  } finally {if(ctx)await ctx.close();srv.close();}
})().catch(e=>{console.error(e.message);process.exitCode=1;});

