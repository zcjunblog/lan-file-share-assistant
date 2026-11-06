// Opt-in synthetic-only UI check. Run while tools/m2_e2e.py start180 is active.
const fs = require('fs');
const {chromium}=require('playwright');
(async()=>{
 const active=JSON.parse(fs.readFileSync('outputs/m2/active.json','utf8'));
 const browser=await chromium.launch({channel:'chrome',headless:true});
 const results=[];
 for(const [name,width,height] of [['desktop',1280,1000],['mobile',390,844]]){
   const page=await browser.newPage({viewport:{width,height},deviceScaleFactor:1});
   const errors=[];page.on('pageerror',e=>errors.push(e.name));
   await page.goto(active.url,{waitUntil:'networkidle'});
   const shape=await page.evaluate(()=>({overflow:document.documentElement.scrollWidth>innerWidth,fileCount:document.querySelectorAll('.file').length,buttons:document.querySelectorAll('a.download[href]').length,timer:document.getElementById('timer').textContent}));
   if(shape.overflow||shape.fileCount!==5||shape.buttons!==5||errors.length)throw Error('UI validation failed');
   await page.screenshot({path:`evidence/m2/download-${name}.png`,fullPage:true});
   results.push({viewport:name,width,horizontalOverflow:false,visibleFiles:shape.fileCount,downloadLinks:shape.buttons,javascriptErrors:errors.length});
   await page.close();
 }
 const expired=await browser.newPage({viewport:{width:390,height:844}});
 await expired.clock.install({time:new Date(Date.now()+600000)});
 await expired.goto(active.url,{waitUntil:'networkidle'});
 const expiredState=await expired.evaluate(()=>({links:document.querySelectorAll('a.download[href]').length,disabled:document.querySelectorAll('a.download[aria-disabled="true"]').length,timer:document.getElementById('timer').textContent}));
 if(expiredState.links!==0||expiredState.disabled!==5||expiredState.timer!=='分享已到期')throw Error('Expired state failed');
 await expired.screenshot({path:'evidence/m2/download-expired-mobile.png',fullPage:true});
 await browser.close();
 fs.writeFileSync('evidence/m2/ui-checks.json',JSON.stringify({browser:'Independent headless Chrome',liveLocalPage:true,viewports:results,expiredClientState:{clockSimulated:true,linksDisabled:5},phoneTested:false},null,2)+'\n');
 console.log(JSON.stringify({desktopAndMobilePassed:true,expiredClientStatePassed:true}));
})().catch(e=>{console.error(e.name+': '+e.message.replace(/http:\/\/[^ ]+/g,'[private URL]'));process.exit(1)});
