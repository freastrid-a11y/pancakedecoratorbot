const $ = s => document.querySelector(s);
const DPR = Math.min(window.devicePixelRatio || 1, 2);

const TOPPINGS = [
  {id:'blueberry',  name:'Blueberries',       emoji:'🫐', color:'#4f6bd8', mm:12, count:10, max:24},
  {id:'strawberry', name:'Strawberry slices', emoji:'🍓', color:'#e2384d', mm:24, count:6,  max:12},
  {id:'banana',     name:'Banana slices',     emoji:'🍌', color:'#d9b21f', mm:24, count:5,  max:12},
  {id:'chip',       name:'Chocolate chips',   emoji:'🍫', color:'#6b3e26', mm:8,  count:14, max:30},
  {id:'cherry',     name:'Cherries',          emoji:'🍒', color:'#b0123a', mm:18, count:3,  max:8},
];
const TBY = Object.fromEntries(TOPPINGS.map(t => [t.id, t]));

const S = {
  src:null, srcW:0, srcH:0, A:null, maskCanvas:null,
  spots:[], short:[], placed:new Set(),
  seed:7, style:'hug', mode:'photo', debug:false,
  diam:150, gap:4, thresh:55, demo:'heart',
  counts:{}, enabled:{}
};
TOPPINGS.forEach(t => { S.counts[t.id] = t.count; S.enabled[t.id] = (t.id === 'blueberry' || t.id === 'strawberry'); });

function mulberry32(a){return function(){a|=0;a=a+0x6D2B79F5|0;let t=Math.imul(a^a>>>15,1|a);t=t+Math.imul(t^t>>>7,61|t)^t;return((t^t>>>14)>>>0)/4294967296}}

/* ---------------- Demo pancakes (stand-in for the overhead camera) ---------------- */
const DEMOS = {
  heart:'Heart', smiley:'Smiley', star:'Star', letter:'Letter A', spiral:'Spiral', pink:'Pink sauce'
};
function makeDemo(kind){
  const c = document.createElement('canvas'); c.width = c.height = 600;
  const x = c.getContext('2d'); const rng = mulberry32(42);
  const g0 = x.createLinearGradient(0,0,600,600); g0.addColorStop(0,'#3b4651'); g0.addColorStop(1,'#283039');
  x.fillStyle = g0; x.fillRect(0,0,600,600);
  x.save(); x.shadowColor='rgba(0,0,0,.35)'; x.shadowBlur=25;
  x.fillStyle='#ebe8e1'; x.beginPath(); x.arc(300,300,284,0,Math.PI*2); x.fill(); x.restore();
  const PX=306, PY=294, PR=226;
  const g = x.createRadialGradient(PX-30,PY-30,20,PX,PY,PR);
  g.addColorStop(0,'#ebb860'); g.addColorStop(.8,'#d79a45'); g.addColorStop(1,'#bf7f33');
  x.fillStyle=g; x.beginPath(); x.arc(PX,PY,PR,0,Math.PI*2); x.fill();
  for(let i=0;i<320;i++){ // browning speckles
    const a=rng()*Math.PI*2, r=Math.sqrt(rng())*PR*.95;
    x.fillStyle=`rgba(${150+rng()*40|0},${90+rng()*30|0},30,${.08+rng()*.12})`;
    x.beginPath(); x.arc(PX+Math.cos(a)*r, PY+Math.sin(a)*r, 2+rng()*7, 0, Math.PI*2); x.fill();
  }
  x.save(); x.translate(PX,PY);
  const sauce = kind==='pink' ? '#c2185b' : '#3a1d10';
  x.strokeStyle = x.fillStyle = sauce; x.lineWidth=15; x.lineCap='round'; x.lineJoin='round';
  const path = () => {
    x.beginPath();
    if(kind==='heart'){ x.moveTo(0,70); x.bezierCurveTo(-130,-10,-70,-125,0,-55); x.bezierCurveTo(70,-125,130,-10,0,70); }
    else if(kind==='smiley' || kind==='pink'){ x.arc(0,0,92,0,Math.PI*2); x.moveTo(43,14); x.arc(0,14,43,0.12*Math.PI,0.88*Math.PI); }
    else if(kind==='star'){ for(let i=0;i<=10;i++){const r=i%2?42:100,a=-Math.PI/2+i*Math.PI/5; x.lineTo(Math.cos(a)*r,Math.sin(a)*r);} }
    else if(kind==='spiral'){ for(let t=0;t<4.6*Math.PI;t+=.05){const r=6+10.5*t; x.lineTo(Math.cos(t)*r,Math.sin(t)*r);} }
  };
  if(kind==='letter'){ x.font='bold 230px Arial, sans-serif'; x.textAlign='center'; x.textBaseline='middle'; x.fillText('A',0,14); }
  else { path(); x.stroke(); if(kind==='smiley'||kind==='pink'){ x.beginPath(); x.arc(-34,-28,11,0,7); x.arc(34,-28,11,0,7); x.fill(); } }
  // glossy highlight on the sauce
  x.translate(-3,-3); x.strokeStyle='rgba(255,225,200,.22)'; x.lineWidth=3;
  if(kind!=='letter'){ path(); x.stroke(); }
  x.restore();
  return c;
}

