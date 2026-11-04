/* 真DOM交互回归：覆盖遮挡牌墙、占格三合一、手机点选、战斗和重开。 */
const fs=require('fs'), path=require('path'), assert=require('assert');
const {spawnSync}=require('child_process');
const {JSDOM,VirtualConsole}=require('jsdom');
const root=path.resolve(__dirname,'../..');
const py=process.env.COURSEMATE_PYTHON || (fs.existsSync(path.join(root,'.venv/Scripts/python.exe')) ? path.join(root,'.venv/Scripts/python.exe') : 'python');
const build=spawnSync(py,['-c','from game.view import build_config,build_html; print(build_html(build_config(200)))'],{cwd:root,encoding:'utf8',env:{...process.env,PYTHONIOENCODING:'utf-8'}});
if(build.status!==0) throw new Error(build.stderr);
let count=0;
const errors=[];
const vc=new VirtualConsole();vc.on('jsdomError',e=>errors.push(e.message));
const dom=new JSDOM(build.stdout,{runScripts:'dangerously',pretendToBeVisual:true,url:'http://localhost/game',virtualConsole:vc,beforeParse(w){let seed=20261103;w.Math.random=()=>{seed|=0;seed=seed+0x6D2B79F5|0;let t=Math.imul(seed^seed>>>15,1|seed);t=t+Math.imul(t^t>>>7,61|t)^t;return ((t^t>>>14)>>>0)/4294967296;};w.requestAnimationFrame=()=>0;w.scrollTo=()=>{};}});
function ok(label,value){assert.ok(value,label);count++;console.log('[PASS] '+label);}
setTimeout(()=>{
 try{
 const w=dom.window,d=w.document,G=w.__CM_DEBUG,S=G.S;
 const click=n=>{assert.ok(n,'click target exists');n.dispatchEvent(new w.MouseEvent('click',{bubbles:true}));};
 const reset=()=>{G.restartGame();S.jade=200;S.board.forEach(c=>{c.locked=c.c!==0;});G.renderAll();};
 const drag=(source,target)=>{let payload='';const dt={setData(_,v){payload=v;},getData(){return payload;}};for(const [node,type] of [[source,'dragstart'],[target,'dragover'],[target,'drop']]){const e=new w.Event(type,{bubbles:true,cancelable:true});Object.defineProperty(e,'dataTransfer',{value:dt});node.dispatchEvent(e);}};
 const cell=(r,c)=>d.querySelector('.cell[data-r="'+r+'"][data-c="'+c+'"]');
 const beastSlot=i=>d.querySelector('.beast-cell[data-bi="'+i+'"]');
 const open=()=>S.board.filter(c=>!c.locked);
 const remaining=()=>S.deck.flat().filter(Boolean).length;
 const typeBag=()=>S.deck.flat().filter(Boolean).map(c=>c.type+':'+c.ch).sort().join(',');
 ok('初始化无脚本异常',errors.length===0);
 ok('道路全部为水平或垂直的直角线段',G.PATH.slice(1).every((p,i)=>p[0]===G.PATH[i][0]||p[1]===G.PATH[i][1]));
 ok('入口与终点未闭合且左上方断开',G.PATH[0][0]<0&&G.PATH.at(-1)[0]===2.5&&G.PATH.at(-1)[1]<0&&G.PATH.length===5);
 ok('下侧路线位于五行棋盘外',G.PATH[1][1]>5&&G.PATH[2][1]>5);
 ok('显示道路与怪物路线完全共用坐标',Array.from(d.querySelectorAll('.road polyline')).every(line=>line.getAttribute('points')===G.PATH.map(p=>p.join(',')).join(' ')));
 // 用非零布局验证怪物实际像素边界，不依赖jsdom默认的零尺寸矩形。
 const boardNode=d.querySelector('#board'),wrapNode=d.querySelector('#boardWrap');
 const boardRect=boardNode.getBoundingClientRect,wrapRect=wrapNode.getBoundingClientRect;
 for(const width of [200,320,480]){
   boardNode.getBoundingClientRect=()=>({left:100,top:120,width,height:width});
   wrapNode.getBoundingClientRect=()=>({left:100,top:120,width,height:width});
   G.measureBoard();let outside=true;
   for(let segment=0;segment<G.PATH.length-1;segment++){
     for(let step=0;step<=20;step++){
       const a=G.PATH[segment],b=G.PATH[segment+1],t=step/20;
       S.enemies=[{x:a[0]+(b[0]-a[0])*t,y:a[1]+(b[1]-a[1])*t,type:'妖王',label:'魁',hp:10,maxHp:10}];
       G.renderEnemies();const node=d.querySelector('.enemy');
       const x=parseFloat(node.style.left),y=parseFloat(node.style.top);
       // 最大怪物显示框含阴影与血条，保守取水平20、垂直28像素半径。
       outside&&=x+20<=0||x-20>=width||y+28<=0||y-28>=width;
     }
   }
   ok('宽度'+width+'下全路线怪物像素框不进入棋盘',outside);
 }
 boardNode.getBoundingClientRect=boardRect;wrapNode.getBoundingClientRect=wrapRect;S.enemies=[];G.measureBoard();G.renderEnemies();
 G.startWave();ok('空阵不能出战',S.phase==='prep');
 ok('开局25格',S.board.length===25);ok('开局随机开放五格',open().length===5);
 const shapes=new Set();let layoutsValid=true;
 for(let sample=0;sample<80;sample++){G.restartGame();const cells=open();shapes.add(cells.map(c=>c.r+','+c.c).sort().join(';'));const seen=new Set([cells[0]]);let queue=[cells[0]];while(queue.length){const a=queue.pop();cells.forEach(b=>{if(!seen.has(b)&&Math.abs(a.r-b.r)+Math.abs(a.c-b.c)===1){seen.add(b);queue.push(b);}});}layoutsValid&&=cells.length===5&&seen.size===5&&cells.some(c=>c.r===0||c.c===0||c.r===4||c.c===4)&&cells.every(c=>Math.min(c.r,c.c,4-c.r,4-c.c)<=1);}
 ok('80次开局都是靠边连通五格',layoutsValid);ok('开局布局确实随机变化',shapes.size>1);reset();
 ok('初始五个独立暂存格',S.slots.length===5&&S.slots.every(x=>x===null));
 ok('四层共60张字牌',S.deck.length===4&&remaining()===60);
 ok('最高层四张都可取',S.deck[3].every((_,i)=>G.isCardFree(3,i)));
 ok('低层存在遮挡',S.deck[0].some((_,i)=>!G.isCardFree(0,i)));
 let blocked=S.deck[0].findIndex((_,i)=>!G.isCardFree(0,i));let before=remaining();G.clickCard(0,blocked);
 ok('被遮挡字牌不可拿走',remaining()===before);
 for(let i=0;i<4;i++){S.deck[3][i].type='normal';S.deck[3][i].ch=['金','水','火','土'][i];}
 click(d.querySelector('.gcard[data-ci="3"][data-i="0"]'));
 ok('点击顶层牌真实消耗一张',remaining()===before-1);ok('取牌占一个暂存格',S.slots.filter(Boolean).length===1);
 ok('取牌后遮挡状态更新',d.querySelectorAll('.gcard').length===59);
 reset();G.addToSlot('火');G.addToSlot('火');ok('两张占两格而非堆叠',S.slots.filter(Boolean).length===2);
 G.addToSlot('火');ok('三张合一消耗三个暂存格',S.slots.every(x=>x===null));ok('三合一仍为一阶火',S.board.some(c=>c.unit&&c.unit.ch==='火'));
 reset();click(d.querySelector('#autoMerge'));G.addToSlot('水');G.addToSlot('水');G.addToSlot('水');G.renderAll();
 ok('关闭自动合成后保留三张',S.slots.filter(Boolean).length===3);ok('未提前落子',open().every(c=>!c.unit));
 click(d.querySelector('.slot.filled'));ok('点击暂存格手动三合一',S.slots.every(x=>x===null)&&S.board.some(c=>c.unit&&c.unit.ch==='水'));
 reset();open().forEach(c=>c.unit={ch:'土',cd:0});G.addToSlot('金');G.addToSlot('金');G.addToSlot('金');
 ok('棋盘满时三张原牌保留',S.slots.filter(Boolean).length===3);
 reset();['金','火','水','土','日'].forEach(ch=>G.addToSlot(ch));ok('五张不同字占满五格',S.slots.every(Boolean));
 ok('满槽拒绝取牌且不覆盖旧牌',!G.addToSlot('木')&&S.slots[4].ch==='日');
 G.renderAll();click(d.querySelector('#expandSlots'));ok('扩槽扣费并增加一格',S.slots.length===6&&S.jade===170);click(d.querySelector('#expandSlots'));ok('最大七格',S.slots.length===7&&S.jade===140);ok('满级扩槽按钮禁用',d.querySelector('#expandSlots').disabled);
 reset();G.placeUnit('火');G.placeUnit('火');G.renderAll();
 click(d.querySelectorAll('.cell')[0]);ok('点击选中单位',!!S.selected&&!!d.querySelector('.cell.selected'));
 click(d.querySelectorAll('.cell')[5]);ok('手机两次点击完成同阶合并',S.board[5].unit.ch==='炎'&&!S.board[0].unit);
 G.placeUnit('炎');ok('二阶合成三阶',G.tryMerge(S.board[0],S.board[5])&&S.board[5].unit.ch==='焱');
 G.placeUnit('焱');ok('两个三星合成四星',G.tryMerge(S.board[0],S.board[5])&&G.LEVEL_OF[S.board[5].unit.ch].lv===4);
 G.placeUnit(G.CHAINS['火'][3]);ok('四星封顶不丢牌',!G.tryMerge(S.board[0],S.board[5])&&G.LEVEL_OF[S.board[0].unit.ch].lv===4);G.renderAll();ok('四星火显示单个完整燚字',cell(1,0).querySelector('.four-glyph').textContent==='燚'&&!cell(1,0).querySelector('.quad'));ok('六系四星均为单个叠字',Object.values(G.CHAINS).every(chain=>Array.from(chain[3]).length===1));ok('右上神兽共鸣标识已删除',!d.querySelector('.beast-emblem'));
 reset();G.placeUnit('火');G.placeUnit('水');ok('跨字不能合并',!G.tryMerge(S.board[0],S.board[5]));
 ok('日字有完整升阶链',G.CHAINS['日'].slice(0,3).join('')==='日昍晶'&&G.CHAINS['日'].length===4);ok('水字二阶为沝',G.CHAINS['水'][1]==='沝');
 reset();G.placeUnit(G.CHAINS['木'][3]);G.renderAll();ok('四星木固定为田字形完整四木图形',cell(0,0).querySelectorAll('svg.wood-glyph path').length===4);ok('四星木不使用会产生结构差异的字体文字',!cell(0,0).querySelector('.wood-glyph').textContent);
 reset();G.placeUnit('水');G.placeUnit('水');G.tryMerge(S.board[0],S.board[5]);ok('两个水实际融合为沝',S.board[5].unit.ch==='沝');
 reset();G.placeUnit('火');G.placeUnit('水');S.board[0].unit.cd=.4;S.board[5].unit.cd=.8;G.renderAll();drag(cell(0,0),cell(1,0));ok('备战异字直接交换位置',S.board[0].unit.ch==='水'&&S.board[5].unit.ch==='火');ok('交换保留各自攻击冷却',S.board[0].unit.cd===.8&&S.board[5].unit.cd===.4);
 G.startWave();drag(cell(1,0),cell(2,0));ok('闯关中可拖到空棋盘',!S.board[5].unit&&S.board[10].unit.ch==='火');
 drag(cell(0,0),cell(2,0));ok('闯关中异字也可交换',S.board[0].unit.ch==='火'&&S.board[10].unit.ch==='水');
 S.board[5].unit={ch:'火',cd:0};G.renderAll();drag(cell(0,0),cell(1,0));ok('闯关中同阶同字仍能融合',!S.board[0].unit&&S.board[5].unit.ch==='炎');
 drag(cell(1,0),cell(1,1));ok('闯关中不能移入封锁格',S.board[5].unit.ch==='炎'&&S.board[6].locked);
 click(cell(1,0));click(cell(0,0));ok('闯关中触屏点选也可移动',S.board[0].unit.ch==='炎'&&!S.board[5].unit);
 S.phase='over';drag(cell(0,0),cell(1,0));ok('结算阶段不再允许移动',S.board[0].unit.ch==='炎'&&!S.board[5].unit);
 reset();const locked=S.board.filter(c=>c.locked).length;click(d.querySelector('#btnShovel'));ok('点击铲子先选目标不扣费',S.jade===200&&!!S.shovelSource);click(cell(4,4));ok('铲子按服务端配置扣费',S.jade===180);ok('点亮玩家指定格',!S.board[24].locked);ok('铲子只解锁一格',S.board.filter(c=>c.locked).length===locked-1);
 const bag=typeBag();before=remaining();click(d.querySelector('#btnShuffle'));ok('打乱保持牌数',remaining()===before);ok('打乱保持牌型多重集',typeBag()===bag);ok('打乱扣15',S.jade===165);
 S.jade=0;before=remaining();click(d.querySelector('#btnRefresh'));ok('灵玉不足不能刷新',remaining()===before&&S.jade===0);
 S.jade=100;click(d.querySelector('#btnRefresh'));ok('刷新扣30',S.jade===70&&remaining()===60);
 S.board.forEach(c=>c.locked=false);const jade=S.jade;click(d.querySelector('#btnShovel'));ok('全部解锁后不空扣铲子费用',S.jade===jade);
 reset();G.placeUnit('炎');G.renderAll();click(d.querySelector('#btnClear'));ok('清空保留已合成牌身份',S.slots[0].ready&&S.slots[0].ch==='炎');G.onSlotClick(0);ok('已合成字能直接重新上阵',S.slots[0]===null&&S.board[0].unit.ch==='炎');
 // 稀有与唯一性：覆盖刷新、已持有、已激活和满格取牌。
 reset();const amounts=new Set();let valid=true;
 for(let n=0;n<150;n++){G.refreshDeck();const chars=S.deck.flat().filter(c=>c&&c.type==='beast').map(c=>c.ch);amounts.add(chars.length);valid&&=chars.length<=2&&new Set(chars).size===chars.length;}
 ok('150副牌均只有0至2个且无重复神兽字',valid);ok('能随机出现0、1、2个残字',amounts.size===3);
 ok('青字初次点击进入神兽槽',G.placeBeastChar('青')&&S.beastSlots[0]==='青');
 ok('已有青字不能再拿青',!G.placeBeastChar('青')&&S.beastSlots.filter(c=>c==='青').length===1);
 G.placeBeastChar('白');ok('神兽槽已满',S.beastSlots.every(Boolean));
 ok('槽满后龙字进入空棋盘',G.placeBeastChar('龙')&&S.board.some(c=>c.unit&&c.unit.beastChar&&c.unit.ch==='龙'));
 let heldExcluded=true;for(let n=0;n<30;n++){G.refreshDeck();heldExcluded&&=!S.deck.flat().some(c=>c&&c.type==='beast'&&['青','白','龙'].includes(c.ch));}ok('反复刷新不再生成已持有残字',heldExcluded);
 S.board.forEach(c=>{if(!c.locked&&!c.unit)c.unit={ch:'火',cd:0};});
 S.deck[3][0]={type:'beast',ch:'虎',x:1.5,y:1.5,z:3};G.renderAll();
 const beforeFull=remaining();click(d.querySelector('.gcard[data-ci="3"][data-i="0"]'));
 ok('神兽槽与棋盘全满时点击不消费牌',remaining()===beforeFull&&S.deck[3][0].ch==='虎');
 // 槽内凑字不自动激活；必须真正拖到棋盘上横向按序排列。
 reset();S.board.forEach(c=>{c.locked=false;});G.placeBeastChar('青');G.placeBeastChar('龙');
 ok('青龙留在神兽槽不自动激活',S.beastUnits.length===0&&S.beastSlots.join('')==='青龙');
 drag(beastSlot(0),cell(0,0));ok('真实拖动槽内青字到空棋盘',S.beastSlots[0]===null&&S.board[0].unit.ch==='青'&&S.board[0].unit.beastChar);
 drag(beastSlot(1),cell(0,1));ok('横排青龙原位激活',S.beastUnits.length===1&&S.board[0].unit.ch==='青龙');
 ok('异兽占据横向两格',S.board[0].unit.span===2&&S.board[1].unit.covered);ok('青龙提供全局攻击加成',G.activeBuff('attack')>1);
 G.checkBeast();ok('重复检查不会重复叠加神兽',S.beastUnits.length===1);
 let activeExcluded=true;for(let n=0;n<40;n++){G.refreshDeck();activeExcluded&&=!S.deck.flat().some(c=>c&&c.type==='beast'&&['青','龙'].includes(c.ch));}
 ok('激活后刷新也不再生成青龙残字',activeExcluded);
 reset();S.board.forEach(c=>{c.locked=false;});G.placeBeastChar('龙');G.placeBeastChar('青');drag(beastSlot(0),cell(0,0));drag(beastSlot(1),cell(0,1));ok('龙青反序不激活',S.beastUnits.length===0);
 reset();S.board.forEach(c=>{c.locked=false;});G.placeBeastChar('白');G.placeBeastChar('龙');drag(beastSlot(0),cell(0,0));drag(beastSlot(1),cell(0,1));ok('白龙混搭不激活',S.beastUnits.length===0);
 reset();S.board.forEach(c=>{c.locked=false;});G.placeBeastChar('青');G.placeBeastChar('龙');drag(beastSlot(0),cell(0,0));drag(beastSlot(1),cell(1,0));ok('竖排青龙不激活',S.beastUnits.length===0);
 drag(cell(1,0),cell(0,1));ok('棋盘残字可以拖动成横排激活',S.beastUnits.length===1);
 reset();S.board.forEach(c=>{c.locked=false;});G.placeBeastChar('白');G.placeBeastChar('虎');drag(beastSlot(0),cell(0,4));drag(beastSlot(1),cell(1,0));ok('跨行尾首不算横排',S.beastUnits.length===0);
 drag(cell(0,4),beastSlot(0));ok('未激活残字可拖回空神兽槽',S.beastSlots[0]==='白'&&!S.board[4].unit);
 drag(beastSlot(0),cell(1,1));ok('虎白反序仍不激活',S.beastUnits.length===0);
 drag(cell(1,1),cell(2,0));drag(cell(1,0),cell(2,1));ok('横排白虎正确激活',S.beastUnits.length===1&&S.board[10].unit.ch==='白虎');
 reset();G.placeBeastChar('青');drag(beastSlot(0),cell(0,1));ok('不能把残字拖到封锁格',S.beastSlots[0]==='青'&&S.board[1].locked);
 G.placeUnit('火');G.renderAll();drag(beastSlot(0),cell(0,0));ok('不能覆盖已有棋盘单位',S.beastSlots[0]==='青'&&S.board[0].unit.ch==='火');
 G.startWave();drag(beastSlot(0),cell(1,0));ok('战斗中不能从神兽槽补字',S.beastSlots[0]==='青'&&!S.board[5].unit);
 reset();G.placeBeastChar('青');drag(beastSlot(0),cell(0,0));
 G.startWave();ok('只有神兽残字时不能空阵出战',S.phase==='prep');
 const target={x:-.4,y:.5,hp:20,maxHp:20,slow:1,seg:0,t:0};S.enemies=[target];G.towerAttack(1);ok('未激活残字不攻击',target.hp===20&&G.activeBuff('attack')===1);
 // 模拟触屏抬手落点，走同一套指针事件，避免只验证桌面drag/drop。
 reset();G.placeBeastChar('青');const touchSource=beastSlot(0),touchTarget=cell(2,0),oldHit=d.elementFromPoint;
 d.elementFromPoint=()=>touchTarget;
 for(const [kind,x,y] of [['pointerdown',10,10],['pointerup',120,140]]){const event=new w.Event(kind,{bubbles:true,cancelable:true});Object.defineProperties(event,{pointerType:{value:'touch'},pointerId:{value:1},clientX:{value:x},clientY:{value:y}});touchSource.dispatchEvent(event);}
 d.elementFromPoint=oldHit;ok('触屏指针拖动能放置神兽残字',S.beastSlots[0]===null&&S.board[10].unit.ch==='青');
 reset();drag(d.querySelector('#btnShovel'),cell(3,3));ok('商店铲子真实拖动定点解锁',!S.board[18].locked&&S.jade===180);
 const paid=S.jade;drag(d.querySelector('#btnShovel'),cell(3,3));ok('拖到已点亮格不扣费',S.jade===paid);
 S.deck[3][0]={type:'shovel',x:1.5,y:1.5,z:3};G.renderAll();
 drag(d.querySelector('.gcard[data-ci="3"][data-i="0"]'),cell(0,0));ok('牌堆铲子无效落点不消耗',S.deck[3][0]!==null);
 drag(d.querySelector('.gcard[data-ci="3"][data-i="0"]'),cell(2,2));ok('牌堆铲子只解锁指定目标',!S.board[12].locked&&S.deck[3][0]===null);ok('牌堆铲子不额外花灵玉',S.jade===paid);
 reset();S.deck[3][0]={type:'shovel',x:1.5,y:1.5,z:3};G.renderAll();click(d.querySelector('.gcard[data-ci="3"][data-i="0"]'));ok('点击牌堆铲子先等待选择目标',!!S.shovelSource&&S.deck[3][0]!==null);click(cell(4,3));ok('触屏点选铲子也能定点解锁',!S.board[23].locked&&S.deck[3][0]===null);
 reset();G.placeUnit('火');G.startWave();const battleJade=S.jade;drag(d.querySelector('#btnShovel'),cell(4,4));ok('战斗中拖铲子不解锁不扣费',S.board[24].locked&&S.jade===battleJade);
 // 神兽的单字可拆出交换；吞噬仅允许三星以上，星级保留至本局结束。
 const activeDragon=()=>{reset();S.board.forEach(c=>{c.locked=false;});G.placeBeastChar('青');G.placeBeastChar('龙');drag(beastSlot(0),cell(0,0));drag(beastSlot(1),cell(0,1));};
 const piece=(part)=>cell(0,0).querySelector('.beast-piece[data-part="'+part+'"]');
 activeDragon();ok('神兽无拆字按钮',!d.querySelector('.split-beast'));drag(piece(1),cell(1,1));ok('拖动拆解保留青与龙两个字',S.board[0].unit.ch==='青'&&S.board[6].unit.ch==='龙'&&S.board[0].unit.beastChar&&S.board[6].unit.beastChar);
 ok('拆解立即移除激活增益与占位',S.beastUnits.length===0&&G.activeBuff('attack')===1&&!S.board[1].unit);
 G.checkBeast();ok('分离后的神兽字不会自动重组',S.beastUnits.length===0);
 drag(cell(1,1),cell(0,1));ok('残字重新横排可以再次激活',S.beastUnits.length===1);
 activeDragon();G.startWave();drag(piece(1),cell(1,1));ok('战斗中拖走神兽右半字可拆解',S.board[6].unit.ch==='龙'&&S.board[0].unit.ch==='青'&&!S.board[1].unit);
 ok('战斗拆解不保留幽灵增益',S.beastUnits.length===0&&G.activeBuff('attack')===1);
 drag(cell(1,1),cell(0,1));ok('战斗中重组仍能激活',S.beastUnits.length===1);
 S.board[5].unit={ch:'火',cd:.7};G.renderAll();drag(cell(1,0),piece(0));ok('低星字拖到神兽上按单字交换',S.board[0].unit.ch==='火'&&S.board[5].unit.ch==='青'&&S.board[1].unit.ch==='龙'&&S.beastUnits.length===0);
 activeDragon();drag(piece(0),piece(1));ok('神兽两半可以直接交换成龙青',S.board[0].unit.ch==='龙'&&S.board[1].unit.ch==='青'&&S.beastUnits.length===0);
 activeDragon();S.board[5].unit={ch:'焱',cd:0};G.renderAll();const seededRandom=w.Math.random;w.Math.random=()=>0;
 drag(cell(1,0),piece(1));ok('三星字可喂到神兽右半并消耗',!S.board[5].unit&&S.board[0].unit.star===2&&S.beastUnits[0].star===2);
 ok('神兽升星增益同步增强',G.activeBuff('attack')>1.2&&cell(0,0).querySelector('.lv').textContent==='★★');
 S.board[5].unit={ch:G.CHAINS['水'][3],cd:0};G.renderAll();drag(cell(1,0),piece(0));ok('四星字同样可以吞噬',!S.board[5].unit&&S.board[0].unit.star===3);
 w.Math.random=()=>.99;S.board[5].unit={ch:'淼',cd:0};G.renderAll();drag(cell(1,0),piece(0));ok('吞噬失败消耗材料但不降星',!S.board[5].unit&&S.board[0].unit.star===3);
 drag(piece(1),cell(1,1));drag(cell(1,1),cell(0,1));ok('拆解重组保留神兽星级',S.board[0].unit.star===3&&S.beastUnits[0].star===3);
 w.Math.random=()=>0;for(let n=0;n<2;n++){S.board[5].unit={ch:'焱',cd:0};G.renderAll();drag(cell(1,0),piece(0));}ok('神兽升星上限为五星',S.board[0].unit.star===5);
 S.board[5].unit={ch:'焱',cd:0};G.renderAll();drag(cell(1,0),piece(1));ok('满星后不再消耗三星材料',S.board[5].unit.ch==='焱'&&S.board[0].unit.star===5);
 w.Math.random=seededRandom;
 activeDragon();G.startWave();S.board[5].unit={ch:'焱',cd:0};G.renderAll();w.Math.random=()=>0;drag(cell(1,0),piece(0));w.Math.random=seededRandom;ok('战斗中允许神兽吞噬升星',!S.board[5].unit&&S.board[0].unit.star===2);
 S.phase='over';S.board[5].unit={ch:'焱',cd:0};G.renderAll();drag(cell(1,0),piece(0));ok('结算后不能吞噬材料',S.board[5].unit.ch==='焱'&&S.board[0].unit.star===2);
 G.restartGame();ok('重开恢复初始30灵玉且不重复发答题奖励',S.jade===30);ok('重开清空异兽',S.beastUnits.length===0&&S.beastSlots.every(x=>x===null));ok('重开清除神兽升星进度',Object.keys(S.beastProgress).length===0);ok('重开恢复五个槽',S.slots.length===5);ok('重开恢复三点生命',S.hp===3);ok('重开恢复五格',open().length===5);ok('重开清空统计',S.stats.kills===0&&S.stats.spent===0);
 reset();G.placeUnit('火');G.renderAll();click(d.querySelector('#fight'));ok('出战进入战斗',S.phase==='battle'&&S.wave===1);ok('出战隐藏备战界面状态',d.querySelector('#app').dataset.phase==='battle');
 ok('首波按配置出怪',S.spawnLeft===6);before=remaining();G.clickCard(3,0);ok('战斗不能取牌',remaining()===before);ok('战斗不能新增暂存牌',!G.addToSlot('金'));
 const balance=S.jade;click(d.querySelector('#btnRefresh'));ok('战斗禁止消费',S.jade===balance);click(d.querySelector('#speed'));ok('二倍速可切换',S.speed===2);click(d.querySelector('#speed'));ok('恢复一倍速',S.speed===1);
 S.enemies=[{x:-.4,y:.5,hp:1,maxHp:1,slow:1,seg:0,t:0}];G.towerAttack(1);ok('单位能攻击击杀真实范围内目标',S.stats.kills===1&&S.enemies.length===0);
 S.spawnLeft=0;G.checkWaveEnd();ok('波结束回到备战',S.phase==='prep');ok('波结束保留棋盘',S.board.some(c=>c.unit));ok('波结束补充牌墙',remaining()===60);ok('波结束多开一格',open().length===6);
 S.phase='battle';S.wave=12;S.spawnLeft=0;S.enemies=[];G.checkWaveEnd();ok('第十二波完成胜利结算',S.phase==='over'&&!!d.querySelector('#restartGame'));ok('结算不强制跳走',!S.reported);click(d.querySelector('#restartGame'));ok('结算按钮真实重开',S.phase==='prep'&&S.wave===0&&!d.querySelector('.overlay'));
 reset();G.placeUnit('火');G.startWave();S.hp=1;S.enemies=[{type:'妖兵',x:2.5,y:-.55,seg:4,t:0,speed:1,slow:1,dmg:1,hp:10}];G.moveEnemies(.1);ok('漏怪耗尽生命触发失败',S.hp===0&&S.phase==='over');
 ok('全过程无脚本异常',errors.length===0);
 console.log('\nPASS '+count+' / FAIL 0');
 }catch(e){console.error(e);process.exitCode=1;}finally{dom.window.close();}
},20);
