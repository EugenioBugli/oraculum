// B2 GL shim: OpenGL 1.5 fixed-function state machine for MuJoCo's classic renderer.
//
// MuJoCo's render code (mjr_makeContext, mjr_render, unchanged) calls these functions through its
// glad loader. Display lists become vertex arrays (uploaded once by b2.js), glCallList becomes one
// instance of a draw with a snapshot of the GL state, and b2.js replays the frame on WebGL2 with
// shaders that implement the fixed-function equations (lighting, texgen, fog) of the GL 1.5 spec.
// Only what MuJoCo's classic renderer uses is implemented; anything else is logged once
// ("B2 GL unimplemented: <name>") by the generated stubs in glstubs.c.
#include <dlfcn.h>
#include <emscripten.h>
#include <link.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "render/glad/glad.h"
#include "glshim.h"

// ------------------------------------------------------------------ JS hooks (textures, log)

EM_JS(void, js_tex_image, (unsigned name, unsigned target, int level, int ifmt, int w, int h,
                           unsigned fmt, unsigned type, const void* px),
      { Module.b2hooks.texImage(name, target, level, ifmt, w, h, fmt, type, px); });
EM_JS(void, js_tex_param, (unsigned name, unsigned target, unsigned pname, int param),
      { Module.b2hooks.texParam(name, target, pname, param); });
EM_JS(void, js_gen_mipmap, (unsigned name, unsigned target),
      { Module.b2hooks.genMipmap(name, target); });
EM_JS(void, js_pixel_store, (unsigned pname, int param),
      { Module.b2hooks.pixelStore(pname, param); });

static int nunimpl, nunimplTotal, nunsupported;
int shim_unimpl_total(void) { return nunimplTotal; }
int shim_unsupported_total(void) { return nunsupported; }
void shim_unimpl(const char* name) {
  static char seen[64][48];
  static int nseen;
  nunimpl++;
  nunimplTotal++;
  for (int i = 0; i < nseen; i++) if (!strcmp(seen[i], name)) return;
  if (nseen < 64) snprintf(seen[nseen++], sizeof(seen[0]), "%s", name);
  printf("B2 GL unimplemented: %s\n", name);
}

static void unsupported_once(const char* what) {
  static char seen[32][48];
  static int nseen;
  for (int i = 0; i < nseen; i++) if (!strcmp(seen[i], what)) return;
  if (nseen < 32) snprintf(seen[nseen++], sizeof(seen[0]), "%s", what);
  nunsupported++;
  printf("B2 GL unsupported feature used: %s\n", what);
}

// ------------------------------------------------------------------ matrices (Mesa m_matrix.c math)

typedef struct { float m[16]; } Mat;  // column-major

static void mat_identity(float* m) {
  memset(m, 0, 16 * sizeof(float));
  m[0] = m[5] = m[10] = m[15] = 1;
}

static void mat_mul(float* r, const float* a, const float* b) {  // r = a * b, r may alias a
  float t[16];
  for (int c = 0; c < 4; c++) {
    for (int i = 0; i < 4; i++) {
      t[c*4+i] = a[i]*b[c*4] + a[4+i]*b[c*4+1] + a[8+i]*b[c*4+2] + a[12+i]*b[c*4+3];
    }
  }
  memcpy(r, t, sizeof(t));
}

#define STACK 64
static Mat mvStack[STACK], prStack[8], txStack[8];
static int mvTop, prTop, txTop;
static GLenum matMode = GL_MODELVIEW;
static int stateDirty = 1;

static float* curmat(void) {
  if (matMode == GL_PROJECTION) return prStack[prTop].m;
  if (matMode == GL_TEXTURE) return txStack[txTop].m;
  return mvStack[mvTop].m;
}
static void touched(void) { if (matMode == GL_PROJECTION) stateDirty = 1; }

void shim_glMatrixMode(GLenum mode) { matMode = mode; }
void shim_glLoadIdentity(void) { mat_identity(curmat()); touched(); }
void shim_glLoadMatrixf(const GLfloat* m) { memcpy(curmat(), m, 16 * sizeof(float)); touched(); }
void shim_glMultMatrixf(const GLfloat* m) { float* c = curmat(); mat_mul(c, c, m); touched(); }

void shim_glPushMatrix(void) {
  if (matMode == GL_PROJECTION) { if (prTop < 7) { prStack[prTop+1] = prStack[prTop]; prTop++; } }
  else if (matMode == GL_TEXTURE) { if (txTop < 7) { txStack[txTop+1] = txStack[txTop]; txTop++; } }
  else if (mvTop < STACK - 1) { mvStack[mvTop+1] = mvStack[mvTop]; mvTop++; }
}
void shim_glPopMatrix(void) {
  if (matMode == GL_PROJECTION) { if (prTop > 0) prTop--; stateDirty = 1; }
  else if (matMode == GL_TEXTURE) { if (txTop > 0) txTop--; }
  else if (mvTop > 0) mvTop--;
}

void shim_glTranslatef(GLfloat x, GLfloat y, GLfloat z) {
  float* m = curmat();
  m[12] = m[0]*x + m[4]*y + m[8]*z + m[12];
  m[13] = m[1]*x + m[5]*y + m[9]*z + m[13];
  m[14] = m[2]*x + m[6]*y + m[10]*z + m[14];
  m[15] = m[3]*x + m[7]*y + m[11]*z + m[15];
  touched();
}

void shim_glScalef(GLfloat x, GLfloat y, GLfloat z) {
  float* m = curmat();
  for (int i = 0; i < 4; i++) { m[i] *= x; m[4+i] *= y; m[8+i] *= z; }
  touched();
}

void shim_glRotatef(GLfloat angle, GLfloat x, GLfloat y, GLfloat z) {
  float r[16], len = sqrtf(x*x + y*y + z*z);
  if (len == 0) return;
  x /= len; y /= len; z /= len;
  float s = sinf(angle * (float)M_PI / 180.0f), c = cosf(angle * (float)M_PI / 180.0f), t = 1 - c;
  mat_identity(r);
  r[0] = x*x*t + c;   r[4] = x*y*t - z*s; r[8]  = x*z*t + y*s;
  r[1] = y*x*t + z*s; r[5] = y*y*t + c;   r[9]  = y*z*t - x*s;
  r[2] = z*x*t - y*s; r[6] = z*y*t + x*s; r[10] = z*z*t + c;
  float* m = curmat();
  mat_mul(m, m, r);
  touched();
}