/* ---------------- Vision: find pancake + syrup ---------------- */
function analyze(src, W, H, T){
  const sc = Math.min(1, 260/Math.max(W,H));
  const w = Math.max(1, Math.round(W*sc)), h = Math.max(1, Math.round(H*sc));
  const c = document.createElement('canvas'); c.width=w; c.height=h;
  const cx2 = c.getContext('2d', {willReadFrequently:true}); cx2.drawImage(src,0,0,w,h);
  const d = cx2.getImageData(0,0,w,h).data; const N=w*h;

  // 1. pancake-colored pixels (golden brown)
  const cand = new Uint8Array(N); let sx=0, sy=0, cnt=0;
  for(let i=0;i<N;i++){
    const r=d[i*4], g=d[i*4+1], b=d[i*4+2];
    const mx=Math.max(r,g,b), mn=Math.min(r,g,b), dl=mx-mn;
    const v=mx/255, s=mx?dl/mx:0; let hu=0;
    if(dl){ if(mx===r) hu=60*(((g-b)/dl)%6); else if(mx===g) hu=60*((b-r)/dl+2); else hu=60*((r-g)/dl+4); if(hu<0) hu+=360; }
    if(hu>=12 && hu<=55 && s>=.22 && v>=.40){ cand[i]=1; sx+=i%w; sy+=(i/w)|0; cnt++; }
  }
  // 2. fit a circle
  let cx, cy, rad; const found = cnt > N*0.03;
  if(found){
    cx=sx/cnt; cy=sy/cnt; rad=Math.max(w,h);
    for(let it=0; it<3; it++){
      const ds=[]; let nx=0, ny=0, nc=0;
      for(let i=0;i<N;i++) if(cand[i]){ const x=i%w, y=(i/w)|0, dd=Math.hypot(x-cx,y-cy); if(dd<rad*1.05){ ds.push(dd); nx+=x; ny+=y; nc++; } }
      if(!nc) break;
      ds.sort((a,b)=>a-b); rad=ds[Math.floor(ds.length*.97)]; cx=nx/nc; cy=ny/nc;
    }
  } else { cx=w/2; cy=h/2; rad=.45*Math.min(w,h); }

  // 3. typical pancake color (median)
  const hist=[new Uint32Array(256),new Uint32Array(256),new Uint32Array(256)]; let hc=0;
  for(let i=0;i<N;i++){ const x=i%w, y=(i/w)|0; if((found?cand[i]:1) && Math.hypot(x-cx,y-cy)<rad*.85){ hist[0][d[i*4]]++; hist[1][d[i*4+1]]++; hist[2][d[i*4+2]]++; hc++; } }
  const pc = hist.map(hh => { let acc=0; for(let k=0;k<256;k++){ acc+=hh[k]; if(acc>=hc/2) return k; } return 128; });

  // 4. syrup = clearly different color, inside the pancake
  let mask = new Uint8Array(N);
  for(let i=0;i<N;i++){
    const x=i%w, y=(i/w)|0; if(Math.hypot(x-cx,y-cy) > rad*.96) continue;
    const dr=d[i*4]-pc[0], dg=d[i*4+1]-pc[1], db=d[i*4+2]-pc[2];
    if(Math.sqrt(2*dr*dr+4*dg*dg+3*db*db)/3 > T) mask[i]=1;
  }
  mask = morph(morph(mask,w,h,'erode'),w,h,'dilate');      // remove specks
  mask = dropSmall(mask, w, h, Math.max(6, .002*Math.PI*rad*rad));
  let syrupPx=0; for(let i=0;i<N;i++) syrupPx+=mask[i];

  return {w,h,scale:sc,cx,cy,rad,mask,dist:chamfer(mask,w,h),found,syrupPx,
          syrupFrac: syrupPx/(Math.PI*(rad*.96)**2), pc};
}
function morph(m,w,h,op){
  const o=new Uint8Array(w*h), er=op==='erode';
  for(let y=0;y<h;y++) for(let x=0;x<w;x++){
    let v=er?1:0;
    for(let dy=-1;dy<=1&&(er?v:!v);dy++) for(let dx=-1;dx<=1;dx++){
      const X=x+dx, Y=y+dy; const s=(X<0||Y<0||X>=w||Y>=h)?0:m[Y*w+X];
      if(er && !s){v=0;break} if(!er && s){v=1;break}
    }
    o[y*w+x]=v;
  }
  return o;
}
function dropSmall(m,w,h,minA){
  const seen=new Uint8Array(w*h), out=new Uint8Array(w*h), st=new Int32Array(w*h);
  for(let i=0;i<w*h;i++){
    if(!m[i]||seen[i]) continue;
    let sp=0, comp=[]; st[sp++]=i; seen[i]=1;
    while(sp){ const j=st[--sp]; comp.push(j); const x=j%w, y=(j/w)|0;
      for(const [dx,dy] of [[1,0],[-1,0],[0,1],[0,-1]]){ const X=x+dx,Y=y+dy; if(X<0||Y<0||X>=w||Y>=h) continue; const k=Y*w+X; if(m[k]&&!seen[k]){seen[k]=1; st[sp++]=k;} } }
    if(comp.length>=minA) for(const j of comp) out[j]=1;
  }
  return out;
}
function chamfer(m,w,h){ // distance (px) to nearest syrup pixel
  const INF=1e9, D=new Float32Array(w*h);
  for(let i=0;i<w*h;i++) D[i]=m[i]?0:INF;
  for(let y=0;y<h;y++) for(let x=0;x<w;x++){ const i=y*w+x; let v=D[i];
    if(x>0) v=Math.min(v,D[i-1]+3);
    if(y>0){ v=Math.min(v,D[i-w]+3); if(x>0) v=Math.min(v,D[i-w-1]+4); if(x<w-1) v=Math.min(v,D[i-w+1]+4); }
    D[i]=v; }
  for(let y=h-1;y>=0;y--) for(let x=w-1;x>=0;x--){ const i=y*w+x; let v=D[i];
    if(x<w-1) v=Math.min(v,D[i+1]+3);
    if(y<h-1){ v=Math.min(v,D[i+w]+3); if(x<w-1) v=Math.min(v,D[i+w+1]+4); if(x>0) v=Math.min(v,D[i+w-1]+4); }
    D[i]=v; }
  for(let i=0;i<w*h;i++) D[i]=D[i]>=INF?INF:D[i]/3;
  return D;
}

