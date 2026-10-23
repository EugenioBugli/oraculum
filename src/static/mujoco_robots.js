// WASM 3D engine: MuJoCo (official WebAssembly build, src/static/mujoco/) loads the
// Booster T2, T1 and K1 models that circus simulates and computes the pose of every part from the
// joint angles; Three.js draws it in the page scene. Assets: tools/fetch_web_assets.sh.
// An agent with robot "t1" or "k1" gets that model, any other (or none) the T2 (the default); a model whose
// files do not load is drawn as the T2 (or, without T2 files, the T1).
import * as THREE from "three";
import loadMujoco from "./mujoco/mujoco.js";

const GEOM_MESH = 7;     // mjGEOM_MESH
// Per model: folder, visual geom group (T1 class "visual" and T2 "Booster-T2_visual" are group 2; circus's K1 has
// class-less group 1 meshes, group 0 = collision), the parts tinted with the team colour (material "metal" = T1/K1
// trunk + waist; the T2 has one light material everywhere, so its Trunk body), and the arms-down rest pose
// (joints an agent does not send keep these values).
const MODELS = {
    t2: { dir: "booster_t2", group: 2, teamBody: "Trunk", rest: { left_shoulder_roll_joint: -1.3, right_shoulder_roll_joint: 1.3 } },
    t1: { dir: "booster_t1", group: 2, teamMat: "metal", rest: { Left_Shoulder_Roll: -1.3, Right_Shoulder_Roll: 1.3 } },
    k1: { dir: "booster_k1", group: 1, teamMat: "metal", rest: { Left_Shoulder_Roll: -1.3, Right_Shoulder_Roll: 1.3 } },
};

// MuJoCo is z-up with x forward. Robot groups in the page are y-up and face local -z
// (the page sets their position and heading): mj x -> -z, mj y -> -x, mj z -> y.
const MJ_TO_SCENE = new THREE.Matrix4().set(0, -1, 0, 0, 0, 0, 1, 0, -1, 0, 0, 0, 0, 0, 0, 1);

// {makeRobot(agent), pose(robot, joints)} for every model whose files load; rejects when none loads.
export async function loadRobots() {
    const mujoco = await loadMujoco();
    const keys = Object.keys(MODELS);
    const loaded = await Promise.all(keys.map(k => loadModel(mujoco, k).catch(e => {
        console.warn(`[WASM] no ${k.toUpperCase()} model:`, e.message);
        return null;
    })));
    const models = Object.fromEntries(keys.map((k, i) => [k, loaded[i]]).filter(([, m]) => m));
    const fallback = models.t2 || models.t1 || models.k1;
    if (!fallback) throw new Error("no robot model loaded (run tools/fetch_web_assets.sh)");
    const modelOf = (agent) => models[String(agent?.robot || "").toLowerCase()] || fallback;
    return {
        makeRobot: (agent) => { const m = modelOf(agent), r = m.makeRobot(agent); r.userData.model = m; return r; },
        pose: (robot, joints) => (robot.userData.model || fallback).pose(robot, joints),
    };
}

