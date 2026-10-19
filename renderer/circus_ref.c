// circus_ref: native reference of "what circus shows on screen".
//
// Same MuJoCo 3.3.3 calls as circus (MujocoContext.cpp, SimulationViewport.cpp) on a default
// framebuffer with circus's QSurfaceFormat (CircusApplication.cpp): RGB8, depth 24, stencil 8,
// SAMPLES samples, OpenGL compatibility profile.
//
// Two backends:
//   RENDERER_SUBSTR = "glx": a real X11 window on $DISPLAY through GLX, config chosen as Qt's xcb_glx
//     does (first glXChooseFBConfig result); the frame is swapped and read back from the X server with
//     XGetImage, i.e. after the driver's resolve at swap. The GPU is the GLX default (Mesa) or the one
//     set by the PRIME offload variables. Also writes <tag>_readback: glReadPixels before the swap.
//   any other string: an EGL pbuffer on the EGL device whose GL_RENDERER contains it (headless);
//     the resolve is glReadPixels on the multisample default framebuffer.
//
// Usage: circus_ref SCENE.xml POSES.txt OUT_DIR TAG RENDERER_SUBSTR SAMPLES WxH [WxH ...]
//   POSES.txt: one pose per line, "name q0 q1 ... q(nq-1)".
//   Writes OUT_DIR/<pose>_<W>x<H>_<TAG>.ppm and prints GL info as JSON lines.
//   OFFSCREEN_SAMPLES=N (diagnostic): render into MuJoCo's own N-sample FBO instead of the window.
//   RESOLVE_TEST=1 (diagnostic): print the grey levels of an antialiased white triangle and exit.
//
// Build (MuJoCo 3.3.3 pip wheel; EGL/GL/X11 headers: libegl-dev libgl-dev libx11-dev, or -Iinc with the
// headers of the circus pixi env; system glvnd libraries):
//   V=<venv>/lib/python3.12/site-packages/mujoco
//   gcc -O2 -Wall -o circus_ref circus_ref.c -Iinc -I$V/include $V/libmujoco.so.3.3.3 -Wl,-rpath,$V
//     -l:libGL.so.1 -l:libX11.so.6 -l:libEGL.so.1  (same line)
// MuJoCo writes MUJOCO_LOG.TXT (harmless NVIDIA pbuffer warnings) into the current folder.
// renderer/msaa_refs.py runs it for the CI references (refs_msaa/).
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GL/glx.h>
#include <X11/Xlib.h>
#include <X11/Xutil.h>
#include <mujoco/mujoco.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#ifndef GL_SAMPLES
#define GL_SAMPLES 0x80A9
#endif

typedef struct {
  int glx;
  EGLDisplay dpy;
  EGLContext ctx;
  EGLSurface surf;
  Display* x;
  Window win;
  Colormap cmap;
  GLXContext gctx;
  GLXFBConfig fbc;
} Win;

static int cfg_attr(EGLDisplay d, EGLConfig c, EGLint a) {
  EGLint v = -1;
  eglGetConfigAttrib(d, c, a, &v);
  return v;
}