/* ---------------- Planning: where do toppings go ---------------- */
function orderChain(pts, rng){
  const n=pts.length; if(!n) return [];
  const used=new Uint8Array(n), out=[]; let cur=Math.floor(rng()*n);
  for(let k=0;k<n;k++){
    used[cur]=1; out.push(pts[cur]);
    let best=-1, bd=1e18; const [x,y]=pts[cur];
    for(let j=0;j<n;j++){ if(used[j]) continue; const dx=pts[j][0]-x, dy=pts[j][1]-y, dd=dx*dx+dy*dy; if(dd<bd){bd=dd;best=j; if(dd<=1) break;} }
    if(best<0) break; cur=best;
  }
  return out;
}
function plan(A){
  const {w,h}=A, ppm=A.rad/(S.diam/2), gapPx=S.gap*ppm, edgePx=3*ppm, spPx=2*ppm;
  const rng=mulberry32(S.seed);
  const items=TOPPINGS.filter(t=>S.enabled[t.id]&&S.counts[t.id]>0)
    .map(t=>({t, rr:t.mm/2*ppm, need:S.counts[t.id], want:S.counts[t.id]}));
  const spots=[]; const hasSyrup=A.syrupPx>0;
  const D=(x,y)=>A.dist[Math.min(h-1,y|0)*w+Math.min(w-1,x|0)];
  const edgeOk=(x,y,rr)=>A.rad-Math.hypot(x-A.cx,y-A.cy) >= rr+edgePx;
  const clear=(x,y,rr)=>{ for(const s of spots){ const dx=s.x-x, dy=s.y-y, m=s.rr+rr+spPx; if(dx*dx+dy*dy<m*m) return false; } return true; };
  const put=(it,x,y)=>{ spots.push({tid:it.t.id,x,y,rr:it.rr}); it.need--; };
  const ring=(target,rr)=>{ const band=Math.max(.75,rr*.12), pts=[];
    for(let y=0;y<h;y++) for(let x=0;x<w;x++){ if(Math.abs(A.dist[y*w+x]-target)<=band && edgeOk(x+.5,y+.5,rr)) pts.push([x+.5,y+.5]); }
    return orderChain(pts,rng); };
  const chainLen=ch=>{ let L=0; for(let i=1;i<ch.length;i++){ const s=Math.hypot(ch[i][0]-ch[i-1][0],ch[i][1]-ch[i-1][1]); if(s<=3) L+=s; } return L; };
  const walk=(ch,step,attempt)=>{ let acc=Infinity;
    for(let i=0;i<ch.length;i++){
      if(i>0){ const s=Math.hypot(ch[i][0]-ch[i-1][0],ch[i][1]-ch[i-1][1]); acc = s>3 ? Infinity : acc+s; }
      if(acc>=step && attempt(ch[i][0],ch[i][1])) acc=0;
    } };

  if(hasSyrup && S.style==='hug'){
    let inner=gapPx;
    for(const it of items){
      const target=inner+it.rr, ch=ring(target,it.rr);
      const step=Math.max(2*it.rr+spPx, chainLen(ch)/Math.max(1,it.need));
      walk(ch,step,(x,y)=>{ if(it.need<=0||!clear(x,y,it.rr)) return false; put(it,x,y); return true; });
      inner=target+it.rr+spPx;
    }
  } else if(hasSyrup && S.style==='turns' && items.length){
    const mr=Math.max(...items.map(i=>i.rr)), ch=ring(gapPx+mr,mr);
    const total=items.reduce((a,i)=>a+i.need,0); let ptr=0;
    walk(ch, Math.max(2*mr+spPx, chainLen(ch)/Math.max(1,total)), (x,y)=>{
      for(let k=0;k<items.length;k++){ const it=items[(ptr+k)%items.length]; if(it.need<=0) continue;
        if(!clear(x,y,it.rr)) return false; put(it,x,y); ptr=(ptr+k+1)%items.length; return true; }
      return false; });
  }
  // Sprinkle (also catches anything the rings had no room for)
  const left=items.filter(i=>i.need>0).sort((a,b)=>b.rr-a.rr);
  if(left.length){
    const minR=Math.min(...left.map(i=>i.rr)), cands=[];
    for(let y=0;y<h;y++) for(let x=0;x<w;x++){ const X=x+.5, Y=y+.5, dv=A.dist[y*w+x];
      if(edgeOk(X,Y,minR) && dv>=gapPx+minR) cands.push({x:X,y:Y,k: hasSyrup ? dv*(.45+rng()) : rng()}); }
    cands.sort((a,b)=>a.k-b.k);
    for(const it of left) for(const c of cands){ if(it.need<=0) break;
      if(!edgeOk(c.x,c.y,it.rr) || D(c.x,c.y)<gapPx+it.rr || !clear(c.x,c.y,it.rr)) continue; put(it,c.x,c.y); }
  }
  return {spots, short: items.filter(i=>i.need>0).map(i=>({t:i.t, got:i.want-i.need, want:i.want}))};
}

