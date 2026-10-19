// B2 entry point: MuJoCo (engine + classic renderer, unmodified) driving the GL shim.
// The calls are circus's (MujocoContext.cpp, SimulationViewport.cpp): mjv_defaultOption with
// geomgroup[4] = 1, mjv_makeScene(10000), mjr_makeContext(mjFONTSCALE_100), and per frame
// mjr_setBuffer(mjFB_WINDOW) + mjv_updateScene(mjCAT_ALL) + mjr_render.
#include <stdio.h>
#include <stdlib.h>
#include <emscripten.h>
#include <mujoco/mujoco.h>
#include "glshim.h"

// MuJoCo's compiler keeps decoded assets (PNG textures, meshes) in a 500 MB global cache
// (src/user/user_api.h). The browser loads one model: switch the cache off to keep the heap small.
typedef struct mjCache_* mjCache;
void mj_setCacheSize(mjCache cache, size_t size);
mjCache mj_globalCache(void);

static mjModel* m;
static mjData* d;
static mjvOption opt;
static mjvCamera cam;
static mjvScene scn;
static mjrContext con;
static double tUpdate, tRender;
static unsigned char* hiddenBody;  // per body: 1 = its geoms and sites are left out of the scene
static int nhidden;

// Load an MJCF from the virtual file system. clipcontrol: 1 = tell MuJoCo that clip control
// exists (reverse-Z with [0, 1] depth, as on desktop GL), 0 = MuJoCo's fallback projection.
EMSCRIPTEN_KEEPALIVE int b2_load(const char* xml, int clipcontrol) {
  char err[1000] = "";
  double t0 = emscripten_get_now();
  shim_set_clip_control(clipcontrol);
  if (mj_globalCache()) mj_setCacheSize(mj_globalCache(), 0);
  m = mj_loadXML(xml, NULL, err, sizeof(err));
  if (!m) {
    printf("B2_ERROR load %s: %s\n", xml, err);
    return 0;
  }
  double t1 = emscripten_get_now();
  d = mj_makeData(m);
  if (m->nkey > 0) mj_resetDataKeyframe(m, d, 0);
  mj_forward(m, d);
  mjv_defaultOption(&opt);
  opt.geomgroup[4] = 1;
  mjv_defaultCamera(&cam);
  mjv_defaultScene(&scn);
  mjv_makeScene(m, &scn, 10000);
  mjr_defaultContext(&con);
  mjr_makeContext(m, &con, mjFONTSCALE_100);
  hiddenBody = calloc(m->nbody, 1);
  double t2 = emscripten_get_now();
  shim_optimize_lists(con.baseMesh, con.rangeMesh);
  printf("B2 load times: mj_loadXML %.0f ms, mjr_makeContext %.0f ms, mesh index order %.0f ms\n",
         t1 - t0, t2 - t1, emscripten_get_now() - t2);
  printf("B2 loaded %s: nq=%d ngeom=%d nmesh=%d ntex=%d extent=%g znear=%g\n", xml, m->nq, m->ngeom,
         m->nmesh, m->ntex, m->stat.extent, m->vis.map.znear * m->stat.extent);
  return 1;
}

EMSCRIPTEN_KEEPALIVE int b2_nq(void) { return m->nq; }
EMSCRIPTEN_KEEPALIVE double* b2_qpos(void) { return d->qpos; }
EMSCRIPTEN_KEEPALIVE const ShimLists* b2_lists(void) { return shim_lists(); }
EMSCRIPTEN_KEEPALIVE void b2_free_vertices(void) { shim_free_vertices(); }
EMSCRIPTEN_KEEPALIVE double b2_time_update(void) { return tUpdate; }
EMSCRIPTEN_KEEPALIVE double b2_time_render(void) { return tRender; }

// GL texture name of a MuJoCo texture (b2.js uploads big PNG textures itself, see b2.js)
EMSCRIPTEN_KEEPALIVE int b2_texture_name(const char* name) {
  int id = mj_name2id(m, mjOBJ_TEXTURE, name);
  return id < 0 ? 0 : (int)con.texture[id];
}

// Calls of GL functions the shim does not implement, and distinct unsupported GL features, since
// the engine started (mjr_makeContext at load included). Both are 0 for the circus scenes.
EMSCRIPTEN_KEEPALIVE int b2_unimplemented(void) { return shim_unimpl_total(); }
EMSCRIPTEN_KEEPALIVE int b2_unsupported(void) { return shim_unsupported_total(); }

