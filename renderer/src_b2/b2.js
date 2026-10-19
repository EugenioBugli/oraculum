// B2 viewer: MuJoCo (WASM, classic renderer unchanged) + WebGL2 replay of its GL 1.5 calls.
//
//   const v = await B2Viewer.create(canvas, {scene: 'b2_scenes/maximus_5v5'});  // or v.load(url) later
//   v.setRobotState('red_Booster-T1_0', {x: -2, y: 1, yaw: 0.5});
//   v.setJoints('red_Booster-T1_0', {AAHead_yaw: 0.3});
//   v.setBall(0.5, 0.2);
//   v.render();                               // kinematics + mjv_updateScene + mjr_render + replay
//
// Options: depth = 'auto' | 'ext' | 'fragdepth' | 'd24' | 'off' (see README), antialias (default
// true: 4 samples per pixel as circus's window; MSAA, or 4 jittered passes in d24/fragdepth), maxTexture (downscale bigger PNG textures; default 2048 on touch
// devices, 0 = off elsewhere), browserTextures (default true), preserve (keep the drawing buffer for
// screenshots), engineUrl (folder of b2_engine.js, default: the folder of b2.js), log (function).
// Full API: README.md. The struct offsets below mirror src_b2/glshim.h.
(function () {
'use strict';
const SCRIPT_BASE = document.currentScript ? new URL('.', document.currentScript.src).href : './';

const VS = `#version 300 es
precision highp float;
precision highp int;
layout(location=0) in vec3 aPos;
layout(location=1) in vec3 aNormal;
layout(location=2) in vec2 aTex;
layout(location=3) in vec4 aColor;
// per-instance data (ShimInstance, 9 texels) from a float texture: few vertex attributes keep
// vertex fetch cheap (it was the bottleneck on Intel with 13 attributes)
uniform highp sampler2D uInst;
uniform int uFirst;
uniform mat4 uProj;
uniform int uLighting, uNumLights, uTexMode, uListColor;
uniform vec4 uLmAmbient;
uniform vec4 uLight[48];  // per light: ambient, diffuse, specular, position, spot, attenuation
out vec4 vColor;
out vec3 vTex;
#ifdef FOG
out float vEyeDist;
#endif
#ifdef FRAGDEPTH
out vec2 vZW;
#endif
void main() {
  int inst = uFirst + gl_InstanceID;
  ivec2 b = ivec2((inst % 128) * 9, inst / 128);
  vec4 iRow0 = texelFetch(uInst, b, 0), iRow1 = texelFetch(uInst, b + ivec2(1, 0), 0);
  vec4 iRow2 = texelFetch(uInst, b + ivec2(2, 0), 0);
  vec4 p = vec4(aPos, 1.0);
  vec3 eye = vec3(dot(iRow0, p), dot(iRow1, p), dot(iRow2, p));
  vec4 clip = uProj * vec4(eye, 1.0);
  gl_Position = clip;
#ifdef FRAGDEPTH
  vZW = clip.zw;
#endif
#ifdef FOG
  vEyeDist = abs(eye.z);
#endif
  vec4 col = uListColor == 1 ? aColor : texelFetch(uInst, b + ivec2(3, 0), 0);
  if (uLighting == 1) {
    // GL_NORMALIZE: inverse transpose of the modelview 3x3, then normalize
    vec3 r0 = iRow0.xyz, r1 = iRow1.xyz, r2 = iRow2.xyz;
    vec3 c0 = cross(r1, r2), c1 = cross(r2, r0), c2 = cross(r0, r1);
    vec3 n = normalize(vec3(dot(c0, aNormal), dot(c1, aNormal), dot(c2, aNormal)) / dot(r0, c0));
    vec3 V = normalize(-eye);  // GL_LIGHT_MODEL_LOCAL_VIEWER
    // GL 1.5 lighting (spec 2.14.1), single color, GL_COLOR_MATERIAL = GL_AMBIENT_AND_DIFFUSE
    vec4 iSpecular = texelFetch(uInst, b + ivec2(5, 0), 0);
    vec3 c = texelFetch(uInst, b + ivec2(4, 0), 0).rgb + col.rgb * uLmAmbient.rgb;
    for (int i = 0; i < 8; i++) {
      if (i >= uNumLights) break;
      vec4 La = uLight[i*6], Ld = uLight[i*6+1], Ls = uLight[i*6+2];
      vec4 Lp = uLight[i*6+3], Lspot = uLight[i*6+4], Latt = uLight[i*6+5];
      vec3 L;
      float f = 1.0;
      if (Lp.w != 0.0) {
        vec3 d = Lp.xyz - eye;
        float dist = length(d);
        L = d / dist;
        f = 1.0 / (Latt.x + Latt.y * dist + Latt.z * dist * dist);
        if (Lspot.w > -1.5) {
          float sd = dot(-L, Lspot.xyz);
          f *= sd >= Lspot.w ? pow(max(sd, 0.0), Latt.w) : 0.0;
        }
      } else {
        L = Lp.xyz;
      }
      float nl = dot(n, L);
      vec3 term = col.rgb * La.rgb;
      if (nl > 0.0) {
        term += nl * col.rgb * Ld.rgb;
        float nh = dot(n, normalize(L + V));
        if (nh > 0.0) term += pow(nh, iSpecular.w) * iSpecular.rgb * Ls.rgb;
      }
      c += f * term;
    }
    vColor = clamp(vec4(c, col.a), 0.0, 1.0);
  } else {
    vColor = clamp(col, 0.0, 1.0);
  }
  if (uTexMode == 1 || uTexMode == 3) {  // texgen planes only when a texture uses them
    vTex = vec3(dot(texelFetch(uInst, b + ivec2(6, 0), 0), p), dot(texelFetch(uInst, b + ivec2(7, 0), 0), p),
                dot(texelFetch(uInst, b + ivec2(8, 0), 0), p));
  } else {
    vTex = vec3(aTex, 0.0);
  }
}`;

const FS = `#version 300 es
precision highp float;
precision highp int;
uniform sampler2D uTex2D;
uniform samplerCube uTexCube;
uniform int uTexMode, uFog;
uniform vec4 uFogColor;
uniform vec2 uFogRange;
in vec4 vColor;
in vec3 vTex;
#ifdef FOG
in float vEyeDist;
#endif
#ifdef FRAGDEPTH
in vec2 vZW;
#endif
out vec4 oColor;
void main() {
  vec4 c = vColor;
  if (uTexMode == 1 || uTexMode == 2) c *= texture(uTex2D, vTex.xy);  // GL_MODULATE
  else if (uTexMode == 3) c *= texture(uTexCube, vTex);
#ifdef FOG
  if (uFog == 1) {
    float f = clamp((uFogRange.y - vEyeDist) / (uFogRange.y - uFogRange.x), 0.0, 1.0);
    c.rgb = mix(uFogColor.rgb, c.rgb, f);
  }
#endif
  oColor = c;
#ifdef FRAGDEPTH
  // MuJoCo's [0, 1] reverse-Z depth, written by the shader: needed without EXT_clip_control
  float z = vZW.x / vZW.y;
  if (z < 0.0) discard;  // beyond the far plane: GL_ZERO_TO_ONE would have clipped it
#ifdef QUANT24
  z = floor(z * 16777215.0 + 0.5) / 16777215.0;  // the 24-bit depth buffer of circus and OSMesa
#endif
  gl_FragDepth = z;
#endif
}`;

// d24 / fragdepth with antialias: the frame is drawn 4 times without MSAA, each time shifted to one sample
// position of 4x MSAA, then this pass writes the mean of the 4 images to the canvas (see _supersample).
const SS_VS = `#version 300 es
void main() {  // one triangle that covers the viewport
  gl_Position = vec4(vec2((gl_VertexID << 1) & 2, gl_VertexID & 2) * 2.0 - 1.0, 0.0, 1.0);
}`;
const SS_FS = `#version 300 es
precision highp float;
uniform highp sampler2D uS0, uS1, uS2, uS3;
out vec4 oColor;
void main() {
  ivec2 p = ivec2(gl_FragCoord.xy);
  oColor = vec4(0.25 * (texelFetch(uS0, p, 0).rgb + texelFetch(uS1, p, 0).rgb +
                        texelFetch(uS2, p, 0).rgb + texelFetch(uS3, p, 0).rgb), 1.0);
}`;
// The 4 sample positions of standard 4x MSAA (D3D/Vulkan: (-2,-6), (6,-2), (-6,2), (2,6) in 1/16 px from the
// pixel centre, y down), here in GL window coordinates (y up). Measured 2026-10-12 (qpos0, 1280x720, circus camera,
// Chrome on the Arc, Firefox, Android emulator, same image): 41.6 dB against the native Arc 4x MSAA reference and 99.3 %
// of the line pixels kept; the old 2x2 ordered grid gave 33.6 dB, 93.8 % and a 2-px stipple along the field lines
// (an ordered grid has only 2 sample columns per pixel), the other y orientation 34.1 dB.
const SS_SAMPLES = [[-2, 6], [6, 2], [-6, -2], [2, -6]].map(([x, y]) => [x / 16, y / 16]);

// struct sizes in 32-bit words (glshim.h)
const CMD = 20, STATE = 240, VERT = 12;
const FRAME_VIEW = 11, FRAME_PROJ = 27;  // ShimFrame.view, .proj
const ATTRS = [[0, 3, 0], [1, 3, 3], [2, 2, 6], [3, 4, 8]];  // location, size, float offset
const GL_LOWER_LEFT = 0x8CA1, GL_ZERO_TO_ONE = 0x935F, GL_NEGATIVE_ONE_TO_ONE = 0x935E;

function compile(gl, defs, vs = VS, fs = FS) {
  const sh = (type, src) => {
    const s = gl.createShader(type);
    gl.shaderSource(s, src.replace('\n', '\n' + defs));
    gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
    return s;
  };
  const p = gl.createProgram();
  gl.attachShader(p, sh(gl.VERTEX_SHADER, vs));
  gl.attachShader(p, sh(gl.FRAGMENT_SHADER, fs));
  gl.linkProgram(p);
  if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p));
  const u = {};
  for (const n of ['uProj', 'uLighting', 'uNumLights', 'uTexMode', 'uListColor', 'uLmAmbient', 'uLight',
                   'uTex2D', 'uTexCube', 'uFog', 'uFogColor', 'uFogRange', 'uInst', 'uFirst']) {
    u[n] = gl.getUniformLocation(p, n);
  }
  gl.useProgram(p);
  gl.uniform1i(u.uTex2D, 0);
  gl.uniform1i(u.uTexCube, 1);
  gl.uniform1i(u.uInst, 2);
  return {p, u};
}