/* ---------------- Pipeline ---------------- */
function setSource(img,w,h){ S.src=img; S.srcW=w; S.srcH=h; runAnalyze(); }
function runAnalyze(){
  if(!S.src) return;
  S.A=analyze(S.src,S.srcW,S.srcH,S.thresh);
  const A=S.A, mc=document.createElement('canvas'); mc.width=A.w; mc.height=A.h;
  const mx=mc.getContext('2d'), id=mx.createImageData(A.w,A.h);
  for(let i=0;i<A.w*A.h;i++) if(A.mask[i]){ id.data[i*4]=255; id.data[i*4+1]=40; id.data[i*4+2]=200; id.data[i*4+3]=170; }
  mx.putImageData(id,0,0); S.maskCanvas=mc;
  runPlan();
}
function runPlan(){ if(!S.A) return; const r=plan(S.A); S.spots=r.spots; S.short=r.short; S.placed=new Set(); $('#celebrate').hidden=true; updateUI(); }

/* ---------------- Drawing ---------------- */
const cv=$('#view'), ctx=cv.getContext('2d'), fx=$('#fx');
function geom(){
  const A=S.A, size=cv.width, C=size/2, R=size*.42, k=R/(A.rad/A.scale);
  const cxI=A.cx/A.scale, cyI=A.cy/A.scale;
  return {size,C,R,k,cxI,cyI, w2c:(x,y)=>[C+(x/A.scale-cxI)*k, C+(y/A.scale-cyI)*k], wr:r=>r/A.scale*k};
}
function draw(t){
  const size=cv.width; ctx.clearRect(0,0,size,size);
  if(!S.A){ ctx.fillStyle='#1d1712'; ctx.fillRect(0,0,size,size); return; }
  const G=geom(), A=S.A;
  if(S.mode==='photo'){
    ctx.fillStyle='#1d1712'; ctx.fillRect(0,0,size,size);
    ctx.drawImage(S.src, G.C-G.cxI*G.k, G.C-G.cyI*G.k, S.srcW*G.k, S.srcH*G.k);
    ctx.save(); ctx.beginPath(); ctx.rect(0,0,size,size); ctx.arc(G.C,G.C,G.R*1.03,0,Math.PI*2);
    ctx.fillStyle='rgba(22,15,10,.62)'; ctx.fill('evenodd'); ctx.restore();
  } else {
    ctx.fillStyle='#000'; ctx.fillRect(0,0,size,size);
    ctx.save(); ctx.setLineDash([6*DPR,8*DPR]); ctx.strokeStyle='rgba(255,255,255,.28)'; ctx.lineWidth=2*DPR;
    ctx.beginPath(); ctx.arc(G.C,G.C,G.R,0,Math.PI*2); ctx.stroke(); ctx.restore();
  }
  if(S.debug){
    ctx.drawImage(S.maskCanvas, G.C-G.cxI*G.k, G.C-G.cyI*G.k, A.w/A.scale*G.k, A.h/A.scale*G.k);
    ctx.strokeStyle='#5cff7a'; ctx.lineWidth=2*DPR; ctx.beginPath(); ctx.arc(G.C,G.C,G.R,0,Math.PI*2); ctx.stroke();
    ctx.fillStyle='rgba(0,0,0,.6)'; ctx.fillRect(10*DPR,10*DPR,230*DPR,48*DPR);
    ctx.font=`600 ${12*DPR}px system-ui`; ctx.fillStyle='#5cff7a'; ctx.fillText('green = pancake edge found',18*DPR,30*DPR);
    ctx.fillStyle='#ff5ad2'; ctx.fillText('pink = syrup found',18*DPR,48*DPR);
  }
  S.spots.forEach((s,i)=>{
    const T=TBY[s.tid], [x,y]=G.w2c(s.x,s.y), r=G.wr(s.rr), done=S.placed.has(i);
    const pulse = done ? 1 : 1 + .07*Math.sin(t*3.2 + i*.7);
    ctx.save();
    if(done){
      ctx.globalAlpha=.9; ctx.fillStyle=T.color; ctx.beginPath(); ctx.arc(x,y,r,0,Math.PI*2); ctx.fill();
      ctx.globalAlpha=1; ctx.strokeStyle='#fff'; ctx.lineWidth=Math.max(2*DPR,r*.16); ctx.lineCap='round'; ctx.lineJoin='round';
      ctx.beginPath(); ctx.moveTo(x-r*.42,y+r*.02); ctx.lineTo(x-r*.1,y+r*.34); ctx.lineTo(x+r*.45,y-r*.32); ctx.stroke();
    } else {
      ctx.shadowColor=T.color; ctx.shadowBlur=10*DPR;
      ctx.fillStyle = S.mode==='photo' ? 'rgba(255,255,255,.82)' : 'rgba(255,255,255,.12)';
      ctx.beginPath(); ctx.arc(x,y,r*pulse,0,Math.PI*2); ctx.fill(); ctx.shadowBlur=0;
      ctx.strokeStyle = S.mode==='photo' ? T.color : '#fff'; ctx.lineWidth=Math.max(2.5*DPR, r*.16);
      ctx.setLineDash([Math.max(3*DPR,r*.35), Math.max(2*DPR,r*.2)]);
      ctx.beginPath(); ctx.arc(x,y,r*pulse,0,Math.PI*2); ctx.stroke(); ctx.setLineDash([]);
      const fs=Math.max(11*DPR, r*1.15);
      ctx.font=`${fs}px "Apple Color Emoji","Segoe UI Emoji","Noto Color Emoji",sans-serif`;
      ctx.fillStyle='#000'; // color-emoji glyphs inherit fillStyle alpha
      ctx.textAlign='center'; ctx.textBaseline='middle'; ctx.fillText(T.emoji,x,y+fs*.05);
    }
    ctx.restore();
  });
}
function loop(ts){ draw(ts/1000); requestAnimationFrame(loop); }