async function loadModel(mujoco, key) {
    const { dir, group, teamMat, teamBody, rest } = MODELS[key];
    const url = `/static/models/${dir}/`;
    const fetchOk = async (path) => {
        const r = await fetch(url + path);
        if (!r.ok) throw new Error(`${url}${path}: HTTP ${r.status} (run tools/fetch_web_assets.sh)`);
        return r;
    };
    const files = (await (await fetchOk("files.txt")).text()).trim().split("\n");
    const blobs = await Promise.all(
        ["common.xml", "instance.xml", ...files].map(async f => [f, new Uint8Array(await (await fetchOk(f)).arrayBuffer())]));
    for (const [f, bytes] of blobs) {
        mujoco.FS.mkdirTree(`/${key}/` + f.split("/").slice(0, -1).join("/"));
        mujoco.FS.writeFile(`/${key}/` + f, bytes);
    }
    mujoco.FS.writeFile(`/${key}/scene.xml`,
        `<mujoco model="${key}"><compiler meshdir="meshes"/><include file="common.xml"/><include file="instance.xml"/></mujoco>`);
    const model = mujoco.MjModel.from_xml_path(`/${key}/scene.xml`);
    const data = new mujoco.MjData(model);
    const name = (type, id) => mujoco.mj_id2name(model, type, id);
    const OBJ = { JOINT: mujoco.mjtObj.mjOBJ_JOINT.value, GEOM: mujoco.mjtObj.mjOBJ_GEOM.value,
                  MATERIAL: mujoco.mjtObj.mjOBJ_MATERIAL.value, BODY: mujoco.mjtObj.mjOBJ_BODY.value };

    // One shared BufferGeometry per visual mesh geom; vertices are in the geom frame.
    // ponytail: full circus meshes, about 170k triangles per robot (1.7M for 10 robots).
    // If old phones are slow, simplify the STL files in tools/fetch_web_assets.sh.
    const parts = [];
    const vert = model.mesh_vert, face = model.mesh_face;
    for (let g = 0; g < model.ngeom; g++) {
        if (model.geom_group[g] !== group || model.geom_type[g] !== GEOM_MESH) continue;
        // circus floats the jersey digit 0.3 m above the head; the page's R<id> label shows the number instead.
        if ((name(OBJ.GEOM, g) || "").startsWith("num_")) continue;
        const m = model.geom_dataid[g];
        const va = model.mesh_vertadr[m], vn = model.mesh_vertnum[m];
        const fa = model.mesh_faceadr[m], fn = model.mesh_facenum[m];
        const geo = new THREE.BufferGeometry();
        geo.setAttribute("position", new THREE.BufferAttribute(vert.slice(3 * va, 3 * (va + vn)), 3));
        geo.setIndex(new THREE.BufferAttribute(new Uint32Array(face.slice(3 * fa, 3 * (fa + fn))), 1));
        geo.computeVertexNormals();
        const mat = model.geom_matid[g];
        const rgba = mat >= 0 ? model.mat_rgba.slice(4 * mat, 4 * mat + 4) : model.geom_rgba.slice(4 * g, 4 * g + 4);
        parts.push({
            g, geo,
            team: teamMat ? mat >= 0 && name(OBJ.MATERIAL, mat) === teamMat : name(OBJ.BODY, model.geom_bodyid[g]) === teamBody,
            // circus' "black" parts (0.08) read as flat silhouettes in a browser: lift them to grey,
            // light enough that a black-team trunk still stands out from the limbs.
            material: new THREE.MeshStandardMaterial({
                color: new THREE.Color(Math.max(rgba[0], 0.35), Math.max(rgba[1], 0.35), Math.max(rgba[2], 0.35)),
                roughness: 0.6, metalness: 0.2 }),
        });
    }
    const qpos0 = model.qpos0.slice();
    const jointAdr = {};
    for (let j = 0; j < model.njnt; j++) jointAdr[name(OBJ.JOINT, j)] = model.jnt_qposadr[j];

    // Free joint at the origin; mj_kinematics fills geom_xpos / geom_xmat for these joints.
    function solve(joints) {
        const q = data.qpos;
        q.set(qpos0);
        q[0] = q[1] = q[2] = 0;
        const angles = { ...rest, ...(joints || {}) };  // a partial joint set keeps the arms down
        for (const [jn, v] of Object.entries(angles)) {
            if (jn in jointAdr && Number.isFinite(v)) q[jointAdr[jn]] = v;
        }
        mujoco.mj_kinematics(model, data);
        return [data.geom_xpos, data.geom_xmat];
    }

    // Lowest visual part (mj z) in the rest pose. Bent knees lift the feet towards the trunk;
    // pose() lowers the body by that rise, so the lowest part stays on the floor.
    const xpos0 = solve(null)[0];
    const restMinZ = Math.min(...parts.map(part => xpos0[3 * part.g + 2]));
    // Height of the trunk above the floor in the rest pose (feet on the ground).
    let floorOffset = null;
    const lift = new THREE.Matrix4();

    function pose(robot, joints) {
        const [xpos, xmat] = solve(joints);
        let minZ = Infinity;
        for (const mesh of robot.userData.mjMeshes) {
            const g = mesh.userData.g, p = 3 * g, r = 9 * g;
            mesh.matrix.set(xmat[r], xmat[r + 1], xmat[r + 2], xpos[p],
                            xmat[r + 3], xmat[r + 4], xmat[r + 5], xpos[p + 1],
                            xmat[r + 6], xmat[r + 7], xmat[r + 8], xpos[p + 2], 0, 0, 0, 1);
            minZ = Math.min(minZ, xpos[p + 2]);
        }
        robot.userData.frame.matrix.copy(MJ_TO_SCENE)
            .premultiply(lift.makeTranslation(0, (floorOffset ?? 0) + restMinZ - minZ, 0));
    }

    function makeRobot(agent) {
        const robot = new THREE.Group();
        const frame = new THREE.Group();
        frame.matrixAutoUpdate = false;
        robot.add(frame);
        // Small emissive part: a black-team trunk still shows its shape.
        const teamMat = new THREE.MeshStandardMaterial({ color: agent.color || "#822433", emissive: 0x222222, roughness: 0.5, metalness: 0.2 });
        robot.userData.frame = frame;
        robot.userData.mjMeshes = [];
        for (const part of parts) {
            const mesh = new THREE.Mesh(part.geo, part.team ? teamMat : part.material);
            mesh.matrixAutoUpdate = false;
            mesh.userData.g = part.g;
            frame.add(mesh);
            robot.userData.mjMeshes.push(mesh);
        }
        pose(robot, null);
        if (floorOffset === null) {
            robot.updateMatrixWorld(true);
            floorOffset = -new THREE.Box3().setFromObject(frame).min.y;
            pose(robot, null);
        }
        robot.userData.mj = true;
        robot.userData.height = new THREE.Box3().setFromObject(robot).max.y;
        return robot;
    }

    const tris = parts.reduce((t, part) => t + part.geo.index.count / 3, 0);
    console.log(`[WASM] MuJoCo ${key.toUpperCase()} model ready: ${parts.length} visual meshes, ${tris} triangles, ${model.njnt} joints`);
    return { makeRobot, pose };
}
