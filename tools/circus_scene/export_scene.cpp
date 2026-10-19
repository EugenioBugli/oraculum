// Prints the MJCF that circus builds for a scene YAML, using circus's own SceneParser.
// It also compiles that XML through circus's MujocoContext (the exact path AppWindow::loadScene
// takes), so a scene that circus cannot load fails here too.
// Built by exporter.cmake inside circus's own CMake project; no circus file is changed.
#include <iostream>

#include "MujocoContext.h"
#include "SceneParser.h"

int main(int argc, char** argv) {
    if (argc != 2) {
        std::cerr << "usage: circus_scene_export <scene.yaml>  (writes the MJCF to stdout)\n";
        return 2;
    }
    const std::string xml = spqr::SceneParser(argv[1]).buildMuJoCoXml();
    spqr::MujocoContext ctx(xml);  // throws if circus could not compile it
    std::cerr << "PROJECT_ROOT=" << PROJECT_ROOT << " nbody=" << ctx.model->nbody << " ngeom=" << ctx.model->ngeom
              << " nq=" << ctx.model->nq << "\n";
    std::cout << xml;
    return 0;
}