// EGL pbuffer on the device whose GL_RENDERER contains `want`. Configs are tried in eglChooseConfig
// order; the first with exactly RGB8, depth 24, stencil 8 and GL_SAMPLES == samples wins. NVIDIA lists a
// CSAA config (EGL_SAMPLES 4, GL_SAMPLES 16) next to true 4x MSAA; the GL_SAMPLES check skips it.
static int open_egl(const char* want, int samples, int W, int H, Win* w) {
  PFNEGLQUERYDEVICESEXTPROC queryDevices = (PFNEGLQUERYDEVICESEXTPROC)eglGetProcAddress("eglQueryDevicesEXT");
  PFNEGLGETPLATFORMDISPLAYEXTPROC getPlatformDisplay =
      (PFNEGLGETPLATFORMDISPLAYEXTPROC)eglGetProcAddress("eglGetPlatformDisplayEXT");
  EGLDeviceEXT devs[16];
  EGLint ndev = 0;
  queryDevices(16, devs, &ndev);
  EGLint attr[] = {EGL_RED_SIZE, 8, EGL_GREEN_SIZE, 8, EGL_BLUE_SIZE, 8, EGL_DEPTH_SIZE, 24,
                   EGL_STENCIL_SIZE, 8, EGL_SAMPLE_BUFFERS, samples > 0, EGL_SAMPLES, samples,
                   EGL_SURFACE_TYPE, EGL_PBUFFER_BIT, EGL_RENDERABLE_TYPE, EGL_OPENGL_BIT, EGL_NONE};
  EGLint pb[] = {EGL_WIDTH, W, EGL_HEIGHT, H, EGL_NONE};
  for (int i = 0; i < ndev; i++) {
    EGLDisplay d = getPlatformDisplay(EGL_PLATFORM_DEVICE_EXT, devs[i], NULL);
    if (d == EGL_NO_DISPLAY || !eglInitialize(d, NULL, NULL)) continue;
    EGLConfig cfgs[256];
    EGLint n = 0;
    eglChooseConfig(d, attr, cfgs, 256, &n);
    for (int j = 0; j < n; j++) {
      EGLConfig c = cfgs[j];
      if (cfg_attr(d, c, EGL_RED_SIZE) != 8 || cfg_attr(d, c, EGL_GREEN_SIZE) != 8 ||
          cfg_attr(d, c, EGL_BLUE_SIZE) != 8 || cfg_attr(d, c, EGL_DEPTH_SIZE) != 24 ||
          cfg_attr(d, c, EGL_STENCIL_SIZE) != 8 || cfg_attr(d, c, EGL_SAMPLES) != samples)
        continue;
      eglBindAPI(EGL_OPENGL_API);
      EGLContext x = eglCreateContext(d, c, EGL_NO_CONTEXT, NULL);  // no version: highest compatibility profile
      EGLSurface sf = eglCreatePbufferSurface(d, c, pb);
      int gs = -1;
      if (x != EGL_NO_CONTEXT && sf != EGL_NO_SURFACE && eglMakeCurrent(d, sf, sf, x)) {
        glGetIntegerv(GL_SAMPLES, &gs);
        if (strstr((const char*)glGetString(GL_RENDERER), want) && gs == samples) {
          w->dpy = d;
          w->ctx = x;
          w->surf = sf;
          return 1;
        }
      }
      eglMakeCurrent(d, EGL_NO_SURFACE, EGL_NO_SURFACE, EGL_NO_CONTEXT);
      if (sf != EGL_NO_SURFACE) eglDestroySurface(d, sf);
      if (x != EGL_NO_CONTEXT) eglDestroyContext(d, x);
    }
    eglTerminate(d);
  }
  return 0;
}

// X11 window through GLX, as Qt xcb_glx (qglxconvenience.cpp): window + RGBA + double buffer, RGB >= 1 bit,
// depth 24, stencil 8, sample buffers + samples; the first config glXChooseFBConfig returns.
static int open_glx(int samples, int W, int H, Win* w) {
  w->glx = 1;
  w->x = XOpenDisplay(NULL);
  if (!w->x) return 0;
  int spec[] = {GLX_LEVEL, 0, GLX_DRAWABLE_TYPE, GLX_WINDOW_BIT, GLX_RENDER_TYPE, GLX_RGBA_BIT,
                GLX_DOUBLEBUFFER, True, GLX_RED_SIZE, 1, GLX_GREEN_SIZE, 1, GLX_BLUE_SIZE, 1,
                GLX_DEPTH_SIZE, 24, GLX_STENCIL_SIZE, 8, GLX_SAMPLE_BUFFERS, samples > 0, GLX_SAMPLES, samples,
                None};
  int n = 0;
  GLXFBConfig* cfgs = glXChooseFBConfig(w->x, DefaultScreen(w->x), spec, &n);
  if (!cfgs || !n) return 0;
  w->fbc = cfgs[0];
  XFree(cfgs);
  XVisualInfo* vi = glXGetVisualFromFBConfig(w->x, w->fbc);
  if (!vi) return 0;
  Window root = RootWindow(w->x, vi->screen);
  XSetWindowAttributes swa = {0};
  w->cmap = swa.colormap = XCreateColormap(w->x, root, vi->visual, AllocNone);
  swa.event_mask = StructureNotifyMask | ExposureMask;
  w->win = XCreateWindow(w->x, root, 0, 0, W, H, 0, vi->depth, InputOutput, vi->visual,
                         CWColormap | CWEventMask, &swa);
  XSizeHints* hints = XAllocSizeHints();  // fixed size so the window manager keeps W x H
  hints->flags = PMinSize | PMaxSize;
  hints->min_width = hints->max_width = W;
  hints->min_height = hints->max_height = H;
  XSetWMNormalHints(w->x, w->win, hints);
  XFree(hints);
  XStoreName(w->x, w->win, "circus_ref");
  XMapWindow(w->x, w->win);
  XEvent ev;
  do XNextEvent(w->x, &ev);
  while (ev.type != MapNotify);
  XFree(vi);
  w->gctx = glXCreateNewContext(w->x, w->fbc, GLX_RGBA_TYPE, NULL, True);
  if (!w->gctx || !glXMakeCurrent(w->x, w->win, w->gctx)) return 0;
  XWindowAttributes wa;
  XGetWindowAttributes(w->x, w->win, &wa);
  if (wa.width != W || wa.height != H) {
    fprintf(stderr, "window is %dx%d, not %dx%d\n", wa.width, wa.height, W, H);
    return 0;
  }
  return 1;
}