EMSCRIPTEN_KEEPALIVE int b2_name2id(int type, const char* name) { return mj_name2id(m, type, name); }
EMSCRIPTEN_KEEPALIVE float* b2_geom_rgba(void) { return m->geom_rgba; }  // jersey numbers: alpha
// half height of a geom's local bounding box: the ball's radius (its rbound is the box corner)
EMSCRIPTEN_KEEPALIVE double b2_geom_half_z(int id) { return m->geom_aabb[6 * id + 5]; }

// Leave bodies first..last (inclusive) out of the scene: their geoms and sites are removed from
// mjvScene after mjv_updateScene, as if they did not exist. Used for robots that are not playing.
EMSCRIPTEN_KEEPALIVE void b2_hide_bodies(int first, int last, int hide) {
  for (int b = first; b <= last && b < m->nbody; b++) {
    if (b < 0 || hiddenBody[b] == !!hide) continue;
    hiddenBody[b] = !!hide;
    nhidden += hide ? 1 : -1;
  }
}

// Debug only (negative CI test): change one circus view option. circus uses mjv_defaultOption
// with geomgroup[4] = 1; any change makes the view differ from circus.
EMSCRIPTEN_KEEPALIVE void b2_set_flag(int i, int v) { if (i >= 0 && i < mjNVISFLAG) opt.flags[i] = v; }
EMSCRIPTEN_KEEPALIVE void b2_set_geomgroup(int i, int v) { if (i >= 0 && i < mjNGROUP) opt.geomgroup[i] = v; }

// Camera control as circus's viewport (SimulationViewport.cpp): mjv_moveCamera with mjtMouse
// actions. reldx, reldy are fractions of the viewport height (circus passes 0.003 per pixel).
EMSCRIPTEN_KEEPALIVE void b2_move_camera(int action, double reldx, double reldy) {
  mjv_moveCamera(m, action, reldx, reldy, &scn, &cam);
}

EMSCRIPTEN_KEEPALIVE const double* b2_get_camera(void) {
  static double c[6];
  c[0] = cam.lookat[0];
  c[1] = cam.lookat[1];
  c[2] = cam.lookat[2];
  c[3] = cam.distance;
  c[4] = cam.azimuth;
  c[5] = cam.elevation;
  return c;
}

EMSCRIPTEN_KEEPALIVE void b2_camera(double x, double y, double z, double dist, double az, double el) {
  cam.type = mjCAMERA_FREE;
  cam.lookat[0] = x;
  cam.lookat[1] = y;
  cam.lookat[2] = z;
  cam.distance = dist;
  cam.azimuth = az;
  cam.elevation = el;
}

// Update the pose and record one frame. physics: 0 = use the current mjData as is,
// 1 = mj_forward (what circus has after a step), 2 = kinematics only (mj_kinematics,
// mj_comPos, mj_camlight: everything mjv_updateScene reads for the circus view).
EMSCRIPTEN_KEEPALIVE const ShimFrame* b2_frame(int width, int height, int physics) {
  double t0 = emscripten_get_now();
  if (physics == 1) {
    mj_forward(m, d);
  } else if (physics == 2) {
    mj_kinematics(m, d);
    mj_comPos(m, d);
    mj_camlight(m, d);
  }
  mjv_updateScene(m, d, &opt, NULL, &cam, mjCAT_ALL, &scn);
  if (nhidden) {
    int n = 0;
    for (int i = 0; i < scn.ngeom; i++) {
      const mjvGeom* g = scn.geoms + i;
      int b = g->objtype == mjOBJ_GEOM ? m->geom_bodyid[g->objid]
            : g->objtype == mjOBJ_SITE ? m->site_bodyid[g->objid]
            : g->objtype == mjOBJ_BODY ? g->objid : -1;
      if (b >= 0 && b < m->nbody && hiddenBody[b]) continue;
      if (n != i) scn.geoms[n] = *g;
      n++;
    }
    scn.ngeom = n;
  }
  double t1 = emscripten_get_now();
  shim_begin_frame();
  mjr_setBuffer(mjFB_WINDOW, &con);
  mjrRect viewport = {0, 0, width, height};
  mjr_render(viewport, &scn, &con);
  const ShimFrame* f = shim_end_frame();
  tUpdate = t1 - t0;
  tRender = emscripten_get_now() - t1;
  return f;
}