void shim_glFrustum(GLdouble l, GLdouble r, GLdouble b, GLdouble t, GLdouble n, GLdouble f) {
  float left = (float)l, right = (float)r, bottom = (float)b, top = (float)t;
  float nearval = (float)n, farval = (float)f, m[16] = {0};
  m[0] = (2.0f*nearval) / (right-left);
  m[5] = (2.0f*nearval) / (top-bottom);
  m[8] = (right+left) / (right-left);
  m[9] = (top+bottom) / (top-bottom);
  m[10] = -(farval+nearval) / (farval-nearval);
  m[11] = -1;
  m[14] = -(2.0f*farval*nearval) / (farval-nearval);
  float* c = curmat();
  mat_mul(c, c, m);
  touched();
}

void shim_glOrtho(GLdouble l, GLdouble r, GLdouble b, GLdouble t, GLdouble n, GLdouble f) {
  float left = (float)l, right = (float)r, bottom = (float)b, top = (float)t;
  float nearval = (float)n, farval = (float)f, m[16];
  mat_identity(m);
  m[0] = 2.0f / (right-left);
  m[12] = -(right+left) / (right-left);
  m[5] = 2.0f / (top-bottom);
  m[13] = -(top+bottom) / (top-bottom);
  m[10] = -2.0f / (farval-nearval);
  m[14] = -(farval+nearval) / (farval-nearval);
  float* c = curmat();
  mat_mul(c, c, m);
  touched();
}

// ------------------------------------------------------------------ fixed-function state

typedef struct {
  float ambient[4], diffuse[4], specular[4], position[4], spotdir[3];
  float exponent, cutoff, att[3];
  int enabled;
} Light;

typedef struct {
  int en2D, enCube, gen[4];
  GLuint bound2D, boundCube;
  float objPlane[4][4];
} TexUnit;

static Light lights[SHIM_MAXLIGHT];
static TexUnit tex[2];
static int activeUnit;
static float curColor[4] = {1, 1, 1, 1}, curNormal[3] = {0, 0, 1}, curTex[2];
static float matEmission[4] = {0, 0, 0, 1}, matSpecular[4] = {0, 0, 0, 1}, matShininess;
static float lmAmbient[4] = {0.2f, 0.2f, 0.2f, 1};
static int localViewer, twoSide;
static int lighting, colorMaterial, blend, depthTest, cull, fog, alphaTest, stencil, clip0, scissor;
static int blendSrc = GL_ONE, blendDst = GL_ZERO, depthMask = 1, depthFunc = GL_LESS;
static int cullMode = GL_BACK, frontFace = GL_CCW, colorMask = 15, polyFill = 1, texEnvModulate = 1;
static int viewport[4], scissorRect[4];
static float clearColor[4], clearDepth = 1;
static float fogColor[4], fogStart, fogEnd = 1;
static int clipControl, advertiseClipControl = 1;
static GLuint boundFBO;

static void init_state(void) {
  mat_identity(mvStack[0].m);
  mat_identity(prStack[0].m);
  mat_identity(txStack[0].m);
  for (int i = 0; i < SHIM_MAXLIGHT; i++) {
    Light* L = lights + i;
    memset(L, 0, sizeof(Light));
    L->ambient[3] = L->diffuse[3] = L->specular[3] = 1;
    if (i == 0) { L->diffuse[0] = L->diffuse[1] = L->diffuse[2] = 1; L->specular[0] = L->specular[1] = L->specular[2] = 1; }
    L->position[2] = 1;
    L->spotdir[2] = -1;
    L->cutoff = 180;
    L->att[0] = 1;
  }
  for (int u = 0; u < 2; u++) {
    memset(tex + u, 0, sizeof(TexUnit));
    tex[u].objPlane[0][0] = 1;
    tex[u].objPlane[1][1] = 1;
  }
}

static int* capflag(GLenum cap) {
  switch (cap) {
    case GL_LIGHTING: return &lighting;
    case GL_COLOR_MATERIAL: return &colorMaterial;
    case GL_BLEND: return &blend;
    case GL_DEPTH_TEST: return &depthTest;
    case GL_CULL_FACE: return &cull;
    case GL_FOG: return &fog;
    case GL_ALPHA_TEST: return &alphaTest;
    case GL_STENCIL_TEST: return &stencil;
    case GL_CLIP_PLANE0: return &clip0;
    case GL_SCISSOR_TEST: return &scissor;
    case GL_TEXTURE_2D: return &tex[activeUnit].en2D;
    case GL_TEXTURE_CUBE_MAP: return &tex[activeUnit].enCube;
    case GL_TEXTURE_GEN_S: return &tex[activeUnit].gen[0];
    case GL_TEXTURE_GEN_T: return &tex[activeUnit].gen[1];
    case GL_TEXTURE_GEN_R: return &tex[activeUnit].gen[2];
    case GL_TEXTURE_GEN_Q: return &tex[activeUnit].gen[3];
  }
  if (cap >= GL_LIGHT0 && cap < GL_LIGHT0 + SHIM_MAXLIGHT) return &lights[cap - GL_LIGHT0].enabled;
  return NULL;  // GL_NORMALIZE (always on in the shader), GL_MULTISAMPLE, debug output, ...
}

void shim_glEnable(GLenum cap) { int* f = capflag(cap); if (f) { *f = 1; stateDirty = 1; } }
void shim_glDisable(GLenum cap) { int* f = capflag(cap); if (f) { *f = 0; stateDirty = 1; } }
GLboolean shim_glIsEnabled(GLenum cap) { int* f = capflag(cap); return f ? (GLboolean)(*f != 0) : 0; }

