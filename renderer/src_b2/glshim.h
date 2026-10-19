// B2 GL shim: the OpenGL 1.5 fixed-function subset that MuJoCo's classic renderer (mjr_*) calls,
// recorded into flat arrays that b2.js replays with WebGL2. Layouts here are read by b2.js:
// keep the two in sync (offsets are listed in b2.js).
#ifndef B2_GLSHIM_H
#define B2_GLSHIM_H

#define SHIM_MAXLIGHT 8

// One light as the vertex shader needs it, already in eye space (GL semantics).
typedef struct {
  float ambient[4], diffuse[4], specular[4];
  float position[4];  // eye space; w = 0: directional (xyz normalized)
  float spot[4];      // xyz: normalized eye-space spot direction, w: cos(cutoff), or -2 if cutoff = 180
  float att[4];       // constant, linear, quadratic attenuation, spot exponent
} ShimLight;          // 24 floats

// Render state of one draw call. Draws that share a state share one record.
typedef struct {
  int lighting, blend, blendSrc, blendDst;
  int depthTest, depthMask, depthFunc, cull;
  int cullMode, frontFace, colorMask, fog;
  int texMode, texName, nlight, unsupported;  // texMode: 0 none, 1 2D texgen, 2 2D texcoords, 3 cube texgen
  int viewport[4];
  float proj[16];
  float lmAmbient[4];
  float fogColor[4];
  float fogStart, fogEnd, pad0, pad1;
  ShimLight light[SHIM_MAXLIGHT];
} ShimState;  // 20 ints + 28 floats + 8*24 floats = 240 words

// Per-instance data of one drawn display list (one glCallList).
typedef struct {
  float row[3][4];     // modelview rows 0..2 (eye = row * (x, y, z, 1))
  float color[4];      // current color = material ambient and diffuse (GL_COLOR_MATERIAL)
  float emission[4];
  float specular[4];   // rgb, w = shininess (GL units, 0..128)
  float gen[3][4];     // texgen object planes S, T, R
} ShimInstance;        // 36 floats

enum { SHIM_CMD_CLEAR = 1, SHIM_CMD_DRAW = 2 };

typedef struct {
  int type;
  int state;           // DRAW: state index
  int list;            // DRAW: display list id
  int first, count;    // DRAW: instance range
  int mask;            // CLEAR: GL clear mask
  int scissor;         // CLEAR: scissor test enabled
  int pad;
  int rect[4];         // CLEAR: scissor rectangle
  float color[4];      // CLEAR: clear color
  float depth;         // CLEAR: clear depth
  int pad2[3];
} ShimCmd;  // 20 words

typedef struct {
  int ncmd, ninst, nstate, clipControl;  // clipControl: glClipControl(LOWER_LEFT, ZERO_TO_ONE) is active
  ShimCmd* cmd;
  ShimInstance* inst;
  ShimState* state;
  int ndraw, nskipped, unimplemented, pad;  // ndraw before grouping; nskipped: alpha-0 blended draws
  float view[16], proj[16];  // camera modelview and projection that mjr_render loaded (column-major)
} ShimFrame;

// Display lists: indexed triangles; vertices are 12 floats (position 3, normal 3, texcoord 2,
// color 4), indices are absolute (uint32) into the vertex array.
typedef struct {
  int first, count, hasTex, hasColor;  // first index, index count
} ShimList;

typedef struct {
  int nlist;
  ShimList* list;     // indexed by display-list id
  float* vert;
  int nvert;
  unsigned* index;
  int nindex;
} ShimLists;

void shim_set_clip_control(int advertise);
int shim_unimpl_total(void);       // calls of unimplemented GL functions since start (load + frames)
int shim_unsupported_total(void);  // distinct unsupported GL features seen since start
void shim_begin_frame(void);
const ShimFrame* shim_end_frame(void);
const ShimLists* shim_lists(void);
void shim_free_vertices(void);
void shim_optimize_lists(int first, int range);
void* shim_getproc(const char* name);

#endif