// PNG textures that b2.js can decode exactly as MuJoCo 3.3.3 does (lodepng to 8-bit RGB or RGBA,
// linear color space): rewrite scene.xml in `data` to give MuJoCo a 1x1 texture instead, and
// start decoding the PNG. maxTexture > 0 downscales larger images (an approximation, for phones).
function browserTextures(data, maxTexture) {
  const xmlName = 'scene.xml';
  const doc = new DOMParser().parseFromString(new TextDecoder().decode(data.get(xmlName)), 'application/xml');
  const compiler = doc.querySelector('compiler');
  const dir = compiler && (compiler.getAttribute('texturedir') || compiler.getAttribute('assetdir'));
  if (dir) return [];  // ponytail: the circus scenes use plain relative paths
  const out = [];
  for (const t of doc.getElementsByTagName('texture')) {
    const file = t.getAttribute('file'), name = t.getAttribute('name');
    const nchannel = +(t.getAttribute('nchannel') || 3);
    const bytes = file && data.get(file);
    if (!bytes || !name || t.getAttribute('type') !== '2d' || !/\.png$/i.test(file) ||
        t.hasAttribute('hflip') || t.hasAttribute('vflip') || (nchannel !== 3 && nchannel !== 4) ||
        (t.getAttribute('colorspace') || 'auto') === 'sRGB' || pngHasSRGB(bytes)) continue;
    const blob = new Blob([bytes], {type: 'image/png'});
    const bitmap = createImageBitmap(blob, {premultiplyAlpha: 'none', colorSpaceConversion: 'none'})
      .then((b) => {
        if (!maxTexture || Math.max(b.width, b.height) <= maxTexture) return b;
        const k = maxTexture / Math.max(b.width, b.height), w = Math.round(b.width * k), h = Math.round(b.height * k);
        b.close();
        return createImageBitmap(blob, {premultiplyAlpha: 'none', colorSpaceConversion: 'none',
          resizeWidth: w, resizeHeight: h, resizeQuality: 'high'});
      });
    out.push({name, file, nchannel, bitmap});
    t.removeAttribute('file');
    for (const [k, v] of [['builtin', 'flat'], ['width', '1'], ['height', '1'], ['rgb1', '1 1 1']]) t.setAttribute(k, v);
  }
  if (out.length) data.set(xmlName, new TextEncoder().encode(new XMLSerializer().serializeToString(doc)));
  return out;
}

// MuJoCo uses an sRGB texture format when the PNG has an sRGB chunk (colorspace="auto")
function pngHasSRGB(b) {
  for (let i = 8; i + 8 <= b.length;) {
    const len = ((b[i] << 24) | (b[i + 1] << 16) | (b[i + 2] << 8) | b[i + 3]) >>> 0;
    const type = String.fromCharCode(b[i + 4], b[i + 5], b[i + 6], b[i + 7]);
    if (type === 'sRGB') return true;
    if (type === 'IDAT' || type === 'IEND') return false;
    i += 12 + len;
  }
  return false;
}

// Resolves true when the script ran, false when it could not be loaded. Module level on purpose: a handler
// created inside load() keeps load()'s variables alive, and the <script> element kept the first engine
// (about 234 MB of WebAssembly memory) after a WebGL context restore (heap snapshot, 2026-10-12).
function loadScript(src) {
  return new Promise((done) => {
    const s = document.createElement('script');
    s.src = src;
    s.onload = s.onerror = (e) => {
      s.onload = s.onerror = null;
      done(e.type === 'load');
    };
    document.head.appendChild(s);
  });
}