void shim_glBlendFunc(GLenum s, GLenum d) { blendSrc = s; blendDst = d; stateDirty = 1; }
void shim_glDepthMask(GLboolean f) { depthMask = f; stateDirty = 1; }
void shim_glDepthFunc(GLenum f) { depthFunc = f; stateDirty = 1; }
void shim_glCullFace(GLenum m) { cullMode = m; stateDirty = 1; }
void shim_glFrontFace(GLenum m) { frontFace = m; stateDirty = 1; }
void shim_glColorMask(GLboolean r, GLboolean g, GLboolean b, GLboolean a) {
  colorMask = (r ? 1 : 0) | (g ? 2 : 0) | (b ? 4 : 0) | (a ? 8 : 0);
  stateDirty = 1;
}
void shim_glPolygonMode(GLenum face, GLenum mode) { polyFill = (mode == GL_FILL); stateDirty = 1; }
void shim_glViewport(GLint x, GLint y, GLsizei w, GLsizei h) {
  viewport[0] = x; viewport[1] = y; viewport[2] = w; viewport[3] = h;
  stateDirty = 1;
}
void shim_glScissor(GLint x, GLint y, GLsizei w, GLsizei h) {
  scissorRect[0] = x; scissorRect[1] = y; scissorRect[2] = w; scissorRect[3] = h;
}
void shim_glClearColor(GLfloat r, GLfloat g, GLfloat b, GLfloat a) {
  clearColor[0] = r; clearColor[1] = g; clearColor[2] = b; clearColor[3] = a;
}
void shim_glClearDepth(GLdouble d) { clearDepth = (float)d; }
void shim_glClearStencil(GLint s) {}
void shim_glDepthRange(GLdouble n, GLdouble f) { if (n != 0 || f != 1) unsupported_once("glDepthRange"); }
void shim_glClipControl(GLenum origin, GLenum depth) {
  clipControl = (origin == GL_LOWER_LEFT && depth == GL_ZERO_TO_ONE);
}
void shim_glAlphaFunc(GLenum f, GLfloat ref) {}
void shim_glStencilFunc(GLenum f, GLint ref, GLuint mask) {}
void shim_glStencilOp(GLenum a, GLenum b, GLenum c) {}
void shim_glClipPlane(GLenum p, const GLdouble* eq) {}
void shim_glShadeModel(GLenum m) {}
void shim_glLineWidth(GLfloat w) {}
void shim_glHint(GLenum t, GLenum m) {}
void shim_glPolygonOffset(GLfloat f, GLfloat u) {}
void shim_glTexEnvi(GLenum target, GLenum pname, GLint param) {
  if (pname == GL_TEXTURE_ENV_MODE) { texEnvModulate = (param == GL_MODULATE); stateDirty = 1; }
}
void shim_glFogi(GLenum pname, GLint param) {
  if (pname == GL_FOG_MODE && param != GL_LINEAR) unsupported_once("fog mode other than GL_LINEAR");
}
void shim_glFogf(GLenum pname, GLfloat param) {
  if (pname == GL_FOG_START) fogStart = param;
  if (pname == GL_FOG_END) fogEnd = param;
  stateDirty = 1;
}
void shim_glFogfv(GLenum pname, const GLfloat* p) {
  if (pname == GL_FOG_COLOR) { memcpy(fogColor, p, 4 * sizeof(float)); stateDirty = 1; }
}

// colors and materials (GL_FRONT_AND_BACK only: MuJoCo never sets the faces separately)
static int recList;  // display list being recorded (0: none)
static int recHasColor;
void shim_glColor4f(GLfloat r, GLfloat g, GLfloat b, GLfloat a) {
  curColor[0] = r; curColor[1] = g; curColor[2] = b; curColor[3] = a;
  if (recList) recHasColor = 1;  // glColor inside a list: per-vertex colors (MuJoCo's haze cone)
}
void shim_glColor4fv(const GLfloat* v) { shim_glColor4f(v[0], v[1], v[2], v[3]); }
void shim_glColor4d(GLdouble r, GLdouble g, GLdouble b, GLdouble a) {
  shim_glColor4f((float)r, (float)g, (float)b, (float)a);
}
void shim_glColor3f(GLfloat r, GLfloat g, GLfloat b) { shim_glColor4f(r, g, b, 1); }
void shim_glColor3fv(const GLfloat* v) { shim_glColor4f(v[0], v[1], v[2], 1); }
void shim_glColor4ubv(const GLubyte* v) {
  shim_glColor4f(v[0] / 255.0f, v[1] / 255.0f, v[2] / 255.0f, v[3] / 255.0f);
}
void shim_glColorMaterial(GLenum face, GLenum mode) {
  if (mode != GL_AMBIENT_AND_DIFFUSE) unsupported_once("glColorMaterial mode");
}
void shim_glMaterialfv(GLenum face, GLenum pname, const GLfloat* p) {
  if (pname == GL_EMISSION) memcpy(matEmission, p, 4 * sizeof(float));
  else if (pname == GL_SPECULAR) memcpy(matSpecular, p, 4 * sizeof(float));
  else if (pname == GL_SHININESS) matShininess = p[0];
  // GL_AMBIENT / GL_DIFFUSE are tracked from the current color (GL_COLOR_MATERIAL)
}
void shim_glMaterialf(GLenum face, GLenum pname, GLfloat v) { shim_glMaterialfv(face, pname, &v); }

// lights: position and spot direction go to eye space when they are set (GL semantics)
void shim_glLightfv(GLenum id, GLenum pname, const GLfloat* p) {
  if (id < GL_LIGHT0 || id >= GL_LIGHT0 + SHIM_MAXLIGHT) return;
  Light* L = lights + (id - GL_LIGHT0);
  const float* m = mvStack[mvTop].m;
  switch (pname) {
    case GL_AMBIENT: memcpy(L->ambient, p, 4 * sizeof(float)); break;
    case GL_DIFFUSE: memcpy(L->diffuse, p, 4 * sizeof(float)); break;
    case GL_SPECULAR: memcpy(L->specular, p, 4 * sizeof(float)); break;
    case GL_POSITION:
      for (int i = 0; i < 4; i++) L->position[i] = m[i]*p[0] + m[4+i]*p[1] + m[8+i]*p[2] + m[12+i]*p[3];
      break;
    case GL_SPOT_DIRECTION:
      for (int i = 0; i < 3; i++) L->spotdir[i] = m[i]*p[0] + m[4+i]*p[1] + m[8+i]*p[2];
      break;
    case GL_SPOT_EXPONENT: L->exponent = p[0]; break;
    case GL_SPOT_CUTOFF: L->cutoff = p[0]; break;
    case GL_CONSTANT_ATTENUATION: L->att[0] = p[0]; break;
    case GL_LINEAR_ATTENUATION: L->att[1] = p[0]; break;
    case GL_QUADRATIC_ATTENUATION: L->att[2] = p[0]; break;
  }
  stateDirty = 1;
}
void shim_glLightf(GLenum id, GLenum pname, GLfloat v) { shim_glLightfv(id, pname, &v); }
void shim_glLightModelfv(GLenum pname, const GLfloat* p) {
  if (pname == GL_LIGHT_MODEL_AMBIENT) { memcpy(lmAmbient, p, 4 * sizeof(float)); stateDirty = 1; }
}
void shim_glLightModeli(GLenum pname, GLint v) {
  if (pname == GL_LIGHT_MODEL_LOCAL_VIEWER) localViewer = v;
  if (pname == GL_LIGHT_MODEL_TWO_SIDE) twoSide = v;
  stateDirty = 1;
}

