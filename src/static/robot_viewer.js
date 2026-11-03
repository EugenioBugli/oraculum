// Selected robot inspection. One canvas/context is moved into a modal; never sends commands.
import * as THREE from 'three';
import { OrbitControls } from './OrbitControls.js';
import { drawRobot2D, shortName, robotName } from './field_model.js';
const el=(tag,props={},...kids)=>{const e=Object.assign(document.createElement(tag),props);e.append(...kids);return e;};
export function miniature() {
    if (!document.getElementById('robot-viewer-style')) document.head.append(el('style',{id:'robot-viewer-style',textContent:`
      .rp-mini-open { position:relative; padding:0; border:1px solid #515970; border-radius:8px; cursor:zoom-in; background:#171c28; flex-shrink:0; width:98px; height:122px; overflow:hidden; }
      .rp-mini-open:after { content:'⛶'; position:absolute; bottom:3px; right:5px; color:#fff; font-size:18px; text-shadow:0 1px 3px #000; }
      .rp-mini-open:focus-visible { outline:2px solid #a5b4fc; }
      .rp-viewer { margin:auto; color:#e5e7eb; background:#161b28; border:1px solid #667085; border-radius:12px; padding:0; width:min(900px,94vw); max-width:94vw; height:min(760px,90dvh); max-height:90dvh; }
      .rp-viewer[open] { display:flex; flex-direction:column; }
      .rp-viewer::backdrop { background:#050813c9; }
      .rp-viewer header { display:flex; align-items:center; flex-wrap:wrap; gap:10px; padding:12px 16px; border-bottom:1px solid #343d52; }
      .rp-viewer h2 { margin:0 auto 0 0; font:700 16px system-ui; }
      .rp-viewer button { background:#293247; border:1px solid #667085; border-radius:6px; padding:7px 10px; color:#fff; cursor:pointer; }
      .rp-viewer button:focus-visible { outline:2px solid #a5b4fc; }
      .rp-viewer button[aria-pressed=true] { background:#4f46e5; }
      .rp-viewer-stage { flex:1; min-height:100px; overflow:hidden; background:radial-gradient(ellipse at 50% 30%,#30394d,#111520); }
      .rp-viewer-stage canvas { display:block; width:100%; height:100%; touch-action:none; }
      .rp-viewer footer { padding:10px 16px; font:12px/1.5 system-ui; color:#bec8db; }
      .rp-viewer-status { display:block; color:#9cdbed; }
    `}));
    const host=el('button',{type:'button',className:'rp-mini-open',title:'Enlarge robot inspection',ariaLabel:'Enlarge robot inspection'});
    const stage=el('div',{className:'rp-viewer-stage'}), title=el('h2',{textContent:'Robot inspection'});
    const pick=el('button',{type:'button',textContent:'Pick pivot'}), reset=el('button',{type:'button',textContent:'Reset view'});
    const close=el('button',{type:'button',textContent:'Close',ariaLabel:'Close robot inspection'});
    const status=el('span',{className:'rp-viewer-status',role:'status',textContent:'Loading robot model…'});
    const help=el('span',{textContent:'Drag to orbit · wheel/pinch to zoom · right-drag/two fingers to pan. Double-click a part or choose Pick pivot, then tap a point.'});
    const dialog=el('dialog',{className:'rp-viewer'},el('header',{},title,pick,reset,close),stage,el('footer',{},help,status));
    dialog.setAttribute('aria-label','Robot inspection');document.body.append(dialog);
    let canvas, r3, scene, camera, controls, marker, robot, pose, latest, robotId='', flat=false, mod, picking=false;
    const ray=new THREE.Raycaster(), pointer=new THREE.Vector2();
    let lastWidth=0,lastHeight=0;
    const fresh=()=>{canvas=el('canvas',{className:'rp-mini'});host.replaceChildren(canvas); if(dialog.open)stage.append(canvas); observer.observe(canvas); wirePicking();};
    const size=()=>{const box=(dialog.open?stage:host).getBoundingClientRect();return [Math.max(1,box.width),Math.max(1,box.height)];};
    function draw() {
        if(!latest || !canvas.isConnected || !canvas.getClientRects().length || document.hidden)return;
        const [w,h]=size();
        if(flat) {
            const px=Math.min(devicePixelRatio||1,2);canvas.width=w*px;canvas.height=h*px;
            const ctx=canvas.getContext('2d');ctx.clearRect(0,0,canvas.width,canvas.height);
            drawRobot2D(ctx,{...latest,angle:Math.PI/2},canvas.width/2,canvas.height/2,Math.min(w,h)/38*px,null,latest.color);
            return;
        }
        if(!r3 || !robot)return;
        if(w!==lastWidth || h!==lastHeight) {
            r3.setSize(w,h,false);camera.aspect=w/h;camera.updateProjectionMatrix();lastWidth=w;lastHeight=h;
        }
        marker.visible=dialog.open; marker.position.copy(controls.target);
        marker.scale.setScalar(camera.position.distanceTo(controls.target)*.008);
        r3.render(scene,camera);
    }
    const observer=new ResizeObserver(draw);
    function pickingMode(on) {
        picking=on;pick.setAttribute('aria-pressed',String(on));
        if(controls)controls.enabled=dialog.open&&!on;
        canvas.style.cursor=on?'crosshair':'';
        if(on)status.textContent='Tap a robot part or any point in the view to set the pivot.';
    }
    function choosePivot(event) {
        if(!dialog.open || flat || !robot)return;
        const b=canvas.getBoundingClientRect();pointer.set(2*(event.clientX-b.left)/b.width-1,1-2*(event.clientY-b.top)/b.height);
        camera.updateMatrixWorld();robot.updateMatrixWorld(true);ray.setFromCamera(pointer,camera);
        const hit=ray.intersectObject(robot,true)[0];
        const target=new THREE.Vector3();
        if(hit)target.copy(hit.point);
        else {
            const normal=camera.getWorldDirection(new THREE.Vector3());
            if(!ray.ray.intersectPlane(new THREE.Plane().setFromNormalAndCoplanarPoint(normal,controls.target),target))return;
        }
        controls.target.copy(target);controls.update();pickingMode(false);
        status.textContent=`Pivot selected${hit?' on robot':''}. Zoom and orbit use this point.`;
        canvas.dataset.pivot=target.toArray().join(','); draw();
    }
    function wirePicking() {
        canvas.addEventListener('dblclick',choosePivot);
        canvas.addEventListener('pointerup',e=>{if(picking)choosePivot(e);});
        canvas.addEventListener('webglcontextlost',e=>{e.preventDefault();to2D('3D context lost');});
    }
    function to2D(why) {
        controls?.dispose();controls=null;r3?.dispose();r3=null;flat=true;robot=null;
        observer.unobserve(canvas);fresh();
        pick.disabled=reset.disabled=true;help.textContent='2D preview: 3D inspection is unavailable.';
        status.textContent=why;draw();
    }
    function resetView() {
        if(!robot || !camera)return;
        const h=robot.userData.height||1.2;
        controls.target.set(0,.48*h,0);camera.position.set(.8*h,.8*h,-2.2*h);
        controls.minDistance=.08*h;controls.maxDistance=12*h;controls.update();
        delete canvas.dataset.pivot;pickingMode(false);status.textContent='Whole robot · choose a pivot to inspect a part.';draw();
    }
    function init() {
        const context=canvas.getContext('webgl2',{antialias:true,alpha:true,powerPreference:'low-power'});
        if(!context)return to2D('WebGL2 is unavailable');
        try {r3=new THREE.WebGLRenderer({canvas,context,antialias:true,alpha:true});}
        catch(e){return to2D(e.message);}
        r3.setPixelRatio(Math.min(devicePixelRatio||1,2));scene=new THREE.Scene();
        scene.add(new THREE.HemisphereLight(0xffffff,0x445066,1.1));
        const sun=new THREE.DirectionalLight(0xffffff,1.2);sun.position.set(-1.5,3,-2.5);scene.add(sun);
        camera=new THREE.PerspectiveCamera(28,96/120,.005,100);
        controls=new OrbitControls(camera,canvas);controls.enabled=dialog.open;
        controls.addEventListener('change',draw);
        marker=new THREE.Mesh(new THREE.SphereGeometry(1,12,8),new THREE.MeshBasicMaterial({color:0x6ee7ff,depthTest:false}));
        marker.renderOrder=10;scene.add(marker);
    }
    fresh();
    host.onclick=()=>{if(!latest)return;dialog.showModal();stage.append(canvas);if(controls)controls.enabled=true;draw();close.focus();};
    close.onclick=()=>dialog.close();
    dialog.addEventListener('close',()=>{pickingMode(false);if(controls)controls.enabled=false;host.append(canvas);if(!flat)resetView();draw();host.focus();});
    pick.onclick=()=>pickingMode(!picking);reset.onclick=resetView;
    function show(agent) {
        latest=agent;
        title.textContent=`${shortName(robotName(agent,[agent]),agent.ip)} · ${String(agent.robot||'robot').toUpperCase()}`;
        if(!flat&&!r3)init();
        if(flat){draw();return;}
        const id=`${agent.ip}|${agent.id}|${agent.robot}|${agent.color}`;
        if(id!==robotId){
            robotId=id;if(robot)scene.remove(robot);robot=null;pick.disabled=reset.disabled=true;status.textContent='Loading robot model…';
            mod ||= import('./mujoco_robots.js');
            mod.then(m=>m.loadRobots([m.modelKey(agent)])).then(R=>{
                if(robotId!==id||flat)return;
                robot=R.makeRobot(agent);pose=R.pose;scene.add(robot);pick.disabled=reset.disabled=false;resetView();show(latest);
            }).catch(e=>{if(robotId===id)to2D(e.message);});
        }
        if(robot){pose(robot,agent.joints);draw();}
    }
    return {host,show,clear:()=>{if(dialog.open)dialog.close();latest=null;robotId='';if(robot)scene.remove(robot);robot=null;}};
}
