"""Offline workspace acceptance: serves static assets, intercepts all API traffic.
No robot gateway, UDP sender or SSH process is started.
Usage: python3 tools/test_workspace_browser.py [evidence_directory]
"""
import functools
import http.server
import json
import pathlib
import sys
import threading
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else '/tmp/oraculum-workspace-check')
OUT.mkdir(parents=True, exist_ok=True)


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Quiet, directory=str(ROOT / 'src')))
threading.Thread(target=server.serve_forever, daemon=True).start()
base = f'http://127.0.0.1:{server.server_port}'
state = {
    'agents': [{'id': 6, 'ip': '192.0.2.6', 'team': 19, 'robot': 't1', 'color': '#d63344',
                'x': 0, 'y': 0, 'angle': 0, 'role': 'striker', 'state': 'R', 'battery': 82,
                'fallen': False, 'latch': 'stop', 'joints': {}, 'sys': {'link': 'control', 'version': 'fixture'}}],
    'ball': None, 'drawings': [], 'texts': [], 'gamecontroller': None,
    'fleet': {'head': 'fixture', 'link': {'192.0.2.6': {'age': 0, 'hz': 10, 'kbps': 2}}},
    'lock': {'holder': 'tester', 'you': True}, 'rec': {}, 'last_event': 0, 'match': False,
}
posts, errors, results = [], [], []


def route(req):
    request = req.request
    path = urlparse(request.url).path
    if request.method != 'GET':
        posts.append({'path': path, 'body': request.post_data})
        return req.fulfill(json={'status': 'sent', 'targets': ['192.0.2.6']})
    if path == '/state':
        return req.fulfill(json=state)
    if path == '/field':
        return req.fulfill(json={'width': 14, 'height': 9})
    if path == '/positions':
        return req.fulfill(json={'positions': [{'id': 'ready_6', 'label': 'Ready R6', 'player': 6, 'x': 0, 'y': 0, 'theta': 0}]})
    if path == '/events':
        return req.fulfill(json={'events': []})
    if path == '/recordings':
        return req.fulfill(json={'recordings': []})
    if path.startswith('/static/') or path.endswith('.html'):
        return req.continue_()
    return req.fulfill(json={})


def check(value, message):
    assert value, message
    results.append(message)
    print('PASS', message, flush=True)