function resize(){
  const s=Math.round($('#stage').clientWidth*DPR);
  if(s && cv.width!==s){ cv.width=cv.height=fx.width=fx.height=s; }
}
new ResizeObserver(resize).observe($('#stage'));

/* ---------------- Interaction ---------------- */
cv.addEventListener('pointerdown', e=>{
  if(!S.A || !S.spots.length) return;
  const rc=cv.getBoundingClientRect(), px=(e.clientX-rc.left)*cv.width/rc.width, py=(e.clientY-rc.top)*cv.height/rc.height;
  const G=geom(); let best=-1, bd=Infinity;
  S.spots.forEach((s,i)=>{ const [x,y]=G.w2c(s.x,s.y), dd=Math.hypot(x-px,y-py); if(dd<G.wr(s.rr)+14*DPR && dd<bd){bd=dd;best=i;} });
  if(best<0) return;
  S.placed.has(best) ? S.placed.delete(best) : S.placed.add(best);
  updateKid();
  if(S.placed.size===S.spots.length) setTimeout(celebrate,350);
});
function celebrate(){
  $('#celebrate').hidden=false;
  const c=fx.getContext('2d'), rng=Math.random, cols=['#e07a2f','#f2c14e','#4f6bd8','#e2384d','#2f8f5b','#ff8ac2'];
  const P=Array.from({length:150},()=>({x:fx.width/2,y:fx.height*.45,vx:(rng()-.5)*16*DPR,vy:(-rng()*15-4)*DPR,s:(4+rng()*6)*DPR,c:cols[rng()*cols.length|0],r:rng()*6,vr:(rng()-.5)*.4}));
  const t0=performance.now();
  (function f(t){ c.clearRect(0,0,fx.width,fx.height);
    for(const p of P){ p.vy+=.38*DPR; p.vx*=.99; p.x+=p.vx; p.y+=p.vy; p.r+=p.vr;
      c.save(); c.translate(p.x,p.y); c.rotate(p.r); c.fillStyle=p.c; c.fillRect(-p.s/2,-p.s/4,p.s,p.s/2); c.restore(); }
    if(t-t0<3500) requestAnimationFrame(f); else c.clearRect(0,0,fx.width,fx.height);
  })(t0);
}
$('#done').onclick=celebrate;
$('#again').onclick=()=>{ S.placed=new Set(); $('#celebrate').hidden=true; updateKid(); };

// demo buttons
for(const [k,label] of Object.entries(DEMOS)){
  const b=document.createElement('button'); b.className='btn'; b.textContent=label; b.dataset.k=k;
  b.onclick=()=>loadDemo(k); $('#demos').appendChild(b);
}
function loadDemo(k){ if(typeof stopLive==='function') stopLive(); S.demo=k; const c=makeDemo(k); setSource(c,c.width,c.height); markDemo(); }
function markDemo(){ document.querySelectorAll('#demos .btn').forEach(b=>b.classList.toggle('on', b.dataset.k===S.demo)); }

// upload / drop / camera photos all end up here
// Draws any image, video frame or canvas into a working canvas (max 1200 px) and analyzes it.
function useFrame(el, w, h){
  if(!w || !h) return false;
  const sc=Math.min(1,1200/Math.max(w,h));
  const c=document.createElement('canvas'); c.width=Math.round(w*sc); c.height=Math.round(h*sc);
  c.getContext('2d').drawImage(el,0,0,c.width,c.height);
  S.demo=null; markDemo(); setSource(c,c.width,c.height);
  return true;
}
// Loads a Blob/File (JPEG, PNG, ...) and analyzes it. Resolves true on success.
function loadBlob(blob){
  return new Promise(res=>{
    if(!blob || !(blob.type||'').startsWith('image/')) return res(false);
    const url=URL.createObjectURL(blob), img=new Image();
    img.onload=()=>{ const ok=useFrame(img,img.naturalWidth,img.naturalHeight); URL.revokeObjectURL(url); res(ok); };
    img.onerror=()=>{ URL.revokeObjectURL(url); res(false); };
    img.src=url;
  });
}
function loadFile(f){ return loadBlob(f); }
$('#file').onchange=e=>{ loadFile(e.target.files[0]); e.target.value=''; };
const stage=$('#stage');
stage.addEventListener('dragover',e=>{ e.preventDefault(); $('#dropHint').hidden=false; });
stage.addEventListener('dragleave',()=>{ $('#dropHint').hidden=true; });
stage.addEventListener('drop',e=>{ e.preventDefault(); $('#dropHint').hidden=true; loadFile(e.dataTransfer.files[0]); });