// textures
static GLuint nextName = 1;
static void gen_names(GLsizei n, GLuint* ids) { for (int i = 0; i < n; i++) ids[i] = nextName++; }
void shim_glGenTextures(GLsizei n, GLuint* ids) { gen_names(n, ids); }
void shim_glDeleteTextures(GLsizei n, const GLuint* ids) {}
void shim_glActiveTexture(GLenum unit) { activeUnit = (unit == GL_TEXTURE1); stateDirty = 1; }
void shim_glBindTexture(GLenum target, GLuint name) {
  if (target == GL_TEXTURE_2D) tex[activeUnit].bound2D = name;
  else if (target == GL_TEXTURE_CUBE_MAP) tex[activeUnit].boundCube = name;
  stateDirty = 1;
}
static GLuint bound_for(GLenum target) {
  return (target == GL_TEXTURE_2D) ? tex[activeUnit].bound2D : tex[activeUnit].boundCube;
}
void shim_glTexImage2D(GLenum target, GLint level, GLint ifmt, GLsizei w, GLsizei h, GLint border,
                       GLenum fmt, GLenum type, const void* px) {
  GLenum t = (target == GL_TEXTURE_2D) ? GL_TEXTURE_2D : GL_TEXTURE_CUBE_MAP;
  if (px) js_tex_image(bound_for(t), target, level, ifmt, w, h, fmt, type, px);
}
void shim_glTexParameteri(GLenum target, GLenum pname, GLint param) {
  js_tex_param(bound_for(target), target, pname, param);
}
void shim_glGenerateMipmap(GLenum target) { js_gen_mipmap(bound_for(target), target); }
void shim_glPixelStorei(GLenum pname, GLint param) { js_pixel_store(pname, param); }
void shim_glTexGeni(GLenum coord, GLenum pname, GLint param) {
  if (activeUnit == 0 && param != GL_OBJECT_LINEAR) unsupported_once("texgen mode other than OBJECT_LINEAR");
}
void shim_glTexGenfv(GLenum coord, GLenum pname, const GLfloat* p) {
  if (pname == GL_OBJECT_PLANE && coord >= GL_S && coord <= GL_Q) {
    memcpy(tex[activeUnit].objPlane[coord - GL_S], p, 4 * sizeof(float));
  }
}

// framebuffers, buffers and queries: MuJoCo only draws to the window here
void shim_glGenFramebuffers(GLsizei n, GLuint* ids) { gen_names(n, ids); }
void shim_glGenRenderbuffers(GLsizei n, GLuint* ids) { gen_names(n, ids); }
void shim_glGenBuffers(GLsizei n, GLuint* ids) { gen_names(n, ids); }
void shim_glBindFramebuffer(GLenum target, GLuint fb) { boundFBO = fb; }
void shim_glBindRenderbuffer(GLenum target, GLuint rb) {}
void shim_glBindBuffer(GLenum target, GLuint b) {}
void shim_glDeleteFramebuffers(GLsizei n, const GLuint* ids) {}
void shim_glDeleteRenderbuffers(GLsizei n, const GLuint* ids) {}
void shim_glDeleteBuffers(GLsizei n, const GLuint* ids) {}
void shim_glRenderbufferStorage(GLenum t, GLenum f, GLsizei w, GLsizei h) {}
void shim_glRenderbufferStorageMultisample(GLenum t, GLsizei s, GLenum f, GLsizei w, GLsizei h) {}
void shim_glFramebufferRenderbuffer(GLenum t, GLenum a, GLenum rt, GLuint rb) {}
void shim_glFramebufferTexture2D(GLenum t, GLenum a, GLenum tt, GLuint tex, GLint l) {}
GLenum shim_glCheckFramebufferStatus(GLenum target) { return GL_FRAMEBUFFER_COMPLETE; }
void shim_glGetRenderbufferParameteriv(GLenum t, GLenum p, GLint* v) { *v = 0; }
void shim_glDrawBuffer(GLenum b) {}
void shim_glReadBuffer(GLenum b) {}
void shim_glFinish(void) {}
GLenum shim_glGetError(void) { return GL_NO_ERROR; }
void shim_glDebugMessageCallback(GLDEBUGPROC cb, const void* user) {}

void shim_glGetIntegerv(GLenum pname, GLint* v) {
  switch (pname) {
    case GL_CULL_FACE_MODE: *v = cullMode; break;
    case GL_MAX_SAMPLES: *v = 4; break;
    case GL_VIEWPORT: memcpy(v, viewport, 4 * sizeof(int)); break;
    default: *v = 0;  // GL_SAMPLE_BUFFERS, GL_SAMPLES: the window has no multisampling
  }
}
void shim_glGetBooleanv(GLenum pname, GLboolean* v) { *v = (pname == GL_DOUBLEBUFFER); }
// mjr_render reads both matrices right after it loads the camera (setView in render_gl3.c): the
// first read of each in a frame is the camera's view and projection, kept for overlays (b2.js).
static int camSaved;
static float camView[16], camProj[16];
void shim_glGetFloatv(GLenum pname, GLfloat* v) {
  if (pname == GL_PROJECTION_MATRIX) {
    memcpy(v, prStack[prTop].m, 16 * sizeof(float));
    if (!(camSaved & 1)) memcpy(camProj, v, sizeof(camProj));
    camSaved |= 1;
  } else if (pname == GL_MODELVIEW_MATRIX) {
    memcpy(v, mvStack[mvTop].m, 16 * sizeof(float));
    if (!(camSaved & 2)) memcpy(camView, v, sizeof(camView));
    camSaved |= 2;
  } else {
    *v = 0;
  }
}
const GLubyte* shim_glGetString(GLenum name) {
  if (name == GL_VERSION) return (const GLubyte*)"1.5 B2-shim (WebGL2 replay)";
  if (name == GL_EXTENSIONS) {
    return (const GLubyte*)(advertiseClipControl
        ? "GL_ARB_framebuffer_object GL_ARB_vertex_buffer_object GL_ARB_seamless_cube_map GL_ARB_clip_control"
        : "GL_ARB_framebuffer_object GL_ARB_vertex_buffer_object GL_ARB_seamless_cube_map");
  }
  if (name == GL_VENDOR) return (const GLubyte*)"oraculum";
  if (name == GL_RENDERER) return (const GLubyte*)"B2 shim";
  return (const GLubyte*)"";
}

