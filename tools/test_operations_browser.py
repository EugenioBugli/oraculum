"""Browser acceptance against real Operations API + fake subprocess/SSH transport."""
import json
from pathlib import Path
import sys
from playwright.sync_api import sync_playwright
from operations_fixture import Fixture, TOKEN

out=Path(sys.argv[1] if len(sys.argv)>1 else '/tmp/oraculum-operations-browser')
out.mkdir(parents=True,exist_ok=True)
f=Fixture();base=f.start_server();errors=[];passed=[];completed=False
def check(condition, message):
    assert condition,message
    passed.append(message);print('PASS',message,flush=True)

try:
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path='/usr/bin/google-chrome',headless=True,args=['--no-sandbox'])
        context=browser.new_context(viewport={'width':1280,'height':1000})
        page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(base+'/operations.html?token=offline-gateway-token',wait_until='domcontentloaded')
        host=page.locator('#operationWorkflows')
        check(not host.locator('[data-controls]').is_visible(),'operations locked on load')
        check(not f.calls,'page load sends no robot command')
        host.locator('[data-token]').fill('incorrect');host.get_by_role('button',name='Unlock workflows').click()
        page.wait_for_function("document.querySelector('[data-message]').textContent.includes('operator token')")
        check(not host.locator('[data-controls]').is_visible(),'bad token cannot unlock workflows')
        host.locator('[data-token]').fill(TOKEN);host.get_by_role('button',name='Unlock workflows').click()
        host.locator('[data-controls]').wait_for(state='visible')
        check(host.locator('[data-token]').input_value()=='','operator token cleared from input')
        check(not page.evaluate('Object.values({...localStorage,...sessionStorage}).some(v=>v.includes("offline-operator"))'),'operator token not persisted in browser storage')

        def preview(action):
            host.locator('[data-action]').select_option(action)
            host.locator('[data-preview]').click()
            host.locator('[data-review]').wait_for(state='visible')
        def execute(target='robot6',supported=False,wait=True):
            host.locator('[data-confirm]').fill(target)
            if supported:host.locator('[data-support]').check()
            host.locator('[data-execute]').click()
            if wait:host.locator('[data-review]').wait_for(state='hidden')
        def finished(status='succeeded'):
            page.wait_for_function('(status)=>document.querySelector("[data-job-status]").textContent.includes(status)',arg=status)

        preview('service-restart')
        check(not f.calls,'preview remains side-effect free')
        execute(wait=False)
        page.wait_for_function("document.querySelector('[data-message]').textContent.includes('physically supported')")
        check(not f.calls,'missing support confirmation sends no SSH')
        execute(supported=True);finished()
        check('ActiveState=active' in host.locator('[data-output]').text_content(),'observed service state shown')
        service_job=f.jobs.list('tester')[0]['id']
        host.locator('[data-action]').select_option('service-stop');host.locator('[data-preview]').click()
        host.locator('[data-review]').wait_for(state='visible')
        host.locator('[data-target]').select_option('gateway')
        check(not host.locator('[data-review]').is_visible(),'changing target invalidates preview')
        host.locator('[data-target]').select_option('robot6')
        preview('stage');execute();finished()
        check(any(j['spec']['action']=='stage' for j in f.jobs.list('tester')),'stage job reaches backend')
        preview('deploy');execute(supported=True);finished()
        check(any('ACTIVATION_VERIFIED' in k.get('input','') for _,k in f.calls),'deploy reaches checksum and rollback adapter')
        preview('rollback');execute(supported=True);finished()
        check('ROLLBACK_VERIFIED' in f.calls[-1][1]['input'],'rollback reaches selected deployment backup')
        f.fail=True;preview('service-start');execute(supported=True);finished('failed')
        check('fixture transport failure' in host.locator('[data-job-status]').inner_text(),'transport failure visible as failure')
        f.fail=False;preview('network-apply');execute();finished()
        check(any('--on-active=90s' in k.get('input','') for _,k in f.calls),'network workflow arms recovery timer')
        host.locator('[data-target]').select_option('gateway');preview('network-apply');execute('gateway');finished('awaiting network confirmation')
        host.locator('[data-keep-network]').click();finished()
        check(any(a==['bash','-se'] for a,_ in f.calls),'gateway profile uses local configured adapter')
        page.screenshot(path=str(out/'operations-desktop.png'),full_page=True)
        page.set_viewport_size({'width':390,'height':844});page.screenshot(path=str(out/'operations-phone.png'),full_page=True)
        check(page.evaluate('document.documentElement.scrollWidth<=innerWidth+2'),'Operations phone has no horizontal overflow')

        # Server authorization and request shape are exercised independently of hidden buttons.
        response=context.request.post(base+'/ops/preview',headers={'X-Oraculum-Operator':'offline-reader-token-123456789'},data={'action':'service-stop','target':'robot6'})
        check(response.status==403,'read-only operator denied by API')
        response=context.request.post(base+'/ops/preview',headers={'X-Oraculum-Operator':TOKEN,'Origin':'https://unrelated.invalid'},data={'action':'service-stop','target':'robot6'})
        check(response.status==403,'foreign origin denied by API')
        response=context.request.get(base+'/ops/jobs/'+service_job,headers={'X-Oraculum-Operator':'offline-reader-token-123456789'})
        check(response.status==400,'another operator cannot read private job')
        f.server.match=True
        response=context.request.post(base+'/ops/preview',headers={'X-Oraculum-Operator':TOKEN},data={'action':'service-stop','target':'robot6'})
        check(response.status==403,'match mode blocks maintenance API');f.server.match=False

        page.goto(base+'/simulation.html',wait_until='domcontentloaded')
        host=page.locator('#simulationWorkflow')
        host.locator('[data-token]').fill(TOKEN);host.get_by_role('button',name='Unlock workflows').click()
        host.locator('[data-controls]').wait_for(state='visible');preview('simulate');execute('simulation')
        finished('simulator running')
        check(any(a[:3]==['docker','run','-d'] and 'none' in a for a,_ in f.calls),'wizard starts isolated simulator adapter')
        host.locator('[data-cancel]').click();finished('cancelled')
        check(f.calls[-1][0][:3]==['docker','rm','-f'],'stopping session cleans up container')
        page.screenshot(path=str(out/'simulation-session.png'),full_page=True)
        check(not errors,'no browser page errors')
        browser.close();completed=True
finally:
    f.server.http_server.shutdown();f.close()
    (out/'operations-results.json').write_text(json.dumps({'completed':completed,'passed':passed,'errors':errors,'transport_calls':len(f.calls)},indent=2))