function b2Error(code, message) {
  const e = new Error(message);
  e.code = code;
  return e;
}

const GEOM = 5;  // mjOBJ_GEOM
const MOUSE = {ROTATE_V: 1, ROTATE_H: 2, MOVE_V: 3, MOVE_H: 4, ZOOM: 5};  // mjtMouse
const CIRCUS_CAMERA = [[0, -1, 0], 15, 90, -45];  // circus viewport: lookat, distance, azimuth, elevation

class B2Viewer {
  // Creates the WebGL2 context and, with opts.scene, loads that scene package.
  // Errors have e.code: 'B2_NO_WEBGL2', 'B2_ENGINE' (b2_engine.js/.wasm), 'B2_SCENE' (scene package).
  static async create(canvas, opts = {}) {
    const v = new B2Viewer(canvas, opts);
    if (opts.scene) await v.load(opts.scene);
    return v;
  }

  constructor(canvas, opts = {}) {
    this.canvas = canvas;
    this.opts = opts;
    this.log = opts.log || ((t) => console.log(t));
    // circus's window has 4x MSAA (CircusApplication.cpp: QSurfaceFormat::setSamples(4)); WebGL's
    // antialias gives the browser's default multisampling (gl.SAMPLES, 4 in Chrome).
    this.antialias = opts.antialias !== false;
    this.gl = canvas.getContext('webgl2', {
      alpha: false, depth: true, stencil: true, antialias: this.antialias, premultipliedAlpha: false,
      preserveDrawingBuffer: !!opts.preserve, powerPreference: 'high-performance',
    });
    if (!this.gl) throw b2Error('B2_NO_WEBGL2', 'WebGL2 is not available in this browser');
    // touch devices: textures above 2048 px are downscaled (same image at the circus camera, see README)
    this.maxTexture = opts.maxTexture ?? (matchMedia('(pointer: coarse)').matches ? 2048 : 0);
    this.ready = false;
    this.lost = false;
    this.glIssues = [];  // "B2 GL unimplemented/unsupported" log lines
    this._hidden = new Map();  // name -> false; re-applied after a context restore
    this._numbers = new Map();
    this._view = new Float32Array(16);
    this._proj = new Float32Array(16);
    this._vp = new Float32Array(16);
    this._size = [0, 0];
    canvas.addEventListener('webglcontextlost', (e) => {
      e.preventDefault();  // allows the restore
      this.lost = true;
      this.ready = false;
      this._freeGpu(false);  // the objects died with the context
      this.log('B2: WebGL context lost');
    });
    canvas.addEventListener('webglcontextrestored', () => {
      this.lost = false;
      this.log('B2: WebGL context restored; reloading the scene');
      this._restore();
    });
  }

  // GPU objects cannot be rebuilt from the engine (vertex arrays are freed after the upload), so a
  // restore loads the scene again in a new engine and puts back pose, camera, hidden robots and
  // numbers. ponytail: a few seconds; the scene files usually come from the HTTP cache.
  async _restore() {
    const keep = this.M && this.sceneUrl ? {qpos: this.getQpos(), cam: this.getCamera()} : null;
    try {
      if (this.sceneUrl) await this.load(this.sceneUrl, keep);
      if (this.ready) this.render();
      this.canvas.dispatchEvent(new Event('b2restored'));
    } catch (e) {
      this.log('B2_ERROR restore: ' + (e && e.stack || e));
    }
  }

  _freeGpu(del = true) {
    const gl = this.gl;
    if (del) {
      for (const t of (this.textures || new Map()).values()) gl.deleteTexture(t);
      for (const it of this.instTex || []) gl.deleteTexture(it.tex);
      for (const p of Object.values(this.progs || {})) gl.deleteProgram(p.p);
      if (this.vbo) gl.deleteBuffer(this.vbo);
      if (this.ebo) gl.deleteBuffer(this.ebo);
      if (this.vao) gl.deleteVertexArray(this.vao);
      if (this._ss) {
        for (const f of this._ss.fbs) gl.deleteFramebuffer(f);
        for (const t of this._ss.texs) gl.deleteTexture(t);
        gl.deleteRenderbuffer(this._ss.depth);
        gl.deleteVertexArray(this._ss.vao);
      }
    }
    this._ss = null;
    this.textures = new Map();
    this.instTex = [];
    this.progs = {};
    this.vbo = this.ebo = this.vao = null;
  }