// text, pixels and client arrays: not used by the circus view (labels off, no skins or flexes)
void shim_glRasterPos3f(GLfloat x, GLfloat y, GLfloat z) {}
void shim_glRasterPos2i(GLint x, GLint y) {}
void shim_glWindowPos2i(GLint x, GLint y) {}
void shim_glBitmap(GLsizei w, GLsizei h, GLfloat xo, GLfloat yo, GLfloat xm, GLfloat ym, const GLubyte* b) {}
void shim_glListBase(GLuint base) {}
void shim_glCallLists(GLsizei n, GLenum type, const void* lists) { unsupported_once("text labels"); }
void shim_glReadPixels(GLint x, GLint y, GLsizei w, GLsizei h, GLenum f, GLenum t, void* p) {}

// ------------------------------------------------------------------ display lists

#define VFLOATS 12
static ShimList* listTab;
static int nlistTab, nextList = 1, recFirst, recHasTex;
static float* arena;
static int narena, carena;
static float savedColor[4], savedNormal[3], savedTex[2];
static float primVert[4 * 4096 * VFLOATS];  // vertices of the current glBegin/glEnd block
static int nprim, primMode, primOverflow;
static int immediateUsed;

GLuint shim_glGenLists(GLsizei range) {
  GLuint base = nextList;
  nextList += range;
  if (nextList > nlistTab) {
    int n = nextList + 1024;
    listTab = realloc(listTab, n * sizeof(ShimList));
    memset(listTab + nlistTab, 0, (n - nlistTab) * sizeof(ShimList));
    nlistTab = n;
  }
  return base;
}
void shim_glDeleteLists(GLuint list, GLsizei range) {
  for (GLuint i = list; i < list + range && (int)i < nlistTab; i++) listTab[i].count = 0;
}
void shim_glNewList(GLuint list, GLenum mode) {
  recList = list;
  recFirst = narena;
  recHasTex = recHasColor = 0;
  memcpy(savedColor, curColor, sizeof(curColor));  // GL_COMPILE does not change current state
  memcpy(savedNormal, curNormal, sizeof(curNormal));
  memcpy(savedTex, curTex, sizeof(curTex));
}
// Identical vertices of a list are merged and the list becomes indexed triangles, as Mesa does
// when it compiles a display list (vbo_save_api.c). Same vertices, same triangles, less vertex work.
static unsigned* indices;
static int nindex, cindex;

static unsigned hash_vertex(const float* v) {
  unsigned h = 2166136261u;
  const unsigned char* b = (const unsigned char*)v;
  for (int i = 0; i < VFLOATS * 4; i++) h = (h ^ b[i]) * 16777619u;
  return h;
}

static void index_list(void) {
  int n = narena - recFirst, cap = 1;
  while (cap < 2 * n) cap <<= 1;
  int* table = malloc(cap * sizeof(int));  // slot -> arena vertex index, -1 empty
  memset(table, -1, cap * sizeof(int));
  if (nindex + n > cindex) {
    cindex = 2 * (nindex + n);
    indices = realloc(indices, (size_t)cindex * sizeof(unsigned));
  }
  int nuniq = 0;
  for (int i = 0; i < n; i++) {
    const float* v = arena + (size_t)(recFirst + i) * VFLOATS;
    unsigned slot = hash_vertex(v) & (cap - 1);
    int found = -1;
    while (table[slot] >= 0) {
      if (!memcmp(arena + (size_t)table[slot] * VFLOATS, v, VFLOATS * sizeof(float))) { found = table[slot]; break; }
      slot = (slot + 1) & (cap - 1);
    }
    if (found < 0) {
      found = recFirst + nuniq++;
      if (found != recFirst + i) memcpy(arena + (size_t)found * VFLOATS, v, VFLOATS * sizeof(float));
      table[slot] = found;
    }
    indices[nindex++] = (unsigned)found;
  }
  free(table);
  narena = recFirst + nuniq;
}

void shim_glEndList(void) {
  if (recList > 0 && recList < nlistTab) {
    int first = nindex;
    index_list();
    listTab[recList] = (ShimList){first, nindex - first, recHasTex, recHasColor};
  }
  recList = 0;
  memcpy(curColor, savedColor, sizeof(curColor));
  memcpy(curNormal, savedNormal, sizeof(curNormal));
  memcpy(curTex, savedTex, sizeof(curTex));
}

void shim_glBegin(GLenum mode) { primMode = mode; nprim = 0; }

static void emit(const float* v) {
  if (narena + 1 > carena) {
    carena = carena ? 2 * carena : 1 << 16;
    arena = realloc(arena, (size_t)carena * VFLOATS * sizeof(float));
  }
  memcpy(arena + (size_t)narena * VFLOATS, v, VFLOATS * sizeof(float));
  narena++;
}

void shim_glEnd(void) {
  if (!recList) {  // immediate mode (line geoms, labels): not replayed
    if (!immediateUsed++) unsupported_once("immediate-mode glBegin/glEnd outside display lists");
    return;
  }
  const float* v = primVert;
  switch (primMode) {
    case GL_TRIANGLES:
      for (int i = 0; i + 2 < nprim; i += 3) for (int k = 0; k < 3; k++) emit(v + (i+k)*VFLOATS);
      break;
    case GL_QUADS:  // split as Mesa llvmpipe does with the default provoking vertex: 012, 023
      for (int i = 0; i + 3 < nprim; i += 4) {
        static const int idx[6] = {0, 1, 2, 0, 2, 3};
        for (int k = 0; k < 6; k++) emit(v + (i+idx[k])*VFLOATS);
      }
      break;
    case GL_TRIANGLE_FAN:
    case GL_POLYGON:
      for (int i = 1; i + 1 < nprim; i++) { emit(v); emit(v + i*VFLOATS); emit(v + (i+1)*VFLOATS); }
      break;
    case GL_TRIANGLE_STRIP:
      for (int i = 0; i + 2 < nprim; i++) {
        int a = (i % 2) ? i+1 : i, b = (i % 2) ? i : i+1;
        emit(v + a*VFLOATS); emit(v + b*VFLOATS); emit(v + (i+2)*VFLOATS);
      }
      break;
    default:
      unsupported_once("lines or points inside a display list");
  }
  if (primOverflow) unsupported_once("glBegin block larger than the shim buffer");
  nprim = primOverflow = 0;
}