// toppings list
function buildToppings(){
  const box=$('#toppings'); box.innerHTML='';
  for(const t of TOPPINGS){
    const row=document.createElement('div'); row.className='trow'+(S.enabled[t.id]?'':' off');
    row.innerHTML=`<label><input type="checkbox" ${S.enabled[t.id]?'checked':''}><span class="em">${t.emoji}</span>${t.name}</label>
      <div class="step"><button aria-label="fewer">−</button><span>${S.counts[t.id]}</span><button aria-label="more">+</button></div>`;
    const [cb]=row.querySelectorAll('input'), [minus,plus]=row.querySelectorAll('button');
    cb.onchange=()=>{ S.enabled[t.id]=cb.checked; buildToppings(); runPlan(); };
    minus.onclick=()=>{ S.counts[t.id]=Math.max(1,S.counts[t.id]-1); buildToppings(); runPlan(); };
    plus.onclick=()=>{ S.counts[t.id]=Math.min(t.max,S.counts[t.id]+1); buildToppings(); runPlan(); };
    box.appendChild(row);
  }
}
function seg(id,key,after){
  document.querySelectorAll(`#${id} button`).forEach(b=>b.onclick=()=>{ S[key]=b.dataset.v; markSeg(); after(); });
}
function markSeg(){
  document.querySelectorAll('#styleSeg button').forEach(b=>b.classList.toggle('on',b.dataset.v===S.style));
  document.querySelectorAll('#modeSeg button').forEach(b=>b.classList.toggle('on',b.dataset.v===S.mode));
}
seg('styleSeg','style',runPlan); seg('modeSeg','mode',()=>{});
$('#shuffle').onclick=()=>{ S.seed=(Math.random()*1e9)|0; runPlan(); };
$('#surprise').onclick=()=>{
  const r=Math.random; S.seed=(r()*1e9)|0;
  S.style=['hug','turns','sprinkle'][r()*3|0];
  const pick=[...TOPPINGS].sort(()=>r()-.5).slice(0, r()<.5?1:2);  // notes: keep it to one or two toppings
  TOPPINGS.forEach(t=>S.enabled[t.id]=pick.includes(t));
  pick.forEach(t=>S.counts[t.id]=Math.max(2,Math.round(t.count*(.6+r()*.7))));
  buildToppings(); markSeg(); runPlan();
};
$('#debug').onchange=e=>{ S.debug=e.target.checked; };

function bindSlider(id,key,fmt,after){
  const el=$('#'+id); el.value=S[key]; $('#'+id+'V').textContent=fmt(S[key]);
  el.oninput=()=>{ S[key]=+el.value; $('#'+id+'V').textContent=fmt(S[key]); after(); };
}
bindSlider('diam','diam',v=>v+' mm',runPlan);
bindSlider('gap','gap',v=>v+' mm',runPlan);
bindSlider('thresh','thresh',v=>v,runAnalyze);

$('#copy').onclick=async()=>{
  const ta=$('#json');
  try{ await navigator.clipboard.writeText(ta.value); $('#copy').textContent='Copied ✓'; }
  catch(e){ ta.select(); $('#copy').textContent='Press Ctrl/Cmd+C'; }
  setTimeout(()=>$('#copy').textContent='Copy JSON',1600);
};

/* ---------------- UI text ---------------- */
function updateKid(){
  const used={};
  S.spots.forEach((s,i)=>{ used[s.tid]=used[s.tid]||{n:0,done:0}; used[s.tid].n++; if(S.placed.has(i)) used[s.tid].done++; });
  $('#legend').innerHTML = Object.keys(used).length ? TOPPINGS.filter(t=>used[t.id]).map(t=>
    `<div class="chip" style="--c:${t.color}"><span class="dot">${t.emoji}</span>${used[t.id].n} ${t.name.toLowerCase()} <small>${used[t.id].done}/${used[t.id].n}</small></div>`).join('')
    : '<span style="color:var(--muted)">Pick a topping on the right to get started.</span>';
  const n=S.spots.length, d=S.placed.size;
  $('#barFill').style.width = n ? (100*d/n)+'%' : '0';
  $('#progText').textContent = n ? `${d} of ${n} placed` : '';
}
function updateUI(){
  const A=S.A, lines=[];
  lines.push(A.found ? `<span class="ok">✓ Pancake found</span>` : `<span class="warn">Couldn't find a golden pancake, so I'm guessing it fills the middle of the photo.</span>`);
  lines.push(A.syrupPx ? `<span class="ok">✓ Syrup found: covers ${Math.round(A.syrupFrac*100)}% of the pancake</span>`
                        : `<span class="warn">No syrup found, so toppings are scattered randomly. Try a lower detection threshold.</span>`);
  if(A.syrupFrac>.6) lines.push(`<span class="warn">Over half the pancake counts as syrup. Brown cooking spots may be getting picked up, so try a higher threshold.</span>`);
  lines.push(`<span>${S.spots.length} topping spots planned</span>`);
  for(const s of S.short) lines.push(`<span class="warn">Only room for ${s.got} of ${s.want} ${s.t.name.toLowerCase()}. Try a smaller gap or fewer.</span>`);
  $('#status').innerHTML=lines.join('');
  const ppm=A.rad/(S.diam/2), r1=v=>Math.round(v*10)/10;
  $('#json').value=JSON.stringify({
    pancake_diameter_mm:S.diam,
    coordinates:'mm from pancake center; +x = right, +y = down in the camera image',
    syrup_coverage:r1(A.syrupFrac*100)/100, layout:S.style, gap_from_syrup_mm:S.gap,
    spots:S.spots.map(s=>({topping:s.tid, x_mm:r1((s.x-A.cx)/ppm), y_mm:r1((s.y-A.cy)/ppm), size_mm:TBY[s.tid].mm}))
  },null,2);
  updateKid();
}


