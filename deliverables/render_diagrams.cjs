const fs=require('fs');
const path=require('path');
const vizModule = require('@viz-js/viz');
const {instance}=vizModule;
(async()=>{
 const viz=await instance();
 const dir=path.join(__dirname,'architecture');
 for(const file of fs.readdirSync(dir).filter(x=>x.endsWith('.dot'))){
  const svg=viz.renderString(fs.readFileSync(path.join(dir,file),'utf8'),{format:'svg',engine:'dot'});
  fs.writeFileSync(path.join(dir,file.replace(/\.dot$/,'.svg')),svg);
  console.log(file+' -> SVG');
 }
})().catch(e=>{console.error(e);process.exitCode=1});
