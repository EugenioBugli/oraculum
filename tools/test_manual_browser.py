"""Offline manual-entry, stale-link, wizard and 2D-fallback browser checks.
Uses the isolated static server and intercepted APIs from test_workspace_browser.
All commands below go to the fixture, never a gateway or robot.
"""
import json
from playwright.sync_api import sync_playwright
from test_workspace_browser import OUT, base, check, errors, posts, results, route, server, state


def commands():
    return [json.loads(p['body']) for p in posts if p['path'] == '/control']


completed = False
try:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path='/usr/bin/google-chrome', headless=True,
                                     args=['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'])
        for name in ('index', 'dashboard'):
            state['agents'][0]['latch'] = 'stop'
            state['fleet']['link']['192.0.2.6']['age'] = 0
            posts.clear()
            context = browser.new_context(viewport={'width':1440,'height':1000})
            context.route('**/*', route)
            context.add_init_script("""
                localStorage.setItem('oraculum_renderer_engine_v2','threejs');
                const get = HTMLCanvasElement.prototype.getContext;
                HTMLCanvasElement.prototype.getContext = function(kind, ...args) {
                    if(this.classList.contains('rp-mini') && kind.startsWith('webgl')) return null;
                    return get.call(this,kind,...args);
                };
            """)
            page = context.new_page()
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(f'{base}/{name}.html', wait_until='domcontentloaded')
            page.wait_for_function("typeof selectRobot==='function' && document.querySelector('[data-act]')")
            page.evaluate("switchView('2d');selectRobot(6,'192.0.2.6')")
            page.locator('.rp-mini-open').click()
            check(page.get_by_role('button',name='Pick pivot',exact=True).is_disabled(),f'{name}: no-WebGL disables 3D pivot')
            check('WebGL2 is unavailable' in page.locator('.rp-viewer-status').inner_text(),f'{name}: 2D fallback explains limitation')
            page.screenshot(path=str(OUT/f'{name}-fallback.png'))
            page.keyboard.press('Escape')
            page.locator('#checkManualMode').check()
            page.wait_for_timeout(350)
            check(commands() and all(c.get('rb') and c.get('rt') and c.get('b') and c['vx']==0 and c['vy']==0 and c['vtheta']==0 for c in commands()),f'{name}: STOP entry sends only zero-speed combo')
            joy = page.locator('#joyBoundary').bounding_box()
            page.mouse.move(joy['x']+joy['width']/2,joy['y']+joy['height']/2)
            page.mouse.down();page.mouse.move(joy['x']+joy['width']/2,joy['y']+5,steps=4)
            state['agents'][0]['latch']=''
            page.wait_for_function("document.getElementById('manualTarget').textContent.includes('Release the joystick')")
            check(all(c['vx']==0 and c['vy']==0 and c['vtheta']==0 for c in commands()),f'{name}: held stick cannot bypass entry gate')
            page.mouse.up()
            page.wait_for_function("document.getElementById('manualTarget').textContent.startsWith('MANUAL ON')")
            page.mouse.move(joy['x']+joy['width']/2,joy['y']+joy['height']/2)
            page.mouse.down();page.mouse.move(joy['x']+joy['width']/2,joy['y']+5,steps=4)
            page.wait_for_timeout(350)
            check(any(c['vx']>0 for c in commands()),f'{name}: released gate permits forward command')
            page.mouse.up();page.wait_for_timeout(250)
            check(commands()[-1]['vx']==0 and commands()[-1]['vy']==0,f'{name}: releasing stick sends zero')
            page.locator('#robotPanel .ctl-stop').click()
            check(not page.locator('#checkManualMode').is_checked(),f'{name}: STOP cancels Manual locally')
            count=len(commands());page.wait_for_timeout(250)
            check(len(commands())==count,f'{name}: no Manual requests after STOP')
            page.locator('#checkManualMode').check();page.wait_for_timeout(250)
            state['fleet']['link']['192.0.2.6']['age']=3
            page.wait_for_function("!document.getElementById('checkManualMode').checked")
            count=len(commands());page.wait_for_timeout(250)
            check(len(commands())==count,f'{name}: stale telemetry cancels ongoing Manual')
            check(all(c['ip']=='192.0.2.6' for c in commands()),f'{name}: every mocked command targets selected robot')
            (OUT/f'{name}-mocked-commands.json').write_text(json.dumps(posts,indent=2))
            context.close()

        # The session menu opens the wizard; saving remains browser-local.
        state['fleet']['link']['192.0.2.6']['age']=0
        posts.clear()
        context=browser.new_context(viewport={'width':1024,'height':768})
        context.route('**/*',route)
        page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(f'{base}/index.html',wait_until='domcontentloaded')
        page.get_by_role('combobox',name='Session menu').select_option('simulated')
        page.wait_for_url('**/simulation.html?mode=simulated')
        page.locator('#scenarioName').fill('Offline acceptance')
        page.locator('#fieldPreset').select_option('spl')
        page.locator('#next').click()
        page.locator('#team1Name').fill('Visitors')
        page.locator('#next').click()
        page.locator('#roster1 [data-field=model]').select_option('k1')
        page.locator('#next').click()
        page.locator('#saveScenario').click()
        saved=page.evaluate("JSON.parse(localStorage.getItem('oraculum_scenario_v1'))")
        check(saved['name']=='Offline acceptance' and saved['field']=={'width':9,'height':6},'wizard saves custom name and field')
        check(saved['teams'][1]['name']=='Visitors' and saved['teams'][1]['players'][0]['model']=='k1','wizard saves teams and model')
        page.reload(wait_until='domcontentloaded')
        check(page.locator('#scenarioName').input_value()=='Offline acceptance','wizard scenario survives reload')
        check(not posts,'wizard makes no command or deployment POST')
        check(not errors,f'no page errors: {errors}')
        context.close();browser.close()
        completed = True
finally:
    server.shutdown()
    (OUT/'manual-results.json').write_text(json.dumps({'completed':completed,'passed':results,'errors':errors},indent=2))