static void vertex(float x, float y, float z) {
  if (!recList) return;
  if (nprim >= (int)(sizeof(primVert) / sizeof(float) / VFLOATS)) {
    // flush complete primitives so far, keep going with an empty block of the same mode
    int keep = (primMode == GL_QUADS) ? nprim - nprim % 4 : (primMode == GL_TRIANGLES) ? nprim - nprim % 3 : 0;
    if (!keep) { primOverflow = 1; return; }
    int rest = nprim - keep;
    int saved = nprim;
    nprim = keep;
    shim_glEnd();
    memmove(primVert, primVert + keep*VFLOATS, rest * VFLOATS * sizeof(float));
    nprim = saved - keep;
  }
  float* p = primVert + nprim*VFLOATS;
  p[0] = x; p[1] = y; p[2] = z;
  memcpy(p + 3, curNormal, 3 * sizeof(float));
  memcpy(p + 6, curTex, 2 * sizeof(float));
  memcpy(p + 8, curColor, 4 * sizeof(float));
  nprim++;
}
void shim_glVertex3f(GLfloat x, GLfloat y, GLfloat z) { vertex(x, y, z); }
void shim_glVertex3fv(const GLfloat* v) { vertex(v[0], v[1], v[2]); }
void shim_glVertex3d(GLdouble x, GLdouble y, GLdouble z) { vertex((float)x, (float)y, (float)z); }
void shim_glVertex2f(GLfloat x, GLfloat y) { vertex(x, y, 0); }
void shim_glVertex2d(GLdouble x, GLdouble y) { vertex((float)x, (float)y, 0); }
void shim_glVertex2i(GLint x, GLint y) { vertex((float)x, (float)y, 0); }
void shim_glNormal3f(GLfloat x, GLfloat y, GLfloat z) { curNormal[0] = x; curNormal[1] = y; curNormal[2] = z; }
void shim_glNormal3fv(const GLfloat* v) { shim_glNormal3f(v[0], v[1], v[2]); }
void shim_glNormal3d(GLdouble x, GLdouble y, GLdouble z) { shim_glNormal3f((float)x, (float)y, (float)z); }
void shim_glTexCoord2fv(const GLfloat* v) { curTex[0] = v[0]; curTex[1] = v[1]; if (recList) recHasTex = 1; }

// client arrays (flex, skin): not replayed
void shim_glEnableClientState(GLenum a) {}
void shim_glDisableClientState(GLenum a) {}
void shim_glVertexPointer(GLint s, GLenum t, GLsizei st, const void* p) {}
void shim_glNormalPointer(GLenum t, GLsizei st, const void* p) {}
void shim_glTexCoordPointer(GLint s, GLenum t, GLsizei st, const void* p) {}
void shim_glDrawArrays(GLenum m, GLint f, GLsizei c) { unsupported_once("client arrays (flex)"); }
void shim_glDrawElements(GLenum m, GLsizei c, GLenum t, const void* i) { unsupported_once("client arrays (skin)"); }
void shim_glBufferData(GLenum t, GLsizeiptr s, const void* d, GLenum u) {}

// ------------------------------------------------------------------ frame recording

typedef struct { int state, list, inst; } Draw;
static ShimState* states;
static int nstate, cstate, curState = -1;
static ShimInstance* insts;  // ungrouped, in call order
static ShimInstance* grouped;
static int ninst, cinst;
static Draw* draws;
static ShimCmd* cmds;
static int ncmd, ccmd, ndraw, nskipped, cdraw;
static ShimFrame frame;

static void* grow(void* p, int* cap, int need, size_t elem) {
  if (need <= *cap) return p;
  *cap = need * 2 + 64;
  return realloc(p, (size_t)*cap * elem);
}

static int state_unsupported(void) {
  int u = 0;
  if (stencil) { u = 1; unsupported_once("stencil test (reflections)"); }
  if (clip0) { u = 1; unsupported_once("clip plane (reflections)"); }
  if (!polyFill) { u = 1; unsupported_once("wireframe"); }
  if (alphaTest) { u = 1; unsupported_once("alpha test (shadows)"); }
  if (tex[1].en2D) { u = 1; unsupported_once("texture unit 1 (shadows)"); }
  if (lighting && !colorMaterial) { u = 1; unsupported_once("lighting without color material"); }
  if (twoSide) { u = 1; unsupported_once("two-sided lighting"); }
  if (!texEnvModulate) { u = 1; unsupported_once("texture env mode other than MODULATE"); }
  return u;
}

static int snapshot_state(void) {
  ShimState s;
  memset(&s, 0, sizeof(s));
  s.lighting = lighting;
  s.blend = blend;
  s.blendSrc = blend ? blendSrc : 0;
  s.blendDst = blend ? blendDst : 0;
  s.depthTest = depthTest;
  s.depthMask = depthMask;
  s.depthFunc = depthFunc;
  s.cull = cull;
  s.cullMode = cullMode;
  s.frontFace = frontFace;
  s.colorMask = colorMask;
  s.fog = fog;
  const TexUnit* t = tex;
  if (t->enCube && t->boundCube) { s.texMode = 3; s.texName = t->boundCube; }
  else if (t->en2D && t->bound2D) { s.texMode = (t->gen[0] && t->gen[1]) ? 1 : 2; s.texName = t->bound2D; }
  s.unsupported = state_unsupported();
  memcpy(s.viewport, viewport, sizeof(viewport));
  memcpy(s.proj, prStack[prTop].m, sizeof(s.proj));
  memcpy(s.fogColor, fogColor, sizeof(fogColor));
  s.fogStart = fogStart;
  s.fogEnd = fogEnd;
  if (lighting) {
    memcpy(s.lmAmbient, lmAmbient, sizeof(lmAmbient));
    if (!localViewer) unsupported_once("infinite viewer lighting");
    for (int i = 0; i < SHIM_MAXLIGHT; i++) {
      const Light* L = lights + i;
      if (!L->enabled) continue;
      ShimLight* o = s.light + s.nlight++;
      memcpy(o->ambient, L->ambient, 4 * sizeof(float));
      memcpy(o->diffuse, L->diffuse, 4 * sizeof(float));
      memcpy(o->specular, L->specular, 4 * sizeof(float));
      memcpy(o->position, L->position, 4 * sizeof(float));
      if (L->position[3] == 0) {  // directional: normalized direction to the light
        float n = sqrtf(L->position[0]*L->position[0] + L->position[1]*L->position[1] + L->position[2]*L->position[2]);
        if (n > 0) for (int k = 0; k < 3; k++) o->position[k] /= n;
      }
      float n = sqrtf(L->spotdir[0]*L->spotdir[0] + L->spotdir[1]*L->spotdir[1] + L->spotdir[2]*L->spotdir[2]);
      for (int k = 0; k < 3; k++) o->spot[k] = n > 0 ? L->spotdir[k] / n : 0;
      o->spot[3] = (L->cutoff == 180) ? -2.0f : cosf(L->cutoff * (float)M_PI / 180.0f);
      o->att[0] = L->att[0];
      o->att[1] = L->att[1];
      o->att[2] = L->att[2];
      o->att[3] = L->exponent;
    }
  }
  // reuse an identical state (states are few: one per pass and texture)
  if (curState >= 0 && !memcmp(states + curState, &s, sizeof(s))) return curState;
  for (int i = nstate - 1; i >= 0; i--) {
    if (!memcmp(states + i, &s, sizeof(s))) return i;
  }
  states = grow(states, &cstate, nstate + 1, sizeof(ShimState));
  states[nstate] = s;
  return nstate++;
}

