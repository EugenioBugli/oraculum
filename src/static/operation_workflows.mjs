// Explicit previews and authenticated jobs. Operator credentials remain only in this module's memory.
export function mountOperationWorkflows(host, { scenario = null } = {}) {
    host.innerHTML = `<h2>${scenario ? 'Run an isolated simulation' : 'Run a workflow'}</h2>
      <p>Review one operation at a time. Progress and results below come from the gateway job.</p>
      <form class="row" data-login><label>Operator token<input type="password" autocomplete="off" data-token></label><button>Unlock workflows</button></form>
      <p role="status" data-message>Use an operator token with the required permissions.</p>
      <div data-controls hidden>
        <div class="row"><label data-target-label>Target<select data-target></select></label><label>Operation<select data-action></select></label></div>
        <div class="row" data-options>
          <label data-profile-label>Configuration<select data-profile><option value="practice">Practice</option><option value="match">Match</option></select></label>
          <label data-artifact-label>Artifact<select data-artifact></select></label>
          <label data-previous-label>Successful operation<select data-previous></select></label>
          <label data-network-label>Network profile<select data-network></select></label>
        </div>
        <button type="button" data-preview>Preview operation</button>
        <div data-review hidden><ol data-steps></ol>
          <label data-support-label><input type="checkbox" data-support> The robot is securely supported now.</label>
          <label>Type the target shown in the preview<input data-confirm autocomplete="off"></label>
          <button type="button" data-execute>Execute reviewed operation</button>
        </div>
        <button type="button" data-lock>Lock workflows</button>
        <h3>Operation history</h3><select aria-label="Operation history" data-history></select>
        <p role="status" data-job-status>No operation started.</p><button type="button" data-keep-network hidden>Keep this network connection</button><button type="button" data-cancel hidden>Cancel / stop session</button>
        <details><summary>Progress and observed result</summary><pre data-output>No output.</pre></details>
      </div>`;
    const $ = key => host.querySelector(`[data-${key}]`);
    const message = text => $('message').textContent = text;
    let token = '', capabilities, preview, generation = 0, requestKey, history = [], selected = '', artifactRevision = '';
    const actions = [
        ['build','Build software','software'],['stage','Stage artifact','software'],['deploy','Deploy over Ethernet','deploy'],
        ['rollback','Roll back deployment','deploy'],['service-start','Start service','service'],['service-stop','Stop service','service'],
        ['service-restart','Restart service','service'],['network-apply','Activate network profile','network'],
        ['network-rollback','Restore network profile','network'],['simulate','Run simulation','simulation'],
    ];
    async function api(path, body) {
        const response = await fetch(path, { method:body ? 'POST':'GET', headers:{'X-Oraculum-Operator':token,
            ...(body ? {'Content-Type':'application/json'} : {})}, ...(body ? {body:JSON.stringify(body)} : {}) });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
        return data;
    }
    function invalidate() {
        generation++; preview=null; $('review').hidden=true; $('support').checked=false; $('confirm').value='';
    }
    function options() {
        invalidate();
        const action=$('action').value;
        $('target-label').hidden=action==='simulate';
        $('profile-label').hidden=!['build','stage'].includes(action);
        $('artifact-label').hidden=action!=='deploy';
        $('previous-label').hidden=!['rollback','network-rollback'].includes(action);
        $('network-label').hidden=action!=='network-apply';
        $('network').replaceChildren(...(capabilities?.network_profiles || []).filter(p=>p.target===$('target').value).map(p=>new Option(p.label,p.id)));
        previousOptions();
    }
    function previousOptions() {
        const value=$('previous').value;
        const previous=history.filter(j=>j.status==='succeeded' && j.spec.target===$('target').value && j.spec.action===($('action').value==='rollback'?'deploy':'network-apply'));
        $('previous').replaceChildren(...previous.map(j=>new Option(`${j.spec.action} · ${j.id.slice(0,8)}`,j.id)));
        if(previous.some(j=>j.id===value))$('previous').value=value;
    }
    $('login').onsubmit=async event=>{
        event.preventDefault(); token=$('token').value; $('token').value='';
        try {
            capabilities=await api('/ops/capabilities');
            $('target').replaceChildren(...capabilities.targets.map(t=>new Option(t==='gateway'?'This gateway host':t,t)));
            $('action').replaceChildren(...actions.filter(([id,,role])=>capabilities.roles.includes(role) && (scenario ? id==='simulate' : id!=='simulate')).map(([id,label])=>new Option(label,id)));
            const artifacts=capabilities.roles.some(r=>['software','deploy'].includes(r)) ? await api('/ops/artifacts') : {artifacts:[]};
            $('artifact').replaceChildren(...artifacts.artifacts.map(id=>new Option(id,id)));
            $('controls').hidden=false; $('login').hidden=true;
            message(`Signed in as ${capabilities.operator}. ${scenario && !capabilities.simulator ? 'The gateway has no simulator image configured.' : 'Choose an operation to preview.'}`);
            await refresh(); options();
        } catch(error) {token='';message(error.message);}
    };
    $('lock').onclick=()=>{token='';history=[];selected='';artifactRevision='';invalidate();$('controls').hidden=true;$('login').hidden=false;message('Workflows locked. Running jobs continue on the gateway.');};
    $('action').onchange=options; $('target').onchange=options;
    $('options').onchange=invalidate;
    $('preview').onclick=async()=>{
        invalidate();const current=generation;
        $('preview').disabled=true;
        try {
            const action=$('action').value;
            const spec={action,target:action==='simulate'?null:$('target').value,profile:action==='network-apply'?$('network').value:$('profile').value,
                artifact:$('artifact').value,job:$('previous').value};
            if(action==='simulate') {spec.scenario=scenario();if(!spec.scenario)throw new Error('Correct the scenario before previewing.');}
            const result=await api('/ops/preview',spec);
            if(current!==generation)return;
            preview=result;requestKey=crypto.randomUUID();
            $('steps').replaceChildren(...result.steps.map(text=>{const li=document.createElement('li');li.textContent=text;return li;}));
            $('support-label').hidden=!result.support_required;$('review').hidden=false;
            message(`Preview: ${result.spec.action} → ${result.confirmation}. Type “${result.confirmation}” to execute. Expires in ${result.expires_in} seconds.`);
        }catch(error){if(current===generation)message(error.message);}
        finally{$('preview').disabled=false;}
    };
    $('execute').onclick=async()=>{
        if(!preview)return;
        $('execute').disabled=true;
        try {
            const job=await api('/ops/jobs',{preview:preview.preview,key:requestKey,confirm:$('confirm').value,supported:$('support').checked});
            selected=job.id;invalidate();message(`Started ${job.spec.action} → ${job.spec.target || "isolated simulation"}. Follow the observed result below.`);show(job);await refresh();
        }catch(error){message(error.message);}
        finally{$('execute').disabled=false;}
    };
    function show(job) {
        $('job-status').textContent=`${job.spec.action} → ${job.spec.target || 'isolated simulation'} · ${job.status} · ${job.phase}${job.error?' · '+job.error:''}`;
        $('output').textContent=(job.logs || []).join('\n')+(job.result?'\n\n'+JSON.stringify(job.result,null,2):'');
        $('cancel').hidden=!['queued','running'].includes(job.status);$('cancel').disabled=job.phase==='activating';
        $('keep-network').hidden=job.status!=='running' || job.phase!=='awaiting network confirmation';
    }
    async function refresh() {
        if(!token)return;
        const credential=token;
        try {
            const result=await api('/ops/jobs');
            if(token!==credential)return;
            history=result.jobs;previousOptions();
            $('history').replaceChildren(...history.map(j=>new Option(`${j.spec.action} · ${j.spec.target || 'simulation'} · ${j.status} · ${j.id.slice(0,8)}`,j.id)));
            if(!selected && history.length)selected=history[0].id;
            $('history').value=selected;const job=history.find(j=>j.id===selected);if(job)show(job);
            const revision=history.filter(j=>j.spec.action==='stage' && j.status==='succeeded').map(j=>j.id).join(',');
            if(revision!==artifactRevision && capabilities.roles.some(r=>['software','deploy'].includes(r))) {
                const artifacts=await api('/ops/artifacts');if(token!==credential)return;
                const value=$('artifact').value;
                $('artifact').replaceChildren(...artifacts.artifacts.map(id=>new Option(id,id)));
                if(artifacts.artifacts.includes(value))$('artifact').value=value;
                artifactRevision=revision;
            }
        }catch(error){if(token===credential)message('Job status unavailable: '+error.message);}
    }
    $('history').onchange=()=>{selected=$('history').value;const job=history.find(j=>j.id===selected);if(job)show(job);};
    $('cancel').onclick=async()=>{try{await api(`/ops/jobs/${selected}/cancel`,{});await refresh();}catch(error){message(error.message);}};
    $('keep-network').onclick=async()=>{try{await api(`/ops/jobs/${selected}/confirm`,{});await refresh();}catch(error){message(error.message);}};
    setInterval(refresh,1000);
}
