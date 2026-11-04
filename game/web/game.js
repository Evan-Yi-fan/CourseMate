/* CourseMate · 灵玉秘境
 *
 * 结构（对照原作截图与攻略文章）：
 *   顶部信息栏 → 棋盘（左侧竖排神兽槽）→ 暂存格 → 叠层牌堆 → 底部操作栏
 *
 * 规则要点：
 *   - 四层字牌按实际矩形遮挡判定可取，下层随取牌逐步露出；
 *   - 暂存格同字满 3 张合成"该字本身"，落到棋盘；
 *   - 棋盘上两个同级同字合并升阶（火→炎→焱）；
 *   - 神兽：神兽残字先入神兽槽，拖到棋盘按青龙/白虎横向相邻顺序才激活；
 *   - 妖怪从左侧进入，绕棋盘一圈扑向人皇。
 */
(function () {
  'use strict';

  const CFG = Object.assign({
    jade: 30, initialJade: 30, hp: 10, boardSize: 5, slots: 5, waves: 3,
    enemiesPerWave: [6, 8, 10],
    randomUnlock: true, unlockCount: 5,
    shop: [], courseName: '', initialLayout: 'edge', beastCardsMax: 2, cardMaxLevel: 4,
    beastMaxStars: 5, beastEatChance: .55, beastStarBuffStep: .15,
  }, window.CM_CONFIG || {});

  // ---------------------------------------------------------------- 字与阶
  // 只保留五行基础字，每行最高四阶（生僻字照用）：
  //   金→鍂→鑫　木→林→森　水→沝→淼　日→昍→晶　火→炎→焱　土→圭→垚
  const CHAINS = {
    金: ['金', '鍂', '鑫'],
    木: ['木', '林', '森'],
    水: ['水', '沝', '淼'],
    日: ['日', '昍', '晶'],
    火: ['火', '炎', '焱'],
    土: ['土', '圭', '垚'],
  };
  const BASE_CHARS = Object.keys(CHAINS);
  const FOUR_GLYPHS={金:'𨰻',木:'𣛧',水:'㵘',日:'𣊭',火:'燚',土:'㙓'};
  BASE_CHARS.forEach(base=>CHAINS[base].push(FOUR_GLYPHS[base]));
  const LEVEL_OF = {};
  BASE_CHARS.forEach((base) => {
    CHAINS[base].forEach((ch, i) => { LEVEL_OF[ch] = { base, lv: i + 1 }; });
  });

  const BASE_UNITS = {
    日: { dmg: 7, range: 2.8, rate: 0.9, color: '#9b302c', style: '日光灼击' },
    金: { dmg: 6, range: 2.6, rate: 1.0, color: '#82713c', style: '穿透单体' },
    木: { dmg: 4, range: 2.8, rate: 1.2, color: '#4c7144', style: '范围缠绕' },
    水: { dmg: 4, range: 2.5, rate: 1.0, color: '#286880', style: '减速', slow: 0.55 },
    火: { dmg: 7, range: 2.0, rate: 1.1, color: '#a44631', style: '爆发单体' },
    土: { dmg: 3, range: 1.9, rate: 0.8, color: '#756044', style: '溅射' },
  };

  const BEAST_CHARS = ['青', '龙', '白', '虎'];
  const BEASTS = [
    { name: '青龙', chars: ['青', '龙'], buff: '全体攻击 +20%',
      unit: { dmg: 34, range: 3.2, rate: 0.9, color: '#26c6da', style: '横跨两格·龙息' } },
    { name: '白虎', chars: ['白', '虎'], buff: '全体攻速 +15%',
      unit: { dmg: 26, range: 2.8, rate: 1.5, color: '#eceff1', style: '横跨两格·扑杀' } },
  ];

  const ENEMY = {
    妖兵: { hp: 26, speed: 0.62, dmg: 1, color: '#8e24aa' },
    妖将: { hp: 62, speed: 0.46, dmg: 2, color: '#6a1b9a' },
    妖王: { hp: 130, speed: 0.34, dmg: 3, color: '#4a148c' },
  };

  // 左侧进入 → 沿下边 → 右边 → 向上扑向人皇
  const PATH = [
    [-0.7, -0.4], [-0.7, 5.7], [5.7, 5.7], [5.7, -0.7], [2.5, -0.7],
  ];

  // 配置同时驱动显示和扣费，避免两者不一致。
  const PRICE = Object.fromEntries(CFG.shop.map(item => [item.id, item.price]));

  // ---------------------------------------------------------------- 状态
  const S = {
    jade: CFG.jade | 0, hp: CFG.hp | 0, maxHp: CFG.hp | 0,
    wave: 0, phase: 'prep',
    board: [], slots: [], deck: [],
    beastSlots: [null, null], beastUnits: [], beastProgress: {},
    enemies: [], autoMerge: true,
    log: [], shopUsed: {},
    stats: { kills: 0, leaked: 0, merges: 0, spent: 0, spawned: 0 },
    spawnLeft: 0, spawnTimer: 0,
    cellsize: 60, originX: 0, originY: 0, reported: false, speed: 1, selected: null, shovelSource: null,
  };

  const $ = (s) => document.querySelector(s);
  const el = (tag, cls, html) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (html != null) n.innerHTML = html;
    return n;
  };

  // ---------------------------------------------------------------- 初始化
  function init() {
    buildBoard();
    S.slots = new Array(CFG.slots).fill(null);
    refreshDeck();
    bindButtons();
    renderAll();
    loop(performance.now());
    toast('先取未被遮挡的牌，三个同字合一后上阵。');
  }

  function buildBoard() {
    const n = CFG.boardSize;
    S.board = [];
    for (let r = 0; r < n; r++) {
      for (let c = 0; c < n; c++) S.board.push({ r, c, locked: true, unit: null });
    }
    randomUnlock(CFG.unlockCount || 5);
  }

  /** 开局随机放开"连在一起"的 N 格（偏向左侧，靠近妖怪来路）。 */
  function randomUnlock(count) {
    const n=CFG.boardSize;
    // 从任意边缘起步，在外侧两圈生长，保证五格相连、靠边且布局有变化。
    const edge=S.board.filter(c=>c.r===0||c.c===0||c.r===n-1||c.c===n-1);
    const first=edge[Math.floor(Math.random()*edge.length)];
    const picked=[first],seen=new Set([first.r+','+first.c]);
    while(picked.length<Math.min(count,n*n)) {
      const choices=new Map();
      picked.forEach(p=>[[p.r-1,p.c],[p.r+1,p.c],[p.r,p.c-1],[p.r,p.c+1]].forEach(([r,c])=>{
        const k=r+','+c;
        if(r<0||c<0||r>=n||c>=n||seen.has(k))return;
        if(Math.min(r,c,n-1-r,n-1-c)>1)return;
        choices.set(k,S.board[r*n+c]);
      }));
      const pool=[...choices.values()];if(!pool.length)break;
      const next=pool[Math.floor(Math.random()*pool.length)];
      seen.add(next.r+','+next.c);picked.push(next);
    }
    picked.forEach(c=>{c.locked=false;});
  }

  const cellAt=(r,c)=>Number.isInteger(r)&&Number.isInteger(c)&&r>=0&&c>=0&&r<CFG.boardSize&&c<CFG.boardSize ? S.board[r*CFG.boardSize+c] : null;

  function ownsBeastChar(ch) {
    return S.beastSlots.includes(ch)||S.board.some(c=>c.unit&&c.unit.beastChar&&c.unit.ch===ch)||
      S.beastUnits.some(unit=>BEASTS.find(b=>b.name===unit.name).chars.includes(ch));
  }


  function makeCard() {
    const r = Math.random();
    if (r < 0.07) return { type: 'shovel' };
    return { type: 'normal', ch: BASE_CHARS[(Math.random() * BASE_CHARS.length) | 0] };
  }

  /** 四层牌墙：底层7×4，逐层内缩，顶层4张。 */
  function refreshDeck() {
    // 真正的多层牌墙：上层牌覆盖下层的一部分，拿走后逐渐露出。
    S.shovelSource=null;S.selected=null;
    S.deck = [];
    [[7,4,0,0],[6,3,.5,.5],[5,2,1,1],[4,1,1.5,1.5]].forEach(([cols,rows,ox,oy],z) => {
      const layer = [];
      for (let y=0;y<rows;y++) for (let x=0;x<cols;x++) {
        layer.push(Object.assign(makeCard(), {x:x+ox,y:y+oy,z}));
      }
      S.deck.push(layer);
    });
    // 每副牌统一抽取0到2个不重复残字，已持有或已激活的字不再生成。
    const available=BEAST_CHARS.filter(ch=>!ownsBeastChar(ch));
    const count=Math.min(Math.floor(Math.random()*(CFG.beastCardsMax+1)),available.length);
    const positions=S.deck.flat();
    for(let i=0;i<count;i++) {
      const index=Math.floor(Math.random()*available.length),ch=available.splice(index,1)[0];
      const pos=Math.floor(Math.random()*positions.length),card=positions.splice(pos,1)[0];
      card.type='beast';card.ch=ch;
    }
  }

  function isCardFree(ci, i) {
    const card = S.deck[ci] && S.deck[ci][i];
    if (!card) return false;
    return !S.deck.some((layer,z) => z>ci && layer.some(other => other &&
      Math.abs(other.x-card.x)<.99 && Math.abs(other.y-card.y)<.99));
  }


  function topIndex(col) {
    for (let i = 0; i < col.length; i++) if (col[i]) return i;
    return -1;
  }

  // ---------------------------------------------------------------- 渲染
  function renderAll() {
    renderTop(); renderBoard(); renderBeasts(); renderSlots(); renderDeck();
  }

  function renderTop() {
    $('#wave').textContent = `${Math.max(1,S.wave)}/${CFG.waves}`;
    $('#app').dataset.phase = S.phase;
    $('#app').dataset.tool=S.shovelSource?'shovel':'';
    $('#hearts').textContent = '♥ '.repeat(Math.max(0,S.hp)) + '♡ '.repeat(Math.max(0,S.maxHp-S.hp));
    $('#danger').textContent = S.hp <= 1 ? '危 · 守住最后防线' : '守卫人皇';
    $('#hp').textContent = S.hp;
    $('#jade').textContent = S.jade;
    $('#phase').textContent = S.phase === 'prep' ? '布阵' : S.phase === 'battle' ? '战斗中' : '结算';
    $('#fight').textContent = S.phase === 'battle' ? '战斗中…' : `出战`;
    $('#fight').disabled = S.phase !== 'prep';
    const total=CFG.enemiesPerWave[S.wave-1] || 6;
    $('#wavecards').textContent = `妖怪：${Math.max(0,total-S.spawnLeft-S.enemies.length)} / ${total}`;
    $('#waveProgress').style.width = (Math.max(0,total-S.spawnLeft-S.enemies.length)/total*100)+'%';
  }

  function isPlaying() { return S.phase==='prep'||S.phase==='battle'; }

  function glyphHTML(ch) {
    // 四木固定成紧凑田字形字形；不依赖各系统对扩展汉字的字体替换。
    if(ch===FOUR_GLYPHS.木){
      const wood='M23 3 L27 3 L27 19 L45 19 L45 23 L30 23 Q35 34 47 41 L44 45 Q32 37 27 28 L27 48 L23 48 L23 29 Q16 40 5 46 L2 42 Q15 34 20 23 L5 23 L5 19 L23 19 Z';
      return '<svg class="ch four-glyph wood-glyph" viewBox="0 0 100 100" role="img" aria-label="四星木，四木田字形"><path fill="currentColor" d="'+wood+'"/><path fill="currentColor" transform="translate(50 0)" d="'+wood+'"/><path fill="currentColor" transform="translate(0 50)" d="'+wood+'"/><path fill="currentColor" transform="translate(50 50)" d="'+wood+'"/></svg>';
    }
    const meta=LEVEL_OF[ch];
    if(meta&&meta.lv===4)return '<span class="ch four-glyph" aria-label="四星'+meta.base+'">'+ch+'</span>';
    return '<span class="ch">'+ch+'</span>';
  }

  function beastAnchor(cell) {
    if(!cell||!cell.unit)return null;
    if(cell.unit.beast)return cell;
    if(cell.unit.covered){const left=cellAt(cell.r,cell.c-1);return left&&left.unit&&left.unit.beast?left:null;}
    return null;
  }

  function unitInfo(ch) {
    if(BEAST_CHARS.includes(ch)) return {lv:0,dmg:0,range:0,rate:1,color:'#75417b',style:'神兽残字，横向按顺序组合后激活'};
    const meta = LEVEL_OF[ch];
    const base = BASE_UNITS[meta.base];
    const mult = 1 + (meta.lv - 1) * 0.9;
    return {
      dmg: +(base.dmg * mult).toFixed(1),
      range: base.range + (meta.lv - 1) * 0.2,
      rate: base.rate, color: base.color,
      style: base.style + (meta.lv > 1 ? `（${meta.lv} 阶）` : ''),
      slow: base.slow, lv: meta.lv,
    };
  }

  function renderBoard() {
    const board = $('#board');
    board.style.gridTemplateColumns = `repeat(${CFG.boardSize}, 1fr)`;
    board.innerHTML = '';
    S.board.forEach((cell) => {
      const d = el('div', 'cell');
      d.dataset.r=cell.r;d.dataset.c=cell.c;
      if (cell.locked) {
        d.className = 'cell locked';
        d.textContent = '';
        d.title = '封锁格：铲子或通关解锁';
      } else if (!cell.unit) {
        d.className = 'cell empty';
        d.title = '空地：点暂存格里的字放下来';
      } else if (cell.unit.covered) {
        d.className = 'cell covered-cell';
        d.title = '被神兽占据';
      } else {
        const u = cell.unit;
        const info = u.beast
          ? Object.assign({ lv: u.star || 1 }, BEASTS.find((b) => b.name === u.ch).unit)
          : unitInfo(u.ch);
        const spanCls = u.span === 2 ? ' span2' : '';
        d.innerHTML = `<div class="unit${spanCls}${u.beastChar ? ' beast-fragment' : ''}" style="border-color:${info.color}66;color:${info.color}">
            ${u.beast ? '<div class="beast-parts">'+BEASTS.find(b=>b.name===u.ch).chars.map((ch,part)=>'<span class="beast-piece" data-part="'+part+'" data-r="'+cell.r+'" data-c="'+(cell.c+part)+'" role="button" tabindex="0" aria-label="拖动'+ch+'拆解神兽">'+ch+'</span>').join('')+'</div>' : glyphHTML(u.ch)}
            <div class="lv">${'★'.repeat(info.lv)}</div>
            <div class="cd"><i></i></div>
          </div>`;
        d.title = `${u.ch}：${info.style}｜伤害 ${info.dmg}`;
        if(u.beast) {
          d.title+='｜拖动单字可拆分，三星及以上字拖来吞噬';
          d.querySelectorAll('.beast-piece').forEach(piece=>{
            const source={from:'beast-part',r:cell.r,c:cell.c,part:+piece.dataset.part};
            bindDragSource(piece,source);bindDropTarget(piece,{from:'board',r:cell.r,c:cell.c+source.part});
            const select=e=>{
              e.stopPropagation();if(!isPlaying())return;
              if(S.selected){const previous=S.selected;S.selected=null;handleDrop(previous,{from:'board',r:cell.r,c:cell.c+source.part});}
              else {S.selected=source;toast('点目标格移动这半个神兽字，或拖走拆分');}
              renderAll();
            };
            piece.addEventListener('click',select);
            piece.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();select(e);}});
          });
        }
      }
      if (S.selected && S.selected.from==='board' && S.selected.r===cell.r && S.selected.c===cell.c) d.classList.add('selected');
      d.tabIndex = cell.locked && !S.shovelSource ? -1 : 0;
      d.setAttribute('role','button');
      d.setAttribute('aria-label', cell.locked ? '封锁格' : (cell.unit && cell.unit.ch || '空地'));
      bindCellEvents(d, cell);
      board.appendChild(d);
    });
    measureBoard();
    renderEnemies();
  }

  function measureBoard() {
    const b = $('#board');
    const wrap = $('#boardWrap');
    if (!b || !wrap) return;
    const rb = b.getBoundingClientRect();
    const rw = wrap.getBoundingClientRect();
    S.cellsize = rb.width / CFG.boardSize;
    S.originX = rb.left - rw.left;
    S.originY = rb.top - rw.top;
    const road=$('.road');
    road.setAttribute('viewBox','-1 -1 7 7');
    // 绘制与行走共用同一条折线，左上入口到人皇之间保持断开。
    road.querySelectorAll('polyline').forEach(line=>line.setAttribute('points',PATH.map(p=>p.join(',')).join(' ')));
  }

  function renderSlots() {
    const wrap = $('#slots'); wrap.innerHTML = '';
    S.slots.forEach((slot,i) => {
      const d=el('div','slot'+(slot?' filled':''));
      d.tabIndex=0; d.setAttribute('role','button');
      d.setAttribute('aria-label',slot ? '暂存字牌 '+slot.ch : '空暂存格');
      if (slot) {
        d.innerHTML=glyphHTML(slot.ch);
        if (LEVEL_OF[slot.ch]) d.style.color=BASE_UNITS[LEVEL_OF[slot.ch].base].color;
        d.title=slot.ready?'已合成字，点击重新上阵':'集齐三个同字后点击合成';
        d.addEventListener('click',()=>onSlotClick(i));
        d.addEventListener('keydown',e=>{ if(e.key==='Enter'||e.key===' ') {e.preventDefault();onSlotClick(i);} });
      }
      wrap.appendChild(d);
    });
    const price=PRICE.slot;
    $('#expandSlots').innerHTML=S.slots.length>=7 ? '满<small>七格</small>' : '＋<small>'+price+' 灵玉</small>';
    $('#expandSlots').disabled=S.slots.length>=7;
  }


  function renderDeck() {
    const deck=$('#deck'); deck.innerHTML='';
    S.deck.forEach((layer,ci)=>layer.forEach((card,i)=>{
      if(!card) return;
      const free=isCardFree(ci,i);
      const d=el('div','gcard '+(free?'top':'blocked')+' '+card.type);
      if(card.type==='shovel'&&free) bindDragSource(d,{from:'shovel',ci,i});
      d.textContent=card.type==='shovel'?'铲':card.ch;
      if(card.type==='normal' && LEVEL_OF[card.ch]) d.style.color=BASE_UNITS[LEVEL_OF[card.ch].base].color;
      d.style.left=card.x/7*100+'%'; d.style.top=card.y/4.08*100+'%'; d.style.zIndex=10+card.z;
      d.dataset.ci=ci; d.dataset.i=i; d.setAttribute('role','button');
      d.setAttribute('aria-disabled',String(!free)); d.tabIndex=free?0:-1;
      d.title=free?'取这张字牌':'被上层牌遮挡';
      d.addEventListener('click',()=>clickCard(ci,i));
      d.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();clickCard(ci,i);}});
      deck.appendChild(d);
    }));
  }


  function renderBeasts() {
    const wrap=$('#beasts');wrap.innerHTML='';
    S.beastSlots.forEach((ch,i)=>{
      const d=el('div','beast-cell'+(ch?' filled':'')+(S.selected&&S.selected.from==='beast'&&S.selected.i===i?' selected':''));
      d.dataset.bi=i;d.textContent=ch||'';d.tabIndex=0;d.setAttribute('role','button');
      d.setAttribute('aria-label','神兽槽 '+(i+1)+(ch?' '+ch:' 空'));
      d.title=ch?'拖到空棋盘，横排青龙或白虎才激活':'空神兽槽';
      if(ch)bindDragSource(d,{from:'beast',i});
      const activate=()=>{
        if(S.phase!=='prep')return;
        S.shovelSource=null;
        if(S.selected){const source=S.selected;S.selected=null;handleDrop(source,{from:'beast',i});}
        else if(ch){S.selected={from:'beast',i};toast('点空棋盘放下残字，或拖动到目标格');}
        renderAll();
      };
      d.addEventListener('click',activate);
      d.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();activate();}});
      bindDropTarget(d,{from:'beast',i});wrap.appendChild(d);
    });
  }


  function renderEnemies() {
    const layer = $('#enemyLayer');
    if (!layer) return;
    layer.innerHTML = '';
    S.enemies.forEach((e) => {
      const d = el('div', 'enemy'+(e.type==='妖将'?' elite':e.type==='妖王'?' boss':''));
      d.style.background = e.color;
      d.style.left = (S.originX + e.x * S.cellsize) + 'px';
      d.style.top = (S.originY + e.y * S.cellsize) + 'px';
      d.innerHTML = `<div class="hpbar"><i style="width:${Math.max(0, e.hp / e.maxHp) * 100}%"></i></div>${e.label}`;
      e.node = d;
      layer.appendChild(d);
    });
  }

  function updateEnemyPositions() {
    S.enemies.forEach((e) => {
      if (!e.node) return;
      e.node.style.left = (S.originX + e.x * S.cellsize) + 'px';
      e.node.style.top = (S.originY + e.y * S.cellsize) + 'px';
      const bar = e.node.querySelector('.hpbar i');
      if (bar) bar.style.width = Math.max(0, e.hp / e.maxHp) * 100 + '%';
    });
  }

  function updateCooldownBars() {
    const units = S.board.filter((c) => !c.locked && c.unit && !c.unit.covered && !c.unit.beastChar);
    document.querySelectorAll('.cell .unit:not(.beast-fragment) .cd i').forEach((bar, idx) => {
      const cell = units[idx];
      if (!cell || !cell.unit) return;
      const info = cell.unit.beast
        ? BEASTS.find((b) => b.name === cell.unit.ch).unit
        : unitInfo(cell.unit.ch);
      bar.style.width = Math.min(1, 1 - cell.unit.cd / (1 / info.rate)) * 100 + '%';
    });
  }

  // ---------------------------------------------------------------- 取卡
  function clickCard(ci, i) {
    if (S.phase !== 'prep') return;
    const col = S.deck[ci];
    if (!col || !col[i]) return;
    if (!isCardFree(ci,i)) {
      const node = document.querySelector('.gcard[data-ci="' + ci + '"][data-i="' + i + '"]');
      if (node) { node.style.transform = 'translateX(-5px)'; setTimeout(() => { node.style.transform = ''; }, 120); }
      toast('这张被上面的压住了，先取上面那张');
      return;
    }
    const card = col[i];
    if (card.type === 'shovel') {
      armShovel({from:'shovel',ci,i});return;
    } else if (card.type === 'beast') {
      if (!placeBeastChar(card.ch)) return;
    } else if (!addToSlot(card.ch)) return;

    col[i] = null;
    renderDeck(); renderSlots(); renderBoard(); renderBeasts(); renderTop();
  }

  function addToSlot(ch) {
    if(S.phase!=='prep') return false;
    const idx=S.slots.indexOf(null);
    if(idx<0){ toast('暂存格已满，合成或扩展后再取牌');return false; }
    S.slots[idx]={ch,count:1};
    if(S.autoMerge) mergeSlot(idx);
    return true;
  }

  function mergeSlot(idx) {
    const slot=S.slots[idx]; if(!slot) return false;
    const same=S.slots.map((v,i)=>v&&!v.ready&&v.ch===slot.ch?i:-1).filter(i=>i>=0);
    if(same.length<3) return false;
    // 先确认能落子再消耗三张，棋盘满时保留所有牌。
    if(!placeUnit(slot.ch)){toast('棋盘已满，先合成棋盘上的同阶字');return false;}
    same.slice(0,3).forEach(i=>{S.slots[i]=null;}); S.stats.merges++;
    toast('三字归一：「'+slot.ch+'」已上阵'); return true;
  }

  function onSlotClick(idx) {
    if(S.phase!=='prep') return;
    if(S.slots[idx]&&S.slots[idx].ready){
      if(placeUnit(S.slots[idx].ch)) S.slots[idx]=null;
      else toast('棋盘没有空位');
      renderSlots();renderBoard();return;
    }
    if(!mergeSlot(idx)) toast('暂存格集齐三个相同字，才能合成上阵');
    renderSlots();renderBoard();
  }


  function placeUnit(ch) {
    const free = S.board.filter((c) => !c.locked && !c.unit);
    if (!free.length) return false;
    free.sort((a, b) => (a.c + a.r * 0.1) - (b.c + b.r * 0.1));
    free[0].unit = { ch, cd: 0 };
    return true;
  }

  // ---------------------------------------------------------------- 棋盘合并
  function tryMerge(aCell, bCell) {
    const a = aCell.unit, b = bCell.unit;
    if(!isPlaying()||aCell===bCell||!a||!b||a.beast||b.beast||a.beastChar||b.beastChar)return false;
    const ma = LEVEL_OF[a.ch], mb = LEVEL_OF[b.ch];
    if (!ma || !mb || ma.base !== mb.base || ma.lv !== mb.lv) return false;
    const chain = CHAINS[ma.base];
    if (ma.lv >= Math.min(CFG.cardMaxLevel,chain.length)) { toast('「' + a.ch + '」已是最高阶'); return false; }
    bCell.unit = { ch: chain[ma.lv], cd: 0 };
    aCell.unit = null;
    S.stats.merges += 1;
    toast(`合成：${a.ch} + ${a.ch} → ${chain[ma.lv]}`);
    return true;
  }

  function splitBeast(cell) {
    if(!isPlaying())return false;
    const anchor=beastAnchor(cell);if(!anchor)return false;
    const u=anchor.unit,beast=BEASTS.find(b=>b.name===u.ch),right=cellAt(anchor.r,anchor.c+1);
    if(!right)return false;
    // 星级保存在本局神兽进度里，拆解或重组既不清零，也不叠加一份增益。
    S.beastProgress[u.ch]=u.star||1;
    S.beastUnits=S.beastUnits.filter(b=>b.name!==u.ch);
    anchor.unit={ch:beast.chars[0],beastChar:true,cd:0};
    right.unit={ch:beast.chars[1],beastChar:true,cd:0};
    return true;
  }

  function feedBeast(source,target) {
    const anchor=beastAnchor(target),meta=source&&source.unit&&LEVEL_OF[source.unit.ch];
    if(!isPlaying()||!anchor||!meta||meta.lv<3)return false;
    const beast=anchor.unit;
    if(beast.star>=CFG.beastMaxStars){toast('神兽已满星，不消耗这张字');return false;}
    source.unit=null;
    const upgraded=Math.random()<CFG.beastEatChance;
    if(upgraded)beast.star++;
    S.beastProgress[beast.ch]=beast.star;
    const active=S.beastUnits.find(b=>b.name===beast.ch);if(active)active.star=beast.star;
    toast(beast.ch+' 吞噬'+meta.lv+'星字：'+(upgraded?'升至'+beast.star+'星':'本次未升星'));
    return true;
  }

  function moveUnit(r1,c1,r2,c2) {
    const a=cellAt(r1,c1),b=cellAt(r2,c2);
    if(!isPlaying()||!a||!b||a===b||a.locked||b.locked||!a.unit)return false;
    const targetBeast=beastAnchor(b),sourceMeta=LEVEL_OF[a.unit.ch];
    if(targetBeast&&sourceMeta&&sourceMeta.lv>=3) {
      const fed=feedBeast(a,b);if(fed)renderAll();return fed;
    }
    // 先把参与移动的神兽还原为两个原字，再按实际目标格交换或合并。
    // 拖动同一神兽的两半可直接反序，不能出现覆盖占位残留。
    const sourceBeast=beastAnchor(a);
    if(sourceBeast)splitBeast(sourceBeast);
    if(targetBeast&&targetBeast!==sourceBeast)splitBeast(targetBeast);
    if(a.unit)delete a.unit.dormant;if(b.unit)delete b.unit.dormant;
    if(!b.unit||!tryMerge(a,b)){const unit=a.unit;a.unit=b.unit;b.unit=unit;}
    checkBeast();renderAll();return true;
  }


  function armShovel(source) {
    if(S.phase!=='prep')return false;
    if(!S.board.some(c=>c.locked)){toast('棋盘已全部解锁');return false;}
    if(source.from==='shop'&&S.jade<PRICE.shovel){toast('灵玉不足');return false;}
    S.selected=null;
    S.shovelSource=JSON.stringify(S.shovelSource)===JSON.stringify(source)?null:source;
    renderAll();toast(S.shovelSource?'把铲子拖到封锁格，或点选要点亮的格子':'已取消铲子');return true;
  }

  function useShovel(cell,source=S.shovelSource) {
    if(S.phase!=='prep'||!cell||!S.board.includes(cell)||!cell.locked||!source)return false;
    if(source.from==='shop') {if(!pay(PRICE.shovel,'铲子'))return false;}
    else if(source.from==='shovel') {
      const card=S.deck[source.ci]&&S.deck[source.ci][source.i];
      if(!card||card.type!=='shovel'||!isCardFree(source.ci,source.i))return false;
      S.deck[source.ci][source.i]=null;
    }else return false;
    cell.locked=false;S.shovelSource=null;S.selected=null;
    toast('已点亮第'+(cell.r+1)+'行第'+(cell.c+1)+'列');renderAll();return true;
  }

  function placeBeastChar(ch) {
    if(S.phase!=='prep'||!BEAST_CHARS.includes(ch)||ownsBeastChar(ch))return false;
    const index=S.beastSlots.indexOf(null);
    if(index>=0)S.beastSlots[index]=ch;
    else {
      const free=S.board.find(c=>!c.locked&&!c.unit);
      if(!free){toast('神兽槽与棋盘都已满');return false;}
      free.unit={ch,cd:0,beastChar:true};checkBeast();
    }
    renderAll();return true;
  }

  function checkBeast() {
    if(!isPlaying())return;
    for(const left of S.board) {
      const right=cellAt(left.r,left.c+1);
      if(left.locked||!right||right.locked||!left.unit||!right.unit||!left.unit.beastChar||!right.unit.beastChar)continue;
      const beast=BEASTS.find(b=>b.chars[0]===left.unit.ch&&b.chars[1]===right.unit.ch);
      if(beast&&deployBeast(beast,left,right)){log(beast.name+' 横排激活');toast(beast.name+' 苏醒！'+beast.buff);}
    }
  }

  function deployBeast(beast,left,right) {
    if(!isPlaying()||!left||!right||left.locked||right.locked||left.r!==right.r||right.c!==left.c+1||
      !left.unit||!right.unit||!left.unit.beastChar||!right.unit.beastChar||
      left.unit.ch!==beast.chars[0]||right.unit.ch!==beast.chars[1]||S.beastUnits.some(b=>b.name===beast.name))return false;
    const star=S.beastProgress[beast.name]||1;
    left.unit={ch:beast.name,span:2,cd:0,beast:true,star};right.unit={covered:true};
    S.beastUnits.push({name:beast.name,star});return true;
  }

  function handleDrop(source,target) {
    if(!isPlaying()||!source||!target)return false;
    if(target.from==='board') {
      const cell=cellAt(target.r,target.c);
      if(source.from==='shovel'||source.from==='shop')return useShovel(cell,source);
      if(!cell||cell.locked)return false;
      if(source.from==='board')return moveUnit(source.r,source.c,target.r,target.c);
      if(source.from==='beast-part'){
        const anchor=cellAt(source.r,source.c);
        if(!anchor||!anchor.unit||!anchor.unit.beast||![0,1].includes(source.part))return false;
        return moveUnit(source.r,source.c+source.part,target.r,target.c);
      }
      if(S.phase!=='prep')return false;
      if(source.from==='beast'&&!cell.unit&&Number.isInteger(source.i)&&S.beastSlots[source.i]) {
        cell.unit={ch:S.beastSlots[source.i],beastChar:true,cd:0};S.beastSlots[source.i]=null;
        checkBeast();renderAll();return true;
      }
    }else if(S.phase==='prep'&&target.from==='beast'&&Number.isInteger(target.i)&&target.i>=0&&target.i<2) {
      if(source.from==='beast'&&Number.isInteger(source.i)&&source.i>=0&&source.i<2) {
        [S.beastSlots[source.i],S.beastSlots[target.i]]=[S.beastSlots[target.i],S.beastSlots[source.i]];
        renderAll();return true;
      }
      const cell=source.from==='board'&&cellAt(source.r,source.c);
      if(cell&&cell.unit&&cell.unit.beastChar&&!S.beastSlots[target.i]) {
        S.beastSlots[target.i]=cell.unit.ch;cell.unit=null;renderAll();return true;
      }
    }
    return false;
  }

  function bindDragSource(node,source) {
    node.draggable=true;
    let suppressClick=false,start=null;
    node.addEventListener('dragstart',e=>{
      if(!(S.phase==='prep'||(S.phase==='battle'&&['board','beast-part'].includes(source.from)))||(source.from==='shovel'&&!isCardFree(source.ci,source.i))){e.preventDefault();return;}
      S.selected=null;S.shovelSource=null;e.dataTransfer.setData('text/plain',JSON.stringify(source));
    });
    // 触屏浏览器不一定触发HTML drag/drop，统一在抬手时解析目标格。
    node.style.touchAction='none';
    node.addEventListener('pointerdown',e=>{if(e.pointerType==='mouse'||!(S.phase==='prep'||(S.phase==='battle'&&['board','beast-part'].includes(source.from))))return;start={x:e.clientX,y:e.clientY};node.setPointerCapture?.(e.pointerId);});
    node.addEventListener('pointerup',e=>{
      if(!start)return;const distance=Math.hypot(e.clientX-start.x,e.clientY-start.y);start=null;
      if(distance<8)return;suppressClick=true;setTimeout(()=>{suppressClick=false;},0);
      const target=document.elementFromPoint(e.clientX,e.clientY)?.closest('.beast-piece,.cell,.beast-cell');
      if(!target)return;
      const dest=(target.classList.contains('cell')||target.classList.contains('beast-piece'))?{from:'board',r:+target.dataset.r,c:+target.dataset.c}:{from:'beast',i:+target.dataset.bi};
      handleDrop(source,dest);
    });
    node.addEventListener('pointercancel',()=>{start=null;});
    node.addEventListener('click',e=>{if(suppressClick){e.preventDefault();e.stopImmediatePropagation();suppressClick=false;}},true);
  }

  function bindDropTarget(node,target) {
    node.addEventListener('dragover',e=>{if(isPlaying()){e.preventDefault();e.stopPropagation();node.classList.add('drag-over');}});
    node.addEventListener('dragleave',()=>node.classList.remove('drag-over'));
    node.addEventListener('drop',e=>{
      e.preventDefault();e.stopPropagation();node.classList.remove('drag-over');let source;
      try{source=JSON.parse(e.dataTransfer.getData('text/plain'));}catch(_){return;}
      S.selected=null;handleDrop(source,target);
    });
  }


  function bindButtons() {
    [['btnShovel', 'shovel', '铲子'], ['btnShuffle', 'shuffle', '打乱'],
     ['btnRefresh', 'refresh', '刷新']].forEach(([id, key, label]) => {
      $('#' + id).textContent = label + ' ' + PRICE[key];
    });
    $('#fight').addEventListener('click', startWave);
    $('#speed').addEventListener('click',()=>{ S.speed=S.speed===1?2:1; $('#speed').textContent=S.speed===1?'一倍速':'二倍速'; });
    $('#expandSlots').addEventListener('click',()=>{ if(S.slots.length>=7||!pay(PRICE.slot,'扩展暂存格'))return; S.slots.push(null);renderSlots(); });
    $('#help').addEventListener('click', showHelp);
    bindDragSource($('#btnShovel'),{from:'shop'});
    $('#btnShovel').addEventListener('click',()=>armShovel({from:'shop'}));
    document.addEventListener('keydown',e=>{if(e.key==='Escape'){S.selected=null;S.shovelSource=null;renderAll();}});
    $('#btnShuffle').addEventListener('click', function () {
      if (!pay(PRICE.shuffle, '打乱')) return;
      S.shovelSource=null;S.selected=null;
      const cards=S.deck.flat().filter(Boolean).map(card=>({type:card.type,ch:card.ch}));
      for(let i=cards.length-1;i>0;i--){const j=Math.floor(Math.random()*(i+1));[cards[i],cards[j]]=[cards[j],cards[i]];}
      S.deck.forEach(layer=>layer.forEach(card=>{if(card){const next=cards.pop();card.type=next.type;card.ch=next.ch;}}));
      toast('牌堆已打乱');
      renderAll();
    });
    $('#btnRefresh').addEventListener('click', function () {
      if (!pay(PRICE.refresh, '刷新')) return;
      refreshDeck(); toast('卡池已刷新'); renderAll();
    });
    $('#btnClear').addEventListener('click', clearBoard);
    const am = $('#autoMerge');
    if (am) {
      am.checked = S.autoMerge;
      am.addEventListener('change', function () { S.autoMerge = am.checked; });
    }
  }

  function pay(amount, what) {
    if(S.phase!=='prep') {toast('请在备战时操作');return false;}
    if(!Number.isFinite(amount)||amount<0) {toast('配置缺少该操作价格');return false;}
    if (S.jade < amount) { toast('灵玉不足（' + what + '需要 ' + amount + '）'); return false; }
    S.jade -= amount; S.stats.spent += amount;
    renderTop();
    return true;
  }

  function clearBoard() {
    if(S.phase!=='prep') return;
    const units = S.board.filter(function (c) { return c.unit && !c.unit.covered; });
    if (!units.length) { toast('棋盘上没有字'); return; }
    let moved = 0;
    units.forEach(function (cell) {
      if (cell.unit.beast) return;
      if(cell.unit.beastChar){const i=S.beastSlots.indexOf(null);if(i>=0){S.beastSlots[i]=cell.unit.ch;cell.unit=null;moved++;}return;}
      const free = S.slots.findIndex(function (s) { return s === null; });
      if (free === -1) return;
      S.slots[free] = { ch: cell.unit.ch, count: 1, ready: true };
      cell.unit = null;
      moved += 1;
    });
    toast('已撤回 ' + moved + ' 个字' + (moved < units.length ? '，其余放不下' : ''));
    renderAll();
  }

  // ---------------------------------------------------------------- 战斗
  function startWave() {
    if (S.phase !== 'prep') return;
    if(!S.board.some(c=>c.unit&&!c.unit.covered&&!c.unit.beastChar)){toast('先集齐三个同字上阵，再出战');return;}
    S.wave += 1;
    S.phase = 'battle';
    window.scrollTo({top:0,behavior:'smooth'});
    S.selected=null;S.shovelSource=null;
    S.spawnLeft = CFG.enemiesPerWave[S.wave - 1] || 6;
    S.spawnTimer = 0;
    log('第 ' + S.wave + ' 波开始，共 ' + S.spawnLeft + ' 只妖怪');
    renderTop();
    requestAnimationFrame(()=>{measureBoard();renderEnemies();});
  }

  function spawnEnemy() {
    const r = Math.random();
    let type = '妖兵';
    if (S.wave >= 2 && r < 0.3) type = '妖将';
    if (S.wave >= 3 && r < 0.12) type = '妖王';
    const base = ENEMY[type];
    const scale = 1 + (S.wave - 1) * 0.12;
    S.enemies.push({
      type: type, label: type==='妖兵'?'魍':type==='妖将'?'魉':'魁', hp: base.hp * scale, maxHp: base.hp * scale,
      speed: base.speed, dmg: base.dmg, color: base.color,
      x: PATH[0][0], y: PATH[0][1], seg: 0, t: 0, slow: 1,
    });
    S.stats.spawned += 1;
  }

  function moveEnemies(dt) {
    S.enemies.forEach(function (e) {
      e.slow = Math.min(1, e.slow + dt * 0.5);
      let remain = e.speed * e.slow * dt;
      while (remain > 0 && e.seg < PATH.length - 1) {
        const ax = PATH[e.seg][0], ay = PATH[e.seg][1];
        const bx = PATH[e.seg + 1][0], by = PATH[e.seg + 1][1];
        const segLen = Math.hypot(bx - ax, by - ay);
        const need = (1 - e.t) * segLen;
        if (remain >= need) { remain -= need; e.seg += 1; e.t = 0; }
        else { e.t += remain / segLen; remain = 0; }
      }
      if (e.seg >= PATH.length - 1) leak(e);
      else {
        const ax = PATH[e.seg][0], ay = PATH[e.seg][1];
        const bx = PATH[e.seg + 1][0], by = PATH[e.seg + 1][1];
        e.x = ax + (bx - ax) * e.t;
        e.y = ay + (by - ay) * e.t;
      }
    });
    S.enemies = S.enemies.filter(function (e) { if(e.dead&&e.node)e.node.remove();return !e.dead; });
  }

  function leak(e) {
    e.dead = true;
    S.hp -= e.dmg;
    S.stats.leaked += 1;
    toast(e.type + ' 突破防线，人皇 -' + e.dmg + ' 血');
    if (S.hp <= 0 && S.phase==='battle') {S.hp=0;endGame(false);}
    renderTop();
  }

  function towerAttack(dt) {
    const atk = activeBuff('attack');
    const rate = activeBuff('rate');
    S.board.forEach(function (cell) {
      if (cell.locked || !cell.unit || cell.unit.covered || cell.unit.beastChar) return;
      const u = cell.unit;
      const info = u.beast
        ? BEASTS.filter(function (b) { return b.name === u.ch; })[0].unit
        : unitInfo(u.ch);
      u.cd -= dt * rate;
      if (u.cd > 0) return;
      const cx = cell.c + (u.span === 2 ? 1.0 : 0.5), cy = cell.r + 0.5;
      const inRange = S.enemies.filter(function (e) {
        return !e.dead && Math.hypot(e.x - cx, e.y - cy) <= info.range;
      }).sort(function (a, b) { return (b.seg+b.t)-(a.seg+a.t); });
      const target = inRange[0];
      if (!target) return;
      u.cd = 1 / info.rate;
      target.hp -= info.dmg * atk;
      drawAttack(cx,cy,target,info.color,Math.round(info.dmg*atk));
      if (info.slow) target.slow = Math.min(target.slow, info.slow);
      flash(target);
      if (target.hp <= 0 && !target.dead) { target.dead = true; S.stats.kills += 1; }
    });
    S.enemies = S.enemies.filter(function (e) { if(e.dead&&e.node)e.node.remove();return !e.dead; });
  }

  function activeBuff(kind) {
    let v = 1;
    S.beastUnits.forEach(function (b) {
      const bonus = 1 + (b.star - 1) * CFG.beastStarBuffStep;
      if (kind === 'attack' && b.name === '青龙') v *= 1 + 0.2 * bonus;
      if (kind === 'rate' && b.name === '白虎') v *= 1 + 0.15 * bonus;
    });
    return v;
  }

  function flash(e) {
    if (!e.node) return;
    e.node.classList.remove('hit');
    void e.node.offsetWidth;
    e.node.classList.add('hit');
  }

  function checkWaveEnd() {
    if (S.phase !== 'battle') return;
    if (S.spawnLeft > 0 || S.enemies.length > 0) return;
    if (S.wave >= CFG.waves) { endGame(true); return; }
    S.phase = 'prep';
    refreshDeck();
    unlockByProgress();
    log('第 ' + S.wave + ' 波结束：棋盘保留，牌堆刷新');
    renderAll();
    toast('本波结束：牌堆刷新，棋盘保留');
  }

  function unlockByProgress() {
    const locked = S.board.filter(function (c) { return c.locked; });
    if (!locked.length) return;
    locked[(Math.random() * locked.length) | 0].locked = false;
  }

  function endGame(win) {
    S.phase = 'over';
    log(win ? '通关！' : '防守失败');
    showOverlay(win);
    renderTop();
  }

  function reportResult(win) {
    if (S.reported) return;
    S.reported = true;
    const payload = { win: win, wave: S.wave, hp: Math.max(0, S.hp),
                      kills: S.stats.kills, leaked: S.stats.leaked, spent: S.stats.spent, merges: S.stats.merges };
    try {
      const b64 = btoa(unescape(encodeURIComponent(JSON.stringify(payload))));
      window.parent.location.href =
        window.parent.location.pathname + '?game_result=' + encodeURIComponent(b64);
    } catch (_) { /* 非嵌入环境忽略 */ }
  }

  function restartGame() {
    // 重开只清空局内状态，不再次发放答题奖励，也不增加动画循环。
    Object.assign(S,{jade:CFG.initialJade,hp:CFG.hp,maxHp:CFG.hp,wave:0,phase:'prep',
      slots:new Array(CFG.slots).fill(null),beastSlots:[null,null],beastUnits:[],beastProgress:{},enemies:[],
      selected:null,shovelSource:null,autoMerge:true,reported:false,spawnLeft:0,spawnTimer:0,log:[],shopUsed:{},speed:1,
      stats:{kills:0,leaked:0,merges:0,spent:0,spawned:0}});
    document.querySelectorAll('.overlay').forEach(n=>n.remove());
    $('#log').innerHTML=''; $('#autoMerge').checked=true; $('#speed').textContent='一倍速';
    buildBoard();refreshDeck();renderAll();window.scrollTo({top:0,behavior:'smooth'});toast('新一局开始，初始灵玉 '+CFG.initialJade);
  }

  function showOverlay(win) {
    const o=el('div','overlay');
    o.innerHTML='<div class="box"><h2>'+(win?'古道守住了':'人皇失守')+'</h2>'
      +'<p>到达第 '+S.wave+' 波 · 击退 '+S.stats.kills+' 只妖怪<br>漏怪 '+S.stats.leaked+' 只 · 合成 '+S.stats.merges+' 次<br>剩余生命 '+Math.max(0,S.hp)+' / '+S.maxHp+'</p>'
      +'<button id="restartGame">再战一局</button><button class="secondary" id="saveResult">结算并返回课程</button>'
      +'<p class="result-note">再战恢复初始 '+CFG.initialJade+' 灵玉并重置布阵，不重复发放答题奖励。</p></div>';
    document.body.appendChild(o);
    $('#restartGame').addEventListener('click',restartGame);
    $('#saveResult').addEventListener('click',()=>reportResult(win));
  }

  function drawAttack(cx,cy,target,color,damage) {
    const svg=$('#fxLayer');const size=S.cellsize;
    if(!svg||!size) return;
    const w=$('#board').getBoundingClientRect().width, offset=w*.2;
    svg.setAttribute('viewBox','0 0 '+(w*1.4)+' '+(w*1.4));
    const line=document.createElementNS('http://www.w3.org/2000/svg','line');
    line.setAttribute('x1',cx*size+offset);line.setAttribute('y1',cy*size+offset);
    line.setAttribute('x2',target.x*size+offset);line.setAttribute('y2',target.y*size+offset);
    line.setAttribute('stroke',color);line.setAttribute('class','shot');svg.appendChild(line);
    const text=document.createElementNS('http://www.w3.org/2000/svg','text');
    text.setAttribute('x',target.x*size+offset);text.setAttribute('y',target.y*size+offset-8);
    text.setAttribute('fill',color);text.setAttribute('class','impact');text.textContent=damage;svg.appendChild(text);
    setTimeout(()=>line.remove(),300);setTimeout(()=>text.remove(),600);
  }


  function bindCellEvents(d,cell) {
    const target={from:'board',r:cell.r,c:cell.c};
    bindDropTarget(d,target);
    const activate=()=>{
      if(!isPlaying())return;
      if(S.shovelSource){useShovel(cell);return;}
      if(cell.locked)return;
      if(S.selected){const source=S.selected;S.selected=null;handleDrop(source,target);renderAll();return;}
      if(cell.unit&&!cell.unit.covered&&!cell.unit.beast){S.selected=target;toast(cell.unit.beastChar?'点目标格移动或交换残字':'空格移动，异字交换，同阶同字合成；三星以上可喂神兽');renderAll();}
    };
    d.addEventListener('click',activate);
    d.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();activate();}});
    if(!cell.locked&&cell.unit&&!cell.unit.covered&&!cell.unit.beast)bindDragSource(d,target);
  }

  // 主循环只有一个，切换工具或拖动不创建额外动画任务。
  let last=0;


  function loop(now) {
    const dt = Math.min(0.05, (now - last) / 1000 || 0)*S.speed;
    last = now;
    if (S.phase === 'battle') {
      S.spawnTimer -= dt;
      if (S.spawnLeft > 0 && S.spawnTimer <= 0) {
        spawnEnemy();
        S.spawnLeft -= 1;
        S.spawnTimer = 1.1;
        renderEnemies();
        renderTop();
      }
      moveEnemies(dt);
      if(S.phase==='battle') towerAttack(dt);
      updateEnemyPositions();
      updateCooldownBars();
      checkWaveEnd();
      renderTop();
    }
    requestAnimationFrame(loop);
  }

  // ---------------------------------------------------------------- 杂项
  function log(msg) {
    S.log.push(msg);
    const box = $('#log');
    if (box) {
      const line = el('div', null, msg);
      line.style.cssText = 'padding:2px 0;border-bottom:1px dashed #243049;color:#644c32';
      box.prepend(line);
      while (box.children.length > 10) box.lastChild.remove();
    }
  }

  let toastTimer = null;
  function toast(msg) {
    const t = $('#toast');
    if (!t) return;
    t.textContent = msg;
    t.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { t.classList.remove('show'); }, 2200);
  }

  function showHelp() {
    const o = el('div', 'overlay');
    o.innerHTML = '<div class="box" style="text-align:left">'
      + '<h2 style="text-align:center">玩法</h2>'
      + '<p style="text-align:left">'
      + '1. 只有<b>未被上层遮挡</b>的字牌能取，取走后露出下一层；<br>'
      + '2. 点普通字进暂存格；三张相同字占三个暂存格，合成<b>这个字本身</b>并上阵；<br>'
      + '3. 棋盘上两个同级同字合并：<b>火+火→炎，炎+炎→焱；日+日→昍；水+水→沝</b>；<br>'
      + '4. 神兽残字每副牌0到2个且不重复；先入神兽槽，拖到棋盘<b>从左到右横排青龙或白虎</b>才激活，反序无效；<br>'
      + '5. 拖铲子到指定封锁格解锁（也可先点铲子再点目标）；打乱重排牌堆、刷新换一批牌、清空把字撤回暂存格；<br>'
      + '6. 闯关时也可拖字移动或交换，同阶同字可升到四星；四星使用燚、㵘等完整叠字字形。<br>'
      + '7. 神兽可拖走单个字拆解；三星及以上字拖给神兽会被吞噬，有'+Math.round(CFG.beastEatChance*100)+'%概率升星，上限'+CFG.beastMaxStars+'星。'
      + '</p><div style="text-align:center">'
      + '<button class="btn primary" id="closeHelp">知道了</button></div></div>';
    document.body.appendChild(o);
    o.querySelector('#closeHelp').addEventListener('click', function () { o.remove(); });
  }

  window.addEventListener('resize',()=>{measureBoard();renderEnemies();});
  document.addEventListener('DOMContentLoaded', function () { init(); });

  window.__CM_DEBUG = {
    S: S, addToSlot: addToSlot, mergeSlot: mergeSlot, onSlotClick: onSlotClick,
    placeUnit: placeUnit, tryMerge: tryMerge, moveUnit: moveUnit,
    clickCard: clickCard, topIndex: topIndex, placeBeastChar: placeBeastChar,
    checkBeast: checkBeast, deployBeast: deployBeast, startWave: startWave,
    refreshDeck: refreshDeck, renderAll: renderAll, checkWaveEnd: checkWaveEnd,
    endGame: endGame, useShovel: useShovel, clearBoard: clearBoard,
    CHAINS: CHAINS, LEVEL_OF: LEVEL_OF, isCardFree:isCardFree, restartGame:restartGame,
    towerAttack:towerAttack, moveEnemies:moveEnemies, activeBuff:activeBuff, pay:pay,
    ownsBeastChar:ownsBeastChar,handleDrop:handleDrop,armShovel:armShovel,
    PATH:PATH,measureBoard:measureBoard,renderEnemies:renderEnemies,spawnEnemy:spawnEnemy,
    splitBeast:splitBeast,feedBeast:feedBeast,unitInfo:unitInfo,beastAnchor:beastAnchor,
  };
})();