static void push_cmd(ShimCmd c) {
  cmds = grow(cmds, &ccmd, ncmd + 1, sizeof(ShimCmd));
  cmds[ncmd++] = c;
}

void shim_glClear(GLbitfield mask) {
  if (boundFBO) return;
  ShimCmd c = {0};
  c.type = SHIM_CMD_CLEAR;
  c.mask = mask;
  c.scissor = scissor;
  memcpy(c.rect, scissorRect, sizeof(c.rect));
  memcpy(c.color, clearColor, sizeof(c.color));
  c.depth = clearDepth;
  push_cmd(c);
}

void shim_glCallList(GLuint list) {
  if (recList) { unsupported_once("nested display lists"); return; }
  if (boundFBO) return;  // shadow-map pass (no light casts shadows in the circus scene)
  if ((int)list >= nlistTab || !listTab[list].count) return;
  // a blended draw with alpha 0 and no depth write leaves the framebuffer unchanged: skip it
  if (blend && blendSrc == GL_SRC_ALPHA && !depthMask && (!lighting || colorMaterial) && curColor[3] == 0 &&
      !listTab[list].hasColor) {
    nskipped++;
    return;
  }
  if (stateDirty || curState < 0) {
    curState = snapshot_state();
    stateDirty = 0;
  }
  insts = grow(insts, &cinst, ninst + 1, sizeof(ShimInstance));
  ShimInstance* in = insts + ninst;
  const float* m = mvStack[mvTop].m;
  for (int r = 0; r < 3; r++) for (int c = 0; c < 4; c++) in->row[r][c] = m[c*4+r];
  memcpy(in->color, curColor, sizeof(curColor));
  memcpy(in->emission, matEmission, sizeof(matEmission));
  memcpy(in->specular, matSpecular, 3 * sizeof(float));
  in->specular[3] = matShininess;
  memcpy(in->gen, tex[0].objPlane, 3 * 4 * sizeof(float));
  draws = grow(draws, &cdraw, ninst + 1, sizeof(Draw));
  draws[ninst] = (Draw){curState, (int)list, ninst};
  ninst++;
  ndraw++;
}

// Draws are order-independent when they neither blend nor skip depth writes: the depth test then
// decides, whatever the order (exact ties between overlapping geoms of equal color aside).
static int order_free(const ShimState* s) {
  return !s->blend && s->depthTest && s->depthMask && s->colorMask == 15 && !s->unsupported;
}

void shim_set_clip_control(int advertise) { advertiseClipControl = advertise; }

void shim_begin_frame(void) {
  ncmd = ninst = nstate = ndraw = nskipped = 0;
  curState = -1;
  stateDirty = 1;
  nunimpl = 0;
  camSaved = 0;
  memset(camView, 0, sizeof(camView));
  memset(camProj, 0, sizeof(camProj));
}

// Turn the recorded draws into instanced draw commands. Commands are emitted while recording
// (clears), so draws are first collected and then merged here, in recording order.
const ShimFrame* shim_end_frame(void) {
  static ShimCmd* out;
  static int cout;
  static int* order;
  static int corder;
  int nout = 0, ng = 0;
  grouped = realloc(grouped, ((ninst + 128) / 128) * 128 * sizeof(ShimInstance));  // whole texture rows
  order = grow(order, &corder, ninst + 1, sizeof(int));
  out = grow(out, &cout, ncmd + ninst + 1, sizeof(ShimCmd));

  // clears come first in mjr_render; keep them first
  for (int i = 0; i < ncmd; i++) out[nout++] = cmds[i];

  int i = 0;
  while (i < ninst) {
    int j = i;
    if (order_free(states + draws[i].state)) {
      while (j < ninst && order_free(states + draws[j].state)) j++;
      // stable bucket sort of [i, j) by (state, list), buckets in order of first appearance
      int n = 0;
      for (int k = i; k < j; k++) order[k] = -1;
      for (int k = i; k < j; k++) {
        if (order[k] != -1) continue;
        for (int q = k; q < j; q++) {
          if (order[q] == -1 && draws[q].state == draws[k].state && draws[q].list == draws[k].list) {
            order[q] = n++;
          }
        }
      }
      // order[k] = position of draw k inside the run
      int start = ng;
      for (int k = i; k < j; k++) grouped[start + order[k]] = insts[draws[k].inst];
      int* inv = malloc((j - i) * sizeof(int));
      for (int k = i; k < j; k++) inv[order[k]] = k;
      for (int p = 0; p < j - i;) {
        int k = inv[p], q = p + 1;
        while (q < j - i && draws[inv[q]].state == draws[k].state && draws[inv[q]].list == draws[k].list) q++;
        out[nout++] = (ShimCmd){SHIM_CMD_DRAW, draws[k].state, draws[k].list, start + p, q - p};
        p = q;
      }
      free(inv);
      ng += j - i;
    } else {
      // blended or depth-mask-off draws: keep the exact order, merge runs of the same list
      while (j < ninst && !order_free(states + draws[j].state) &&
             draws[j].state == draws[i].state && draws[j].list == draws[i].list) j++;
      for (int k = i; k < j; k++) grouped[ng + k - i] = insts[draws[k].inst];
      out[nout++] = (ShimCmd){SHIM_CMD_DRAW, draws[i].state, draws[i].list, ng, j - i};
      ng += j - i;
    }
    i = j;
  }
  frame = (ShimFrame){nout, ng, nstate, clipControl, out, grouped, states, ndraw, nskipped, nunimpl, 0};
  memcpy(frame.view, camView, sizeof(camView));
  memcpy(frame.proj, camProj, sizeof(camProj));
  return &frame;
}