def main():
    completed = False
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path='/usr/bin/google-chrome', headless=True,
                                         args=['--no-sandbox', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'])
            for name in ('index', 'dashboard'):
                context = browser.new_context(viewport={'width': 1440, 'height': 1000})
                context.add_init_script("localStorage.setItem('oraculum_renderer_engine_v2','threejs')")
                context.route('**/*', route)
                page = context.new_page()
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(f'{base}/{name}.html', wait_until='domcontentloaded')
                page.wait_for_function('typeof selectRobot === "function"')
                page.evaluate("switchView('2d');selectRobot(6,'192.0.2.6')")
                page.wait_for_selector('.rp-mini-open')
                page.wait_for_function("document.querySelector('.rp-viewer-status').textContent.startsWith('Whole robot')", timeout=60000)
                check(not page.locator('.joystick-panel-grid').is_visible(), f'{name}: joystick hidden until Manual')
                check(page.locator('#sliderVx').get_attribute('max') == '1.0', f'{name}: speed range respects stick limit')
                check(not page.locator('#robotPanel button.ctl-more').is_visible(), f'{name}: secondary posture actions folded')
                check(page.locator('#robotPanel .ctl-stop').is_visible(), f'{name}: STOP stays visible')
                left = page.get_by_role('separator', name='Resize left pane', exact=True)
                old = float(left.get_attribute('aria-valuenow'))
                b = left.bounding_box()
                page.mouse.move(b['x']+3, b['y']+40)
                page.mouse.down(); page.mouse.move(b['x']+83, b['y']+40, steps=5); page.mouse.up()
                check(float(left.get_attribute('aria-valuenow')) > old+50, f'{name}: pane drag resizes')
                left.focus(); page.keyboard.press('ArrowRight')
                width = left.get_attribute('aria-valuenow')
                page.reload(wait_until='domcontentloaded')
                page.wait_for_selector('.ws-grip[data-axis=x]')
                check(left.get_attribute('aria-valuenow') == width, f'{name}: pane width persists after reload')
                left.focus(); page.keyboard.press('Home')
                check(float(left.get_attribute('aria-valuenow')) == 280, f'{name}: keyboard reset')
                page.evaluate("switchView('2d');selectRobot(6,'192.0.2.6')")
                vertical = page.locator('#robotPanel .ws-grip[data-axis=y]')
                b = vertical.bounding_box(); old = page.locator('#robotPanel').bounding_box()['height']
                page.mouse.move(b['x']+50,b['y']+3);page.mouse.down();page.mouse.move(b['x']+50,b['y']+83,steps=5);page.mouse.up()
                check(page.locator('#robotPanel').bounding_box()['height'] > old+50, f'{name}: panel height resizes')
                vertical.focus();page.keyboard.press('Home')
                page.locator('.rp-mini-open').click()
                page.wait_for_function("document.querySelector('.rp-viewer-status').textContent.startsWith('Whole robot')", timeout=60000)
                check(abs(page.locator('.rp-viewer').bounding_box()['x']-270)<5, f'{name}: viewer centered')
                check(page.locator('.rp-viewer').is_visible(), f'{name}: enlarged 3D viewer opens')
                canvas=page.locator('.rp-viewer-stage canvas')
                b=canvas.bounding_box();check(b['width']>500 and b['height']>300,f'{name}: enlarged canvas fills pane')
                page.get_by_role('button',name='Pick pivot',exact=True).click()
                page.mouse.click(b['x']+b['width']*.53,b['y']+b['height']*.32)
                check(canvas.get_attribute('data-pivot') is not None,f'{name}: custom pivot selected')
                check('on robot' in page.locator('.rp-viewer-status').inner_text(),f'{name}: pivot raycast hits robot surface')
                before=page.screenshot(clip=canvas.bounding_box())
                page.mouse.wheel(0,-350);page.wait_for_timeout(150)
                check(page.screenshot(clip=canvas.bounding_box())!=before,f'{name}: zoom changes view around pivot')
                before=page.screenshot(clip=canvas.bounding_box())
                page.mouse.move(b['x']+200,b['y']+200);page.mouse.down(button='right');page.mouse.move(b['x']+250,b['y']+230,steps=6);page.mouse.up(button='right')
                check(page.screenshot(clip=canvas.bounding_box())!=before,f'{name}: enlarged pan changes view')
                before=page.screenshot(clip=canvas.bounding_box())
                page.mouse.move(b['x']+300,b['y']+200);page.mouse.down();page.mouse.move(b['x']+350,b['y']+230,steps=6);page.mouse.up()
                check(page.screenshot(clip=canvas.bounding_box())!=before,f'{name}: enlarged orbit changes view')
                page.get_by_role('button',name='Reset view',exact=True).click()
                page.get_by_role('button',name='Pick pivot',exact=True).click()
                touch=context.new_cdp_session(page)
                touch.send('Emulation.setTouchEmulationEnabled',{'enabled':True,'maxTouchPoints':2})
                touch.send('Input.dispatchTouchEvent',{'type':'touchStart','touchPoints':[{'x':b['x']+b['width']*.53,'y':b['y']+b['height']*.32,'id':0}]})
                touch.send('Input.dispatchTouchEvent',{'type':'touchEnd','touchPoints':[]})
                check(canvas.get_attribute('data-pivot') is not None,f'{name}: touch tap chooses custom pivot')
                touch.send('Emulation.setTouchEmulationEnabled',{'enabled':False});touch.detach()
                page.screenshot(path=str(OUT/f'{name}-viewer.png'))
                page.keyboard.press('Escape')
                check(not page.locator('.rp-viewer').is_visible(),f'{name}: Escape closes viewer')
                check(page.locator('.rp-mini-open').evaluate('(e)=>document.activeElement===e'),f'{name}: focus restored')
                page.locator('.rp-mini-open canvas').wait_for(state='attached')
                check(page.locator('.rp-mini-open canvas').count()==1,f'{name}: original canvas restored')
                check(page.locator('.rp-mini-open canvas').get_attribute('data-pivot') is None,f'{name}: miniature returns to whole-robot framing')
                page.locator('.rp-mini-open').click()
                page.evaluate("selectRobot(null,'')")
                check(not page.locator('.rp-viewer').is_visible(),f'{name}: clearing selection closes inspection')
                page.evaluate("selectRobot(6,'192.0.2.6')")
                page.screenshot(path=str(OUT/f'{name}-desktop.png'),full_page=True)
                right = page.get_by_role('separator', name='Resize right pane', exact=True)
                right.focus();page.keyboard.press('ArrowLeft')
                check(float(right.get_attribute('aria-valuenow')) > (320 if name=='index' else 340), f'{name}: right pane keyboard resizes')
                for _ in range(15): page.keyboard.press('Shift+ArrowLeft')
                check(float(right.get_attribute('aria-valuenow')) <= 560, f'{name}: pane width clamped')
                page.keyboard.press('Home')
                if name=='dashboard':
                    page.evaluate('toggleInspectorDock()')
                    check(not right.is_visible(),f'{name}: collapsed dock hides resize grip')
                    page.evaluate('toggleInspectorDock()')
                for field,value in [('link','telemetry'),('readonly',True),('match',True)]:
                    if field=='link': state['agents'][0]['sys']['link']=value
                    elif field=='readonly': state['agents'][0][field]=value
                    else: state[field]=value
                    page.wait_for_function("document.getElementById('checkManualMode').disabled")
                    check(not page.locator('#robotPanel .ctl-stop').is_visible(),f'{name}: {field} inspection hides commands')
                    page.evaluate('toggleManualMode(true)')
                    page.wait_for_timeout(150)
                    check(not page.locator('#checkManualMode').is_checked(),f'{name}: {field} cannot enter Manual')
                    state['agents'][0]['sys']['link']='control';state['agents'][0]['readonly']=False
                    if field=='match':
                        with page.expect_navigation(wait_until='domcontentloaded'):
                            state['match']=False
                        page.wait_for_function('typeof selectRobot === "function"')
                        page.wait_for_function("document.querySelector('[data-act]') !== null")
                        page.evaluate("switchView('2d');selectRobot(6,'192.0.2.6')")
                    page.wait_for_function("!document.getElementById('checkManualMode').disabled")
                # Ghost control must stay local even though the fixture also has a live real robot.
                page.get_by_role('combobox',name='Session menu').select_option('hybrid')
                ghost = page.locator('[data-act^="sim."]').first
                ghost.wait_for(state='attached')
                ghost_ip = ghost.get_attribute('data-act')
                page.evaluate('(ip)=>selectRobot(1,ip)',ghost_ip)
                page.locator('#checkManualMode').check()
                check(page.locator('.joystick-panel-grid').is_visible(),f'{name}: joystick shown in ghost Manual')
                check(not page.locator('#robotPanel .ctl-stop').is_visible(),f'{name}: ghost has no robot commands')
                joy=page.locator('#joyBoundary').bounding_box()
                page.mouse.move(joy['x']+joy['width']/2,joy['y']+joy['height']/2)
                page.mouse.down();page.mouse.move(joy['x']+joy['width']/2,joy['y']+5,steps=5)
                page.wait_for_timeout(250)
                check('Forward 0.00' not in page.locator('#manualTarget').inner_text(),f'{name}: ghost joystick receives forward input')
                page.mouse.up();page.locator('#checkManualMode').uncheck()
                page.get_by_role('combobox',name='Session menu').select_option('real')
                page.evaluate("selectRobot(6,'192.0.2.6')")
                for width,height,label in [(1024,768,'tablet'),(390,844,'phone')]:
                    page.set_viewport_size({'width':width,'height':height});page.wait_for_timeout(250)
                    if name=='dashboard':
                        page.evaluate("document.getElementById('inspectorDock').classList.remove('collapsed');document.getElementById('toolPanelDock').classList.add('collapsed')")
                    page.screenshot(path=str(OUT/f'{name}-{label}.png'),full_page=True)
                    check(page.evaluate('document.documentElement.scrollWidth <= innerWidth+2'),f'{name}: {label} no horizontal overflow')
                page.set_viewport_size({'width':1440,'height':1000})
                page.wait_for_timeout(150)
                check(float(page.locator('[aria-label="Resize left pane"]').get_attribute('aria-valuenow'))==280,f'{name}: mobile resize preserves desktop preference')
                context.close()
            check(not errors, f'no page errors: {errors}')
            check(not posts, f'inspection/layout/ghost control caused no API POSTs: {posts}')
            browser.close()
            completed = True
    finally:
        server.shutdown()
        (OUT/'results.json').write_text(json.dumps({'completed':completed,'passed':results,'errors':errors,'posts':posts},indent=2))


if __name__ == "__main__":
    main()