static void close_win(Win* w) {
  if (w->glx) {
    glXMakeCurrent(w->x, None, NULL);
    glXDestroyContext(w->x, w->gctx);
    XDestroyWindow(w->x, w->win);
    XFreeColormap(w->x, w->cmap);
    XCloseDisplay(w->x);
  } else {
    eglMakeCurrent(w->dpy, EGL_NO_SURFACE, EGL_NO_SURFACE, EGL_NO_CONTEXT);
    eglDestroySurface(w->dpy, w->surf);
    eglDestroyContext(w->dpy, w->ctx);
    eglTerminate(w->dpy);
  }
}

// write a PPM; `bottom_up` for GL row order
static void write_ppm(const char* dir, const char* pose, int W, int H, const char* tag, const unsigned char* rgb,
                      int bottom_up) {
  char out[1024];
  snprintf(out, sizeof(out), "%s/%s_%dx%d_%s.ppm", dir, pose, W, H, tag);
  FILE* f = fopen(out, "wb");
  fprintf(f, "P6\n%d %d\n255\n", W, H);
  for (int y = 0; y < H; y++) fwrite(rgb + (size_t)(bottom_up ? H - 1 - y : y) * W * 3, 1, (size_t)W * 3, f);
  fclose(f);
  printf("%s\n", out);
}

static double* read_poses(const char* path, int nq, char names[][64], int* npose) {
  FILE* f = fopen(path, "r");
  if (!f) {
    perror(path);
    exit(1);
  }
  double* q = malloc(sizeof(double) * nq * 64);
  int k = 0;
  while (k < 64 && fscanf(f, "%63s", names[k]) == 1) {
    for (int i = 0; i < nq; i++)
      if (fscanf(f, "%lf", &q[k * nq + i]) != 1) {
        fprintf(stderr, "bad pose %s\n", names[k]);
        exit(1);
      }
    k++;
  }
  fclose(f);
  *npose = k;
  return q;
}