// Vertex cache optimisation of the triangle order inside a list (Forsyth, "Linear-speed vertex
// cache optimisation", 2006). Used for mesh lists only: they are drawn opaque in circus, where
// the triangle order inside one draw does not change the image (depth test), but fewer vertex
// shader runs are needed. ponytail: O(n * cache) scoring, fine for meshes of < 1e5 triangles.
#define FCACHE 32
static float fscore(int cachePos, int active) {
  if (active == 0) return -1.0f;
  float s = 0;
  if (cachePos >= 0) s = cachePos < 3 ? 0.75f : powf(1.0f - (cachePos - 3) / (float)(FCACHE - 3), 1.5f);
  return s + 2.0f * powf((float)active, -0.5f);
}

static void forsyth(unsigned* idx, int ntri, int base, int nvert) {
  int* nact = calloc(nvert, sizeof(int));
  int* start = calloc(nvert + 1, sizeof(int));
  int* adj = malloc(3 * ntri * sizeof(int));
  int* cpos = malloc(nvert * sizeof(int));
  float* vs = malloc(nvert * sizeof(float));
  float* ts = malloc(ntri * sizeof(float));
  char* done = calloc(ntri, 1);
  unsigned* out = malloc(3 * ntri * sizeof(unsigned));
  for (int i = 0; i < 3 * ntri; i++) nact[idx[i] - base]++;
  for (int v = 0; v < nvert; v++) start[v + 1] = start[v] + nact[v];
  int* fill = calloc(nvert, sizeof(int));
  for (int t = 0; t < ntri; t++) for (int k = 0; k < 3; k++) {
    int v = idx[3*t+k] - base;
    adj[start[v] + fill[v]++] = t;
  }
  for (int v = 0; v < nvert; v++) { cpos[v] = -1; vs[v] = fscore(-1, nact[v]); }
  for (int t = 0; t < ntri; t++) ts[t] = vs[idx[3*t]-base] + vs[idx[3*t+1]-base] + vs[idx[3*t+2]-base];
  int cache[FCACHE + 3], ncache = 0, scan = 0;
  for (int n = 0; n < ntri; n++) {
    int best = -1;
    float bestScore = -1e30f;
    for (int c = 0; c < ncache; c++) {  // candidates: triangles of the cached vertices
      int v = cache[c];
      for (int a = start[v]; a < start[v] + fill[v]; a++) {
        int t = adj[a];
        if (!done[t] && ts[t] > bestScore) { bestScore = ts[t]; best = t; }
      }
    }
    if (best < 0) {  // cache exhausted: next unused triangle in order
      while (done[scan]) scan++;
      best = scan;
    }
    done[best] = 1;
    memcpy(out + 3*n, idx + 3*best, 3 * sizeof(unsigned));
    // remove best from its vertices' active lists, push them to the cache front
    int newc[FCACHE + 3], nn = 0;
    for (int k = 0; k < 3; k++) {
      int v = idx[3*best+k] - base;
      for (int a = start[v]; a < start[v] + fill[v]; a++) {
        if (adj[a] == best) { adj[a] = adj[start[v] + fill[v] - 1]; fill[v]--; break; }
      }
      newc[nn++] = v;
    }
    for (int c = 0; c < ncache; c++) {
      int v = cache[c];
      if (v != newc[0] && v != newc[1] && v != newc[2]) newc[nn++] = v;
    }
    for (int c = 0; c < nn; c++) {
      int v = newc[c];
      cpos[v] = c < FCACHE ? c : -1;
      vs[v] = fscore(cpos[v], fill[v]);
    }
    ncache = nn < FCACHE ? nn : FCACHE;
    memcpy(cache, newc, ncache * sizeof(int));
    for (int c = 0; c < nn; c++) {  // rescore triangles touching the changed vertices
      int v = newc[c];
      for (int a = start[v]; a < start[v] + fill[v]; a++) {
        int t = adj[a];
        ts[t] = vs[idx[3*t]-base] + vs[idx[3*t+1]-base] + vs[idx[3*t+2]-base];
      }
    }
  }
  memcpy(idx, out, 3 * ntri * sizeof(unsigned));
  free(nact); free(start); free(adj); free(cpos); free(vs); free(ts); free(done); free(out); free(fill);
}

void shim_optimize_lists(int first, int range) {
  for (int l = first; l < first + range && l < nlistTab; l++) {
    ShimList* L = listTab + l;
    if (L->count < 3) continue;
    unsigned lo = 0xFFFFFFFFu, hi = 0;
    for (int i = L->first; i < L->first + L->count; i++) {
      if (indices[i] < lo) lo = indices[i];
      if (indices[i] > hi) hi = indices[i];
    }
    forsyth(indices + L->first, L->count / 3, (int)lo, (int)(hi - lo + 1));
  }
}

const ShimLists* shim_lists(void) {
  static ShimLists L;
  L = (ShimLists){nlistTab, listTab, arena, narena, indices, nindex};
  return &L;
}

void shim_free_vertices(void) {
  free(arena);
  free(indices);
  arena = NULL;
  indices = NULL;
  carena = cindex = 0;  // narena and nindex stay: lists index the GPU buffers
}

// ------------------------------------------------------------------ loader glue
// MuJoCo's glad loader looks for eglGetProcAddress with dlopen(NULL) + dlsym. WebAssembly has no
// dynamic linker: answer that lookup with the shim table (link-time definitions, as in Spike A).

extern const struct shim_entry { const char* name; void* fn; } shim_table[];

void* shim_getproc(const char* name) {
  static int ready;
  if (!ready) { init_state(); ready = 1; }
  for (int i = 0; shim_table[i].name; i++) {
    if (!strcmp(shim_table[i].name, name)) return shim_table[i].fn;
  }
  return NULL;
}

static int self_handle;
void* dlopen(const char* file, int flags) { return file ? NULL : &self_handle; }
void* dlsym(void* restrict handle, const char* restrict name) {
  if (handle == &self_handle && !strcmp(name, "eglGetProcAddress")) return (void*)shim_getproc;
  return NULL;
}
int dlclose(void* handle) { return 0; }
char* dlerror(void) { return "dynamic loading is not available in this WebAssembly build"; }
int dl_iterate_phdr(int (*cb)(struct dl_phdr_info*, size_t, void*), void* data) { return 0; }