  // Load a scene package: a folder with files.json ({"files": [...]}, paths relative to the folder),
  // scene.xml, scene_index.json and the assets. Replaces the current scene (a new engine instance).
  async load(scene, keep = null) {
    const gl = this.gl, log = this.log;
    this.ready = false;
    this._freeGpu(!gl.isContextLost());
    this.M = null;
    this._size = [0, 0];
    this.sceneUrl = scene;
    if (!keep) {
      this._hidden.clear();
      this._numbers.clear();
    }
    gl.disable(gl.DITHER);
    this.samples = gl.getParameter(gl.SAMPLES);
    this.clipExt = gl.getExtension('EXT_clip_control');
    // ext: EXT_clip_control, hardware depth. fragdepth: shader-written depth (no extension needed).
    // d24: shader-written depth rounded to 24 bits, as circus's window. off: MuJoCo's own fallback.
    let depth = this.opts.depth || 'auto';
    if (depth === 'auto' || (depth === 'ext' && !this.clipExt)) depth = this.clipExt ? 'ext' : 'd24';
    this.depthMode = depth;

    this.textures = new Map();
    const textures = this.textures;
    const tex = (name) => {
      if (!textures.has(name)) textures.set(name, gl.createTexture());
      return textures.get(name);
    };
    const bindTarget = (target) => (target === gl.TEXTURE_2D ? gl.TEXTURE_2D : gl.TEXTURE_CUBE_MAP);
    this.texBytes = 0;
    const hooks = {
      texImage: (name, target, level, ifmt, w, h, fmt, type, px) => {
        const nch = fmt === 0x1907 ? 3 : fmt === 0x1908 ? 4 : 0;  // GL_RGB, GL_RGBA; depth maps skipped
        if (!nch || !name) return;
        const bt = target === gl.TEXTURE_2D ? gl.TEXTURE_2D : gl.TEXTURE_CUBE_MAP;
        gl.bindTexture(bt, tex(name));
        let data = this.M.HEAPU8.subarray(px, px + w * h * nch);
        let internal = nch === 3 ? gl.RGB8 : gl.RGBA8;
        if (ifmt === 0x8C41) {  // GL_SRGB8: not color-renderable in WebGL2, so no mipmaps; pad to RGBA
          const rgba = new Uint8Array(w * h * 4);
          for (let i = 0, j = 0; i < w * h * 3; i += 3, j += 4) {
            rgba[j] = data[i]; rgba[j + 1] = data[i + 1]; rgba[j + 2] = data[i + 2]; rgba[j + 3] = 255;
          }
          data = rgba;
          fmt = gl.RGBA;
          internal = gl.SRGB8_ALPHA8;
        } else if (ifmt === 0x8C43) {
          internal = gl.SRGB8_ALPHA8;
        }
        gl.texImage2D(target, level, internal, w, h, 0, fmt, gl.UNSIGNED_BYTE, data);
        if (target <= gl.TEXTURE_CUBE_MAP_POSITIVE_X) log(`B2 texture ${name}: ${w}x${h} ifmt=0x${ifmt.toString(16)} fmt=0x${fmt.toString(16)}`);
        this.texBytes += w * h * 4 * (4 / 3);
      },
      texParam: (name, target, pname, param) => {
        if (![0x2800, 0x2801, 0x2802, 0x2803, 0x8072].includes(pname) || !name) return;  // filters, wraps
        gl.bindTexture(bindTarget(target), tex(name));
        gl.texParameteri(bindTarget(target), pname, param);
      },
      genMipmap: (name, target) => {
        if (!name) return;
        gl.bindTexture(bindTarget(target), tex(name));
        gl.generateMipmap(bindTarget(target));
      },
      pixelStore: (pname, param) => {
        if (pname === gl.UNPACK_ALIGNMENT || pname === gl.PACK_ALIGNMENT) gl.pixelStorei(pname, param);
      },
    };
    const engineLog = (t) => {
      if (/^B2 GL (unimplemented|unsupported)/.test(t)) this.glIssues.push(t);
      log(t);
    };

    // engine (b2_engine.js and .wasm next to b2.js unless opts.engineUrl says otherwise)
    const base = (this.opts.engineUrl || SCRIPT_BASE).replace(/\/$/, '');
    if (!window.createB2Engine && !await loadScript(`${base}/b2_engine.js`)) {
      throw b2Error('B2_ENGINE', `cannot load ${base}/b2_engine.js`);
    }
    const t0 = performance.now();
    let M;
    try {
      M = await window.createB2Engine({b2hooks: hooks, print: engineLog, printErr: engineLog,
                                       locateFile: (f) => `${base}/${f}`});
    } catch (e) {
      throw b2Error('B2_ENGINE', `cannot start the engine: ${e}`);
    }
    this.M = M;
    this.glIssues = [];

    // scene files into the virtual file system
    let data;
    try {
      const list = await fetch(`${scene}/files.json`);
      if (!list.ok) throw new Error(`${scene}/files.json: HTTP ${list.status}`);
      const files = (await list.json()).files;
      data = new Map(await Promise.all(files.map(async (f) => {
        const r = await fetch(`${scene}/${f}`);
        if (!r.ok) throw new Error(`${scene}/${f}: HTTP ${r.status}`);
        return [f, new Uint8Array(await r.arrayBuffer())];
      })));
    } catch (e) {
      throw b2Error('B2_SCENE', `cannot download the scene: ${e.message || e}`);
    }
    this.downloadSeconds = (performance.now() - t0) / 1000;
    const index = data.has('scene_index.json')
      ? JSON.parse(new TextDecoder().decode(data.get('scene_index.json'))) : {robots: []};
    // Big PNG textures are decoded by the browser, not by MuJoCo in WebAssembly: MuJoCo gets a
    // 1x1 texture of the same name (same ids, materials and GL state) and the real pixels are
    // uploaded into its GL texture afterwards. This keeps the WASM heap small and loads faster.
    const jsTex = this.opts.browserTextures === false ? [] : browserTextures(data, this.maxTexture);
    const t1 = performance.now();
    for (const [f, bytes] of data) {
      if (jsTex.some((t) => t.file === f)) continue;
      const path = `/scene/${f}`;
      M.FS.mkdirTree(path.slice(0, path.lastIndexOf('/')));
      M.FS.writeFile(path, bytes);
    }
    if (!M.ccall('b2_load', 'number', ['string', 'number'], ['/scene/scene.xml', depth === 'off' ? 0 : 1])) {
      throw b2Error('B2_SCENE', 'MuJoCo could not load the scene (see log)');
    }
    for (const f of data.keys()) if (M.FS.analyzePath(`/scene/${f}`).exists) M.FS.unlink(`/scene/${f}`);
    gl.pixelStorei(gl.UNPACK_COLORSPACE_CONVERSION_WEBGL, gl.NONE);
    gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
    gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
    for (const t of jsTex) {
      const name = M.ccall('b2_texture_name', 'number', ['string'], [t.name]);
      const bitmap = await t.bitmap;
      gl.bindTexture(gl.TEXTURE_2D, textures.get(name));
      const fmt = t.nchannel === 4 ? gl.RGBA : gl.RGB;
      gl.texImage2D(gl.TEXTURE_2D, 0, t.nchannel === 4 ? gl.RGBA8 : gl.RGB8, fmt, gl.UNSIGNED_BYTE, bitmap);
      gl.generateMipmap(gl.TEXTURE_2D);
      this.texBytes += bitmap.width * bitmap.height * 4 * (4 / 3);
      log(`B2 texture ${t.name} (${t.file}): ${bitmap.width}x${bitmap.height} decoded by the browser`);
      bitmap.close();
    }
    this.loadSeconds = (performance.now() - t1) / 1000;
    this.nq = M._b2_nq();
    this.unimplementedAtLoad = M._b2_unimplemented();

    // display lists -> one static vertex buffer + one index buffer
    const lp = M._b2_lists() >> 2;
    const nlist = M.HEAP32[lp], listPtr = M.HEAP32[lp + 1] >> 2, vertPtr = M.HEAP32[lp + 2] >> 2;
    this.nvert = M.HEAP32[lp + 3];
    const indexPtr = M.HEAP32[lp + 4] >> 2, nindex = M.HEAP32[lp + 5];
    this.lists = M.HEAP32.slice(listPtr, listPtr + 4 * nlist);
    this.vao = gl.createVertexArray();
    gl.bindVertexArray(this.vao);
    this.vbo = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, this.vbo);
    gl.bufferData(gl.ARRAY_BUFFER, M.HEAPF32.subarray(vertPtr, vertPtr + this.nvert * VERT), gl.STATIC_DRAW);
    // 16-bit indices relative to each list's first vertex (every list has < 65536 vertices);
    // the vertex attributes are re-pointed at the list's base vertex for each draw
    const idx32 = M.HEAPU32.subarray(indexPtr, indexPtr + nindex), idx16 = new Uint16Array(nindex);
    this.listBase = new Int32Array(nlist);
    for (let l = 0; l < nlist; l++) {
      const first = this.lists[4 * l], count = this.lists[4 * l + 1];
      if (!count) continue;
      let lo = Infinity, hi = 0;
      for (let i = first; i < first + count; i++) { lo = Math.min(lo, idx32[i]); hi = Math.max(hi, idx32[i]); }
      if (hi - lo > 65535) throw new Error('display list with more than 65536 vertices');
      for (let i = first; i < first + count; i++) idx16[i] = idx32[i] - lo;
      this.listBase[l] = lo;
    }
    this.ebo = gl.createBuffer();
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.ebo);
    gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, idx16, gl.STATIC_DRAW);
    this.gpuGeometryBytes = this.nvert * VERT * 4 + nindex * 2;
    M._b2_free_vertices();
    this.curBase = -1;
    gl.enableVertexAttribArray(0);
    gl.enableVertexAttribArray(1);
    this.attrOn = [true, true, false, false];
    // per-instance data textures: rows of 128 instances x 9 RGBA32F texels. Three of them in turn,
    // so that a frame never overwrites a texture the GPU may still read for the previous frame.
    this.instTex = [0, 1, 2].map(() => ({tex: gl.createTexture(), rows: 0}));
    this.frameNo = 0;
    // shader variants: depth written by the shader (fragdepth, d24), linear fog; built on first use
    this.progs = {};
    this._program(depth === 'off' ? 'ext' : depth, false);
    this.stats = {};

    // robots and ball from scene_index.json (exported with the scene by tools/circus_scene)
    const id = (name) => (name ? M.ccall('b2_name2id', 'number', ['number', 'string'], [GEOM, name]) : -1);
    const rgba = M._b2_geom_rgba() >> 2;
    this.robots = new Map();
    for (const r of index.robots || []) {
      const prefix = r.name + '_';
      const joints = {};
      for (const [j, a] of Object.entries(r.hinge_qposadr)) joints[j.startsWith(prefix) ? j.slice(prefix.length) : j] = a;
      const own = id(r.number_geom);
      this.robots.set(r.name, {
        name: r.name, team: r.team, number: r.number, qposadr: r.freejoint.qposadr, bodies: r.body_ids, joints,
        numberGeoms: [1, 2, 3, 4, 5, 6, 7, 8, 9].map((k) => id(`${prefix}num_${k}`)),
        numberRgba: own >= 0 ? Array.from(M.HEAPF32.subarray(rgba + 4 * own, rgba + 4 * own + 4)) : [1, 1, 1, 1],
      });
    }
    const ball = index.ball;
    this.ball = ball ? {qposadr: ball.freejoint.qposadr, body: ball.body_id, radius: M._b2_geom_half_z(id(ball.geom))} : null;
    this.qpos0 = this.getQpos();

    if (keep) {
      this.setQpos(keep.qpos);
      this.setCamera(keep.cam.lookat, keep.cam.distance, keep.cam.azimuth, keep.cam.elevation);
    } else {
      this.resetCamera();
    }
    for (const [name, visible] of this._hidden) this._setVisible(name, visible);
    for (const [name, n] of this._numbers) this.setNumber(name, n);
    this.ready = true;
    log(`B2 ready: depth=${depth} antialias=${this.antialias} samples=${this.samples} nq=${this.nq} robots=${this.robots.size}` +
        ` vertices=${this.nvert} geometry=${(this.gpuGeometryBytes / 1e6).toFixed(1)} MB textures~${(this.texBytes / 1e6).toFixed(1)} MB` +
        ` depth_bits=${gl.getParameter(gl.DEPTH_BITS)} download=${this.downloadSeconds.toFixed(2)} s load=${this.loadSeconds.toFixed(2)} s` +
        ` heap=${(M.HEAPU8.length / 1e6).toFixed(0)} MB gl_unimplemented_at_load=${this.unimplementedAtLoad}`);
  }

  // Calls of GL functions the shim does not implement since the engine started (load + frames), and
  // distinct unsupported GL features. Both must be 0: anything else means the image can differ from circus.
  get glUnimplemented() { return this.M ? this.M._b2_unimplemented() : 0; }
  get glUnsupported() { return this.M ? this.M._b2_unsupported() : 0; }

  // ---------------------------------------------------------------- camera (mjvCamera, free)

  setCamera(lookat, distance, azimuth, elevation) {
    this.M._b2_camera(lookat[0], lookat[1], lookat[2], distance, azimuth, elevation);
  }

  getCamera() {
    const p = this.M._b2_get_camera() >> 3, c = this.M.HEAPF64;
    return {lookat: [c[p], c[p + 1], c[p + 2]], distance: c[p + 3], azimuth: c[p + 4], elevation: c[p + 5]};
  }

  resetCamera() { this.setCamera(...CIRCUS_CAMERA); }

  // mjv_moveCamera(action, reldx, reldy), as circus's viewport; reldx, reldy in viewport heights.
  // Needs one render() first (it reads the camera frame of the last scene update).
  moveCamera(action, reldx, reldy) {
    if (!this._size[0] && action !== MOUSE.ZOOM) return;  // no camera frame yet: would give NaN
    this.M._b2_move_camera(action, reldx, reldy);
  }
  orbit(reldx, reldy) { this.moveCamera(MOUSE.ROTATE_V, reldx, reldy); }  // azimuth -= 180 * reldx, elevation -= 180 * reldy
  pan(reldx, reldy) { this.moveCamera(MOUSE.MOVE_H, reldx, reldy); }  // the scene follows the pointer
  zoom(factor) {  // factor > 1: closer
    const c = this.getCamera();
    this.setCamera(c.lookat, c.distance / factor, c.azimuth, c.elevation);
    this.moveCamera(MOUSE.ZOOM, 0, 0);  // MuJoCo's distance limits
  }

  // Render on the next animation frame (several calls in one frame render once).
  requestRender() {
    if (this._rafPending) return;
    this._rafPending = true;
    requestAnimationFrame(() => { this._rafPending = false; this.render(); });
  }

  // Mouse as circus's viewport (SimulationViewport.cpp): left drag = move in the horizontal plane,
  // shift + left or middle drag = rotate, 0.003 per CSS pixel; wheel = zoom (0.0005 per Qt wheel unit).
  // Touch: one finger rotates, two fingers move (the scene follows the fingers) and pinch-zoom.
  // onChange (default: requestRender) runs after each camera change. Returns a function that detaches.
  attachControls(el = this.canvas, onChange = () => this.requestRender()) {
    const pts = new Map();
    let mouseAction = 0;
    el.style.touchAction = 'none';
    const down = (e) => {
      if (!this.ready) return;
      try { el.setPointerCapture(e.pointerId); } catch (err) { /* synthetic events have no capture */ }
      pts.set(e.pointerId, [e.clientX, e.clientY]);
      if (e.pointerType === 'mouse') {
        mouseAction = e.button === 1 || (e.button === 0 && e.shiftKey) ? MOUSE.ROTATE_V : e.button === 0 ? MOUSE.MOVE_H : 0;
      }
    };
    const move = (e) => {
      const p = pts.get(e.pointerId);
      if (!p || !this.ready) return;
      const dx = e.clientX - p[0], dy = e.clientY - p[1];
      if (e.pointerType === 'mouse') {
        if (mouseAction) this.moveCamera(mouseAction, 0.003 * dx, 0.003 * dy);
      } else if (pts.size === 1) {
        this.orbit(0.003 * dx, 0.003 * dy);
      } else if (pts.size === 2) {
        const q = [...pts.entries()].find(([k]) => k !== e.pointerId)[1];
        const before = Math.hypot(p[0] - q[0], p[1] - q[1]), after = Math.hypot(e.clientX - q[0], e.clientY - q[1]);
        const h = el.clientHeight || 1;
        this.pan(dx / 2 / h, dy / 2 / h);  // the midpoint moves by half of this finger's move
        if (before > 0 && after > 0) this.zoom(after / before);
      }
      p[0] = e.clientX;
      p[1] = e.clientY;
      onChange();
    };
    const up = (e) => {
      pts.delete(e.pointerId);
      if (e.pointerType === 'mouse') mouseAction = 0;
    };
    const wheel = (e) => {
      if (!this.ready) return;
      e.preventDefault();
      const notches = e.deltaMode === 1 ? e.deltaY / 3 : e.deltaY / 100;  // Qt: 120 units per notch, up > 0
      this.moveCamera(MOUSE.ZOOM, 0, -0.0005 * 120 * notches);
      onChange();
    };
    const ev = [['pointerdown', down], ['pointermove', move], ['pointerup', up], ['pointercancel', up], ['wheel', wheel]];
    for (const [n, f] of ev) el.addEventListener(n, f, {passive: n !== 'wheel'});
    return () => { for (const [n, f] of ev) el.removeEventListener(n, f); };
  }

  // View (world -> eye) and projection matrices of the last render(), column-major as OpenGL, and
  // viewProj = proj * view (world -> clip). Clip space is MuJoCo's reverse-Z; x and y are standard.
  // width, height: the drawing-buffer size of that frame (canvas pixels).
  getViewProjection() {
    return {view: this._view.slice(), proj: this._proj.slice(), viewProj: this._vp.slice(),
            width: this._size[0], height: this._size[1]};
  }

  // World point (metres, MuJoCo/field frame) -> [x, y] in canvas pixels of the last frame, origin at
  // the top-left corner; null when the point is behind the camera. Divide by
  // canvas.width / canvas.clientWidth to get CSS pixels.
  project(x, y, z = 0) {
    const m = this._vp;
    const cx = m[0] * x + m[4] * y + m[8] * z + m[12], cy = m[1] * x + m[5] * y + m[9] * z + m[13];
    const cw = m[3] * x + m[7] * y + m[11] * z + m[15];
    if (!(cw > 0)) return null;
    return [(cx / cw * 0.5 + 0.5) * this._size[0], (0.5 - cy / cw * 0.5) * this._size[1]];
  }

  // ---------------------------------------------------------------- state (qpos)

  setQpos(q) {
    if (q.length !== this.nq) throw new Error(`qpos has ${q.length} values, the model has nq=${this.nq}`);
    this.M.HEAPF64.set(q, this.M._b2_qpos() >> 3);
  }

  getQpos() {
    const p = this.M._b2_qpos() >> 3;
    return this.M.HEAPF64.slice(p, p + this.nq);
  }

  // Robot names of the scene (scene_index.json): <team>_Booster-T1_<i>, with team and jersey number.
  listRobots() {
    return [...this.robots.values()].map((r) => ({name: r.name, team: r.team, number: r.number}));
  }

  // Robot root pose on the field: x, y (m), yaw (rad about +z, 0 = facing +x), z (m, default: the
  // scene's start height). Writes the robot's free joint (qpos x y z qw qx qy qz). false: no such robot.
  setRobotState(name, {x, y, yaw = 0, z}) {
    const r = this.robots.get(name);
    if (!r) return false;
    const a = r.qposadr, q = this.M.HEAPF64, p = (this.M._b2_qpos() >> 3) + a;
    q[p] = x;
    q[p + 1] = y;
    q[p + 2] = z ?? this.qpos0[a + 2];
    q[p + 3] = Math.cos(yaw / 2);
    q[p + 4] = 0;
    q[p + 5] = 0;
    q[p + 6] = Math.sin(yaw / 2);
    return true;
  }

  // Hinge angles (rad) by joint name without the robot prefix (e.g. AAHead_yaw), as AgentMsg.joints.
  // Joints not given keep their value; unknown names are ignored. Returns the number of joints set.
  setJoints(name, joints) {
    const r = this.robots.get(name);
    if (!r) return 0;
    const q = this.M.HEAPF64, p = this.M._b2_qpos() >> 3;
    let n = 0;
    for (const [j, v] of Object.entries(joints)) {
      const a = r.joints[j];
      if (a !== undefined && Number.isFinite(v)) { q[p + a] = v; n++; }
    }
    return n;
  }

  // Ball centre (m); z defaults to the ball radius (on the ground). Orientation is kept.
  setBall(x, y, z) {
    if (!this.ball) return false;
    const q = this.M.HEAPF64, p = (this.M._b2_qpos() >> 3) + this.ball.qposadr;
    q[p] = x;
    q[p + 1] = y;
    q[p + 2] = z ?? this.ball.radius;
    return true;
  }

  // Show or hide a robot: its geoms and sites are left out of the scene (not moved under the floor).
  setRobotVisible(name, visible) {
    if (!this.robots.has(name)) return false;
    if (visible) this._hidden.delete(name); else this._hidden.set(name, false);
    return this._setVisible(name, visible);
  }

  setBallVisible(visible) {
    if (!this.ball) return false;
    if (visible) this._hidden.delete('ball'); else this._hidden.set('ball', false);
    return this._setVisible('ball', visible);
  }

  _setVisible(name, visible) {
    const [first, last] = name === 'ball' ? [this.ball.body, this.ball.body] : this.robots.get(name).bodies;
    this.M._b2_hide_bodies(first, last, visible ? 0 : 1);
    return true;
  }

  // Jersey number 1..9 as circus draws it (geom num_<n> visible with the number colour, the other
  // eight with alpha 0); any other n shows no number, as circus above 9.
  setNumber(name, n) {
    const r = this.robots.get(name);
    if (!r) return false;
    this._numbers.set(name, n);
    const p = this.M._b2_geom_rgba() >> 2, F = this.M.HEAPF32;
    r.numberGeoms.forEach((g, k) => {
      if (g >= 0) F.set(k + 1 === n ? r.numberRgba : [1, 1, 1, 0], p + 4 * g);
    });
    return true;
  }

  // Debug only: change one circus view option (mjvOption flags[i] or geomgroup[i]). The negative
  // CI test uses it to check that the pixel test fails when the view differs from circus.
  setViewOption(kind, i, value) {
    if (kind === 'flag') this.M._b2_set_flag(i, value);
    else if (kind === 'geomgroup') this.M._b2_set_geomgroup(i, value);
    else throw new Error(`unknown view option ${kind}`);
  }

  // ---------------------------------------------------------------- frame

  // physics: 2 = kinematics only (default), 1 = mj_forward, 0 = mjData as is.
  // Returns the frame statistics, or null while the scene loads or the WebGL context is lost.
  render(physics = 2) {
    if (!this.ready) return null;
    const {gl, M} = this;
    const w = this.canvas.width, h = this.canvas.height;
    const t0 = performance.now();
    const ss = this.antialias && (this.depthMode === 'd24' || this.depthMode === 'fragdepth') ? this._supersample(w, h) : null;
    const fp = M._b2_frame(w, h, physics) >> 2;
    const t1 = performance.now();
    const H32 = M.HEAP32, F32 = M.HEAPF32;
    const ncmd = H32[fp], ninst = H32[fp + 1], clip = H32[fp + 3];
    const cmd = H32[fp + 4] >> 2, inst = H32[fp + 5] >> 2, state = H32[fp + 6] >> 2;
    this.stats = {ndraw: H32[fp + 7], nskipped: H32[fp + 8], unimplemented: H32[fp + 9], ncmd, ninst,
                  nstate: H32[fp + 2], wasmUpdateMs: M._b2_time_update(), wasmRenderMs: M._b2_time_render()};
    this._view.set(F32.subarray(fp + FRAME_VIEW, fp + FRAME_VIEW + 16));
    this._proj.set(F32.subarray(fp + FRAME_PROJ, fp + FRAME_PROJ + 16));
    for (let c = 0; c < 4; c++) {
      for (let r = 0; r < 4; r++) {
        let s = 0;
        for (let k = 0; k < 4; k++) s += this._proj[k * 4 + r] * this._view[c * 4 + k];
        this._vp[c * 4 + r] = s;
      }
    }
    this._size = [w, h];

    gl.bindVertexArray(this.vao);
    const rows = Math.ceil(ninst / 128);
    gl.activeTexture(gl.TEXTURE2);
    const it = this.instTex[this.frameNo++ % 3];
    gl.bindTexture(gl.TEXTURE_2D, it.tex);
    if (rows > it.rows) {
      it.rows = Math.max(rows, 2 * it.rows);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA32F, 1152, it.rows, 0, gl.RGBA, gl.FLOAT, null);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
    }
    if (rows) gl.texSubImage2D(gl.TEXTURE_2D, 0, 0, 0, 1152, rows, gl.RGBA, gl.FLOAT, F32, inst);
    gl.activeTexture(gl.TEXTURE0);
    const mode = clip ? this.depthMode : 'off';
    if (this.clipExt) {
      this.clipExt.clipControlEXT(GL_LOWER_LEFT, mode === 'ext' || mode === 'd24' ? GL_ZERO_TO_ONE : GL_NEGATIVE_ONE_TO_ONE);
    }
    let fog = false;
    for (let k = 0; k < H32[fp + 2]; k++) fog = fog || H32[state + k * STATE + 11] !== 0;
    const prog = this._program(mode, fog);
    gl.useProgram(prog.p);
    const u = prog.u;
    let ndraw = 0;
    for (let pass = 0; pass < (ss ? 4 : 1); pass++) {  // ss: one pass per sample position
    gl.bindFramebuffer(gl.FRAMEBUFFER, ss ? ss.fbs[pass] : null);
    this._jit = ss ? SS_SAMPLES[pass] : null;
    let cur = -1;
    for (let c = 0; c < ncmd; c++) {
      const o = cmd + c * CMD;
      if (H32[o] === 1) {  // clear
        if (H32[o + 6]) {
          gl.enable(gl.SCISSOR_TEST);
          gl.scissor(H32[o + 8], H32[o + 9], H32[o + 10], H32[o + 11]);
        }
        gl.clearColor(F32[o + 12], F32[o + 13], F32[o + 14], F32[o + 15]);
        gl.clearDepth(F32[o + 16]);
        gl.colorMask(true, true, true, true);
        gl.depthMask(true);
        gl.clear(H32[o + 5] & (gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT | gl.STENCIL_BUFFER_BIT));
        gl.disable(gl.SCISSOR_TEST);
        cur = -1;
        continue;
      }
      const s = H32[o + 1], list = H32[o + 2], first = H32[o + 3], count = H32[o + 4];
      if (s !== cur) {
        this._applyState(state + s * STATE, u);
        cur = s;
      }
      const L = this.lists, hasTex = L[4 * list + 2] !== 0, hasColor = L[4 * list + 3] !== 0;
      if (hasTex !== this.attrOn[2]) { hasTex ? gl.enableVertexAttribArray(2) : gl.disableVertexAttribArray(2); this.attrOn[2] = hasTex; }
      if (hasColor !== this.attrOn[3]) { hasColor ? gl.enableVertexAttribArray(3) : gl.disableVertexAttribArray(3); this.attrOn[3] = hasColor; }
      gl.uniform1i(u.uListColor, hasColor ? 1 : 0);
      gl.uniform1i(u.uFirst, first);
      const base = this.listBase[list];
      if (base !== this.curBase) {
        gl.bindBuffer(gl.ARRAY_BUFFER, this.vbo);
        for (const [loc, size, off] of ATTRS) gl.vertexAttribPointer(loc, size, gl.FLOAT, false, VERT * 4, (base * VERT + off) * 4);
        this.curBase = base;
      }
      gl.drawElementsInstanced(gl.TRIANGLES, L[4 * list + 1], gl.UNSIGNED_SHORT, 2 * L[4 * list], count);
      ndraw++;
    }
    }
    this._jit = null;
    if (ss) {  // mean of the 4 passes -> canvas
      gl.bindFramebuffer(gl.FRAMEBUFFER, null);
      gl.viewport(0, 0, w, h);
      gl.disable(gl.BLEND);
      gl.disable(gl.DEPTH_TEST);
      gl.disable(gl.CULL_FACE);
      gl.colorMask(true, true, true, true);
      gl.useProgram(this.progs.ss.p);
      gl.bindVertexArray(ss.vao);
      for (let k = 0; k < 4; k++) { gl.activeTexture(gl.TEXTURE3 + k); gl.bindTexture(gl.TEXTURE_2D, ss.texs[k]); }
      gl.drawArrays(gl.TRIANGLES, 0, 3);
      for (let k = 0; k < 4; k++) { gl.activeTexture(gl.TEXTURE3 + k); gl.bindTexture(gl.TEXTURE_2D, null); }  // no feedback loop
      gl.activeTexture(gl.TEXTURE0);
    }
    this.stats.supersample = !!ss;
    this.stats.webglDraws = ndraw;
    this.stats.jsMs = performance.now() - t1;
    this.stats.frameCpuMs = performance.now() - t0;
    return this.stats;
  }

  // The targets of a d24 or fragdepth frame with antialias. Those modes write the depth in the shader, and
  // with MSAA a pixel then has one depth value for all its samples: thin coplanar geometry such as the 5 cm
  // field lines broke up into dashes (62 % of the line pixels kept, 95-97 % in ext mode). So the frame is drawn
  // 4 times without MSAA (RGBA8 each, one depth 24 / stencil 8 buffer), each shifted to one 4x MSAA sample position
  // (SS_SAMPLES), and averaged: 4 samples per pixel, plain mean, as circus's 4x MSAA on Mesa.
  // ponytail: 4x the WebGL draw calls of one frame (measured: Android emulator 7.8 ms per synced frame against
  // 4.9 ms for one 2x2 supersampled pass, still 60 fps); same memory as 2x2 supersampling.
  _supersample(w, h) {
    const gl = this.gl;
    this._ssMax = this._ssMax || Math.min(gl.getParameter(gl.MAX_RENDERBUFFER_SIZE), gl.getParameter(gl.MAX_TEXTURE_SIZE));
    if (!w || !h || w > this._ssMax || h > this._ssMax) return null;
    if (!this._ss) {
      this._ss = {fbs: [0, 1, 2, 3].map(() => gl.createFramebuffer()), texs: [0, 1, 2, 3].map(() => gl.createTexture()),
                  depth: gl.createRenderbuffer(), vao: gl.createVertexArray(), w: 0, h: 0};
      if (!this.progs.ss) {
        this.progs.ss = compile(gl, '', SS_VS, SS_FS);
        for (let k = 0; k < 4; k++) gl.uniform1i(gl.getUniformLocation(this.progs.ss.p, `uS${k}`), 3 + k);
      }
    }
    const s = this._ss;
    if (s.w !== w || s.h !== h) {
      gl.activeTexture(gl.TEXTURE0);
      gl.bindRenderbuffer(gl.RENDERBUFFER, s.depth);
      gl.renderbufferStorage(gl.RENDERBUFFER, gl.DEPTH24_STENCIL8, w, h);
      for (let k = 0; k < 4; k++) {
        gl.bindTexture(gl.TEXTURE_2D, s.texs[k]);
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, w, h, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
        gl.bindFramebuffer(gl.FRAMEBUFFER, s.fbs[k]);
        gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, s.texs[k], 0);
        gl.framebufferRenderbuffer(gl.FRAMEBUFFER, gl.DEPTH_STENCIL_ATTACHMENT, gl.RENDERBUFFER, s.depth);
      }
      gl.bindTexture(gl.TEXTURE_2D, null);
      gl.bindFramebuffer(gl.FRAMEBUFFER, null);
      s.w = w;
      s.h = h;
    }
    return s;
  }

  _program(mode, fog) {
    const key = `${mode}${fog ? '+fog' : ''}`;
    if (!this.progs[key]) {
      const defs = (mode === 'fragdepth' || mode === 'd24' ? '#define FRAGDEPTH 1\n' : '') +
                   (mode === 'd24' ? '#define QUANT24 1\n' : '') + (fog ? '#define FOG 1\n' : '');
      this.progs[key] = compile(this.gl, defs);
    }
    return this.progs[key];
  }

  _applyState(o, u) {
    const {gl, M} = this;
    const I = M.HEAP32, F = M.HEAPF32;
    gl.viewport(I[o + 16], I[o + 17], I[o + 18], I[o + 19]);
    if (I[o + 1]) { gl.enable(gl.BLEND); gl.blendFunc(I[o + 2], I[o + 3]); } else gl.disable(gl.BLEND);
    if (I[o + 4]) gl.enable(gl.DEPTH_TEST); else gl.disable(gl.DEPTH_TEST);
    gl.depthMask(!!I[o + 5]);
    gl.depthFunc(I[o + 6]);
    if (I[o + 7]) gl.enable(gl.CULL_FACE); else gl.disable(gl.CULL_FACE);
    gl.cullFace(I[o + 8]);
    gl.frontFace(I[o + 9]);
    const cm = I[o + 10];
    gl.colorMask(!!(cm & 1), !!(cm & 2), !!(cm & 4), !!(cm & 8));
    const P = F.subarray(o + 20, o + 36);
    if (this._jit) {  // shift the image by minus the sample offset: the pixel centre then samples there
      const J = this._jp || (this._jp = new Float32Array(16)), jx = -2 * this._jit[0] / I[o + 18], jy = -2 * this._jit[1] / I[o + 19];
      J.set(P);
      for (let c = 0; c < 4; c++) { J[4 * c] += jx * J[4 * c + 3]; J[4 * c + 1] += jy * J[4 * c + 3]; }
      gl.uniformMatrix4fv(u.uProj, false, J);
    } else gl.uniformMatrix4fv(u.uProj, false, P);
    gl.uniform1i(u.uLighting, I[o]);
    gl.uniform1i(u.uNumLights, I[o + 14]);
    gl.uniform4fv(u.uLmAmbient, F.subarray(o + 36, o + 40));
    if (I[o + 14]) gl.uniform4fv(u.uLight, F.subarray(o + 48, o + 48 + 24 * I[o + 14]));
    const mode = I[o + 12];
    gl.uniform1i(u.uTexMode, mode);
    if (mode === 3) {
      gl.activeTexture(gl.TEXTURE1);
      gl.bindTexture(gl.TEXTURE_CUBE_MAP, this.textures.get(I[o + 13]) || null);
      gl.activeTexture(gl.TEXTURE0);
    } else if (mode) {
      gl.bindTexture(gl.TEXTURE_2D, this.textures.get(I[o + 13]) || null);
    }
    gl.uniform1i(u.uFog, I[o + 11]);
    if (I[o + 11]) {
      gl.uniform4fv(u.uFogColor, F.subarray(o + 40, o + 44));
      gl.uniform2f(u.uFogRange, F[o + 44], F[o + 45]);
    }
    if (I[o + 15] && !this._warned) {
      this._warned = true;
      this.log('B2: the scene uses a GL feature this replay does not support (see the log above)');
    }
  }

  // Frames per second of requestAnimationFrame rendering over ms milliseconds.
  fps(ms = 5000, physics = 2) {
    return new Promise((done) => {
      let n = 0;
      const t0 = performance.now();
      const frame = (t) => {
        this.render(physics);
        n++;
        if (t - t0 < ms) requestAnimationFrame(frame);
        else done(n * 1000 / (t - t0));
      };
      requestAnimationFrame(frame);
    });
  }

  // Mean ms per frame, CPU + GPU: each frame ends with a 1-pixel readPixels (waits for the GPU).
  benchSync(n = 20, physics = 2) {
    const px = new Uint8Array(4);
    const t0 = performance.now();
    for (let i = 0; i < n; i++) {
      this.render(physics);
      this.gl.readPixels(0, 0, 1, 1, this.gl.RGBA, this.gl.UNSIGNED_BYTE, px);
    }
    return (performance.now() - t0) / n;
  }

  // Mean ms per frame when n frames are queued back to back (one readPixels at the end):
  // the frame rate the page could reach without the display's refresh limit.
  benchThroughput(n = 60, physics = 2) {
    const px = new Uint8Array(4);
    this.gl.readPixels(0, 0, 1, 1, this.gl.RGBA, this.gl.UNSIGNED_BYTE, px);
    const t0 = performance.now();
    for (let i = 0; i < n; i++) this.render(physics);
    this.gl.readPixels(0, 0, 1, 1, this.gl.RGBA, this.gl.UNSIGNED_BYTE, px);
    return (performance.now() - t0) / n;
  }
}

B2Viewer.MOUSE = MOUSE;
B2Viewer.CIRCUS_CAMERA = CIRCUS_CAMERA;
window.B2Viewer = B2Viewer;
})();