int main(int argc, char** argv) {
  if (argc < 8) {
    fprintf(stderr, "usage: %s SCENE.xml POSES.txt OUT_DIR TAG RENDERER_SUBSTR|glx SAMPLES WxH...\n", argv[0]);
    return 2;
  }
  const char *scene_path = argv[1], *poses_path = argv[2], *out_dir = argv[3], *tag = argv[4];
  const char* want = argv[5];
  int samples = atoi(argv[6]);
  int use_glx = !strcmp(want, "glx");

  char err[1000] = "";
  mjModel* m = mj_loadXML(scene_path, NULL, err, sizeof(err));
  if (!m) {
    fprintf(stderr, "load: %s\n", err);
    return 1;
  }
  mjData* d = mj_makeData(m);
  static char names[64][64];
  int npose = 0;
  double* poses = read_poses(poses_path, m->nq, names, &npose);

  // circus MujocoContext: default option + group 4, default (free) camera, scene with 10000 geoms
  mjvOption opt;
  mjv_defaultOption(&opt);
  opt.geomgroup[4] = 1;
  mjvCamera cam;
  mjv_defaultCamera(&cam);
  mjvScene scn;
  mjv_defaultScene(&scn);
  mjv_makeScene(m, &scn, 10000);
  // circus SimulationViewport constructor
  cam.distance = 15.f;
  cam.azimuth = 90.f;
  cam.elevation = -45.f;
  cam.lookat[0] = 0.f;
  cam.lookat[1] = -1.f;
  cam.lookat[2] = 0.f;

  for (int a = 7; a < argc; a++) {
    int W, H;
    if (sscanf(argv[a], "%dx%d", &W, &H) != 2) {
      fprintf(stderr, "bad size %s\n", argv[a]);
      return 2;
    }
    Win w = {0};
    if (!(use_glx ? open_glx(samples, W, H, &w) : open_egl(want, samples, W, H, &w))) {
      fprintf(stderr, "no %s window with %d samples and RGB8/D24S8\n", want, samples);
      return 1;
    }
    int s = -1, db = -1, sb = -1, enc = -1, rgbbits[3];
    unsigned char dbl = 0;
    glGetIntegerv(GL_SAMPLES, &s);
    glGetIntegerv(GL_DEPTH_BITS, &db);
    glGetIntegerv(GL_STENCIL_BITS, &sb);
    glGetIntegerv(GL_RED_BITS, &rgbbits[0]);
    glGetIntegerv(GL_GREEN_BITS, &rgbbits[1]);
    glGetIntegerv(GL_BLUE_BITS, &rgbbits[2]);
    glGetBooleanv(GL_DOUBLEBUFFER, &dbl);
    // colour encoding of the default framebuffer (GL_SRGB = 0x8c40, GL_LINEAR = 0x2601)
    const char* fn = "glGetFramebufferAttachmentParameteriv";
    void (*getFBAP)(unsigned, unsigned, unsigned, int*) = (void (*)(unsigned, unsigned, unsigned, int*))(
        use_glx ? (void*)glXGetProcAddress((const GLubyte*)fn) : (void*)eglGetProcAddress(fn));
    getFBAP(0x8D40 /* GL_FRAMEBUFFER */, GL_BACK_LEFT, 0x8210 /* COLOR_ENCODING */, &enc);
    glGetError();
    int srgb_capable = -1;
    if (use_glx) glXGetFBConfigAttrib(w.x, w.fbc, 0x20B2 /* GLX_FRAMEBUFFER_SRGB_CAPABLE_ARB */, &srgb_capable);
    printf("{\"backend\":\"%s\",\"size\":\"%dx%d\",\"renderer\":\"%s\",\"version\":\"%s\",\"samples\":%d,"
           "\"rgb_bits\":[%d,%d,%d],\"depth_bits\":%d,\"stencil_bits\":%d,\"doublebuffer\":%d,"
           "\"color_encoding\":\"0x%x\",\"glx_srgb_capable\":%d}\n",
           use_glx ? "glx-window" : "egl-pbuffer", W, H, glGetString(GL_RENDERER), glGetString(GL_VERSION), s,
           rgbbits[0], rgbbits[1], rgbbits[2], db, sb, dbl, enc, srgb_capable);

    // diagnostic only: RESOLVE_TEST=1 draws a white triangle on black and prints the distinct grey levels
    // on its edges. 4x MSAA with a plain average gives 64/128/191; a gamma-correct (sRGB) resolve gives
    // about 137/188/225.
    if (getenv("RESOLVE_TEST")) {
      glViewport(0, 0, W, H);
      glClearColor(0, 0, 0, 1);
      glClear(GL_COLOR_BUFFER_BIT);
      glEnable(GL_MULTISAMPLE);
      glColor3f(1, 1, 1);
      glBegin(GL_TRIANGLES);
      glVertex2f(-0.9f, -0.9f);
      glVertex2f(0.9f, -0.7f);
      glVertex2f(-0.3f, 0.9f);
      glEnd();
      unsigned char* px = malloc((size_t)W * H * 3);
      glReadPixels(0, 0, W, H, GL_RGB, GL_UNSIGNED_BYTE, px);
      int hist[256] = {0};
      for (size_t i = 0; i < (size_t)W * H; i++) hist[px[i * 3]]++;
      printf("resolve levels (value:count, 1..254):");
      for (int v = 1; v < 255; v++)
        if (hist[v] > 20) printf(" %d:%d", v, hist[v]);
      printf("\n");
      free(px);
      return 0;
    }
    // diagnostic only: OFFSCREEN_SAMPLES=N renders into MuJoCo's own N-sample FBO (blit resolve)
    const char* offs = getenv("OFFSCREEN_SAMPLES");
    if (offs) {
      m->vis.quality.offsamples = atoi(offs);
      m->vis.global.offwidth = W;
      m->vis.global.offheight = H;
    }
    int fb = offs ? mjFB_OFFSCREEN : mjFB_WINDOW;

    // circus initializeGL
    mjrContext con;
    mjr_defaultContext(&con);
    mjr_makeContext(m, &con, mjFONTSCALE_100);
    if (!con.windowAvailable || con.windowSamples != samples) {
      fprintf(stderr, "window not as requested: available %d samples %d\n", con.windowAvailable, con.windowSamples);
      return 1;
    }

    unsigned char* rgb = malloc((size_t)W * H * 3);
    for (int p = 0; p < npose; p++) {
      mju_copy(d->qpos, poses + (size_t)p * m->nq, m->nq);
      mj_forward(m, d);
      mjrRect vp = {0, 0, W, H};
      // circus paintGL (main viewport); in the GLX window, three frames so the compositor has the last one
      for (int rep = 0; rep < (use_glx ? 3 : 1); rep++) {
        glViewport(0, 0, W, H);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
        mjr_setBuffer(fb, &con);
        mjv_updateScene(m, d, &opt, NULL, &cam, mjCAT_ALL, &scn);
        mjr_render(vp, &scn, &con);
        unsigned e1 = glGetError();
        if (e1 && rep == 0) {
          // NVIDIA pbuffer: MuJoCo's glDrawBuffer(GL_FRONT) on a single-buffered surface is rejected;
          // drawing stays on GL_BACK, the pbuffer's only colour buffer
          int dbuf = 0;
          glGetIntegerv(GL_DRAW_BUFFER, &dbuf);
          fprintf(stderr, "GL error 0x%x in frame %s; draw buffer 0x%x\n", e1, names[p], dbuf);
        }
        if (use_glx && rep == 2) {
          mjr_readPixels(rgb, NULL, vp, &con);  // before the swap: multisample readback
          char t2[128];
          snprintf(t2, sizeof(t2), "%s_readback", tag);
          write_ppm(out_dir, names[p], W, H, t2, rgb, 1);
        }
        if (use_glx) {
          glXSwapBuffers(w.x, w.win);
          glFinish();
        }
      }
      if (use_glx) {
        XSync(w.x, False);
        usleep(200000);
        XImage* im = XGetImage(w.x, w.win, 0, 0, W, H, AllPlanes, ZPixmap);
        for (int y = 0; y < H; y++)
          for (int x = 0; x < W; x++) {
            unsigned long px = XGetPixel(im, x, y);
            unsigned char* o = rgb + ((size_t)y * W + x) * 3;
            o[0] = (px & im->red_mask) >> __builtin_ctzl(im->red_mask);
            o[1] = (px & im->green_mask) >> __builtin_ctzl(im->green_mask);
            o[2] = (px & im->blue_mask) >> __builtin_ctzl(im->blue_mask);
          }
        XDestroyImage(im);
        write_ppm(out_dir, names[p], W, H, tag, rgb, 0);
      } else {
        mjr_readPixels(rgb, NULL, vp, &con);  // implicit multisample resolve of the default framebuffer
        write_ppm(out_dir, names[p], W, H, tag, rgb, 1);
      }
    }
    free(rgb);
    mjr_freeContext(&con);
    close_win(&w);
  }
  mjv_freeScene(&scn);
  mj_deleteData(d);
  mj_deleteModel(m);
  free(poses);
  return 0;
}