/* ---------------- Camera ----------------
   Two live sources besides the demos:
   - "pi": the robot's camera server (pi/camera_server.py). Live view is its MJPEG stream,
     photos come from /api/snapshot.jpg, and /api/status tells us when the robot has
     finished the syrup (POST /api/syrup-done) so we can take the photo on our own.
   - "webcam": this device's camera through getUserMedia, for testing without a Pi.
   Photos go through loadBlob/useFrame, the same path as uploads. */
const CAM = { source:'demo', piBase:null, piSeq:null, pollTimer:null, pollBusy:false, stream:null, snapping:false };
const liveImg=$('#live'), liveVid=$('#liveVideo');

function camMsg(id, text, kind){ const el=$(id); el.textContent=text; el.className='camMsg'+(kind?' '+kind:''); }
function showLive(which){
  liveImg.hidden = which!=='img'; liveVid.hidden = which!=='video';
  $('#liveBadge').hidden = !which;
  if(which) $('#celebrate').hidden=true;
}
function stopLive(){
  showLive(null);
  liveImg.removeAttribute('src');   // closes the MJPEG connection
  if(CAM.stream){ CAM.stream.getTracks().forEach(t=>t.stop()); CAM.stream=null; liveVid.srcObject=null; camMsg('#camMsg','Camera off.'); }
}

function setCamSource(v){
  if(v===CAM.source) return;
  stopLive(); stopPoll();
  CAM.source=v;
  document.querySelectorAll('#srcSeg button').forEach(b=>b.classList.toggle('on',b.dataset.v===v));
  $('#srcDemo').hidden = v!=='demo'; $('#srcPi').hidden = v!=='pi'; $('#srcWebcam').hidden = v!=='webcam';
  try{ localStorage.setItem('pancake.source', v); }catch(e){}
  if(v==='pi') piConnect();
  if(v==='webcam') listCams();
}
document.querySelectorAll('#srcSeg button').forEach(b=>b.onclick=()=>setCamSource(b.dataset.v));

/* ----- Raspberry Pi camera server ----- */
function piBaseFromInput(){
  let u=$('#piUrl').value.trim();
  if(!u) return location.protocol.startsWith('http') ? '' : null; // same server the page came from
  if(!/^https?:\/\//i.test(u)) u='http://'+u;
  return u.replace(/\/+$/,'');
}
async function piFetch(path, opts={}){
  const ctl=new AbortController(), to=setTimeout(()=>ctl.abort(), opts.timeout||4000);
  try{ const r=await fetch(CAM.piBase+path,{cache:'no-store',signal:ctl.signal,...opts}); if(!r.ok) throw new Error('HTTP '+r.status); return r; }
  finally{ clearTimeout(to); }
}
function piButtons(on){ $('#piLive').disabled=!on; $('#piSnap').disabled=!on; }
async function piConnect(){
  stopPoll(); piButtons(false);
  const base=piBaseFromInput();
  if(base===null){ camMsg('#piMsg','Type the Pi\'s address, e.g. http://raspberrypi.local:8000','err'); return; }
  try{ localStorage.setItem('pancake.piUrl', $('#piUrl').value.trim()); }catch(e){}
  CAM.piBase=base; camMsg('#piMsg','Connecting…');
  try{
    const st=await (await piFetch('/api/status')).json();
    if(!st.camera_ok){ camMsg('#piMsg',`Connected, but the camera isn't working: ${st.error||'unknown error'}`,'err'); return; }
    CAM.piSeq=st.syrup_done;
    camMsg('#piMsg',`✓ Connected to ${st.camera} camera. Waiting for the robot…`,'ok');
    piButtons(true); startPoll();
    if(!S.src || S.demo) piLive();
  }catch(e){
    camMsg('#piMsg',`Can't reach the camera server at ${base||location.origin}. Is pi/camera_server.py running, and is this the right address?`,'err');
  }
}
function piLive(){
  if(CAM.source!=='pi' || CAM.piBase===null) return;
  liveImg.onerror=()=>{ if(!liveImg.hidden){ showLive(null); camMsg('#piMsg','Live view stopped. Press Connect to try again.','err'); } };
  liveImg.src=CAM.piBase+'/api/stream?t='+Date.now();
  showLive('img');
}
async function piSnap(why){
  if(CAM.snapping) return; CAM.snapping=true;
  try{
    const blob=await (await piFetch('/api/snapshot.jpg?t='+Date.now(),{timeout:8000})).blob();
    if(!(await loadBlob(blob))) throw new Error('not an image');
    stopLive();
    camMsg('#piMsg', why==='auto' ? `✓ The robot finished the syrup, so I took the photo (${new Date().toLocaleTimeString()}).`
                                  : `✓ Photo taken (${new Date().toLocaleTimeString()}).`, 'ok');
  }catch(e){ camMsg('#piMsg','Couldn\'t get a photo from the camera server.','err'); }
  finally{ CAM.snapping=false; }
}
function startPoll(){ stopPoll(); CAM.pollTimer=setInterval(piPoll, 1000); }
function stopPoll(){ if(CAM.pollTimer){ clearInterval(CAM.pollTimer); CAM.pollTimer=null; } }
async function piPoll(){
  if(CAM.pollBusy || CAM.source!=='pi') return; CAM.pollBusy=true;
  try{
    const st=await (await piFetch('/api/status',{timeout:2500})).json();
    if(CAM.piSeq!==null && st.syrup_done!==CAM.piSeq && $('#piAuto').checked){ CAM.piSeq=st.syrup_done; await piSnap('auto'); }
    else CAM.piSeq=st.syrup_done;
  }catch(e){ /* a missed poll is fine; the next one retries */ }
  finally{ CAM.pollBusy=false; }
}
$('#piConnect').onclick=piConnect;
$('#piUrl').addEventListener('keydown',e=>{ if(e.key==='Enter') piConnect(); });
$('#piLive').onclick=piLive;
$('#piSnap').onclick=()=>piSnap('button');
piButtons(false);

/* ----- This computer's webcam ----- */
async function listCams(){
  if(!navigator.mediaDevices?.enumerateDevices) return;
  try{
    const devs=(await navigator.mediaDevices.enumerateDevices()).filter(d=>d.kind==='videoinput');
    const sel=$('#camSelect'), cur=sel.value;
    sel.innerHTML='<option value="">Default camera</option>'+devs.map((d,i)=>`<option value="${d.deviceId}">${(d.label||'Camera '+(i+1)).replace(/</g,'&lt;')}</option>`).join('');
    if([...sel.options].some(o=>o.value===cur)) sel.value=cur;
  }catch(e){}
}
async function camStart(){
  if(!navigator.mediaDevices?.getUserMedia){
    camMsg('#camMsg','This browser can only use the camera on a secure page (https:// or http://localhost).','err'); return; }
  stopLive();
  const id=$('#camSelect').value;
  try{
    CAM.stream=await navigator.mediaDevices.getUserMedia({audio:false, video: id ? {deviceId:{exact:id}} : {width:{ideal:1280},height:{ideal:960}}});
    liveVid.srcObject=CAM.stream; await liveVid.play().catch(()=>{});
    showLive('video'); camMsg('#camMsg','✓ Camera on. Line up the pancake, then take the photo.','ok');
    listCams(); // labels only show up after permission is granted
  }catch(e){
    const why = e.name==='NotAllowedError' ? 'Camera permission was blocked. Allow it in the address bar and try again.'
              : e.name==='NotFoundError'   ? 'No camera found on this device.'
              : e.name==='NotReadableError'? 'The camera is busy in another app.'
              : 'Couldn\'t start the camera ('+e.name+').';
    camMsg('#camMsg',why,'err');
  }
}
async function camSnap(){
  if(!CAM.stream){ await camStart(); if(!CAM.stream) return; await new Promise(r=>setTimeout(r,400)); }
  if(!liveVid.videoWidth){ await new Promise(r=>liveVid.addEventListener('loadeddata',r,{once:true})); }
  if(useFrame(liveVid, liveVid.videoWidth, liveVid.videoHeight)){ stopLive(); camMsg('#camMsg',`✓ Photo taken (${new Date().toLocaleTimeString()}). Press Live view to retake.`,'ok'); }
}
$('#camStart').onclick=camStart;
$('#camSnap').onclick=camSnap;
$('#camSelect').onchange=()=>{ if(CAM.stream) camStart(); };

/* ----- Pick the starting source -----
   ?source=pi|webcam|demo and ?pi=<address> in the URL win; otherwise the last choice is remembered.
   A page served by the camera server itself starts on the Pi tab. */
(function initCamera(){
  const q=new URLSearchParams(location.search); let saved=null, savedUrl='';
  try{ saved=localStorage.getItem('pancake.source'); savedUrl=localStorage.getItem('pancake.piUrl')||''; }catch(e){}
  $('#piUrl').value = q.get('pi') ?? savedUrl;
  document.querySelectorAll('#srcSeg button').forEach(b=>b.classList.toggle('on',b.dataset.v==='demo'));
  let want=q.get('source') || saved;
  if(!want){
    fetch('api/status',{cache:'no-store'}).then(r=>r.ok?r.json():null).then(st=>{ if(st && 'syrup_done' in st) setCamSource('pi'); }).catch(()=>{});
  } else if(want!=='demo') setCamSource(want);
})();

/* ---------------- Start ---------------- */
buildToppings(); markSeg(); resize(); loadDemo('heart'); requestAnimationFrame(loop);
