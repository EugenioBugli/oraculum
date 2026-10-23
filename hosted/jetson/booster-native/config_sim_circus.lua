-- booster-motion 1.8.0.9 (native aarch64) with circus + simbridge.  Private SPQR interop config, not Booster's.
-- Base: the firmware's own T1 config.lua (real-robot graph: rs_sdk_interface + -mode sim => SimTransportRos).
-- Fix A (always): simbridge applies only JointState.effort as torque, and SimTransportRos::SendData drops kp/kd,
--   so the PD loop runs here (pid::MITGroupController, as in Booster's own mujoco branch) and simulator_in sends
--   pure torque (use_pvt_ = false). RsSdkOutput reads the key "is_real_bot" (no underscore; default true = flips
--   IMU pitch and yaw for the real IMU mounting); circus's IMU needs false, as in the 0.0.11 isaac config.
-- Fix B (SIM_ANKLE_BYPASS = true): circus's T1 has serial ankles (pitch, roll), the firmware graph expects the
--   parallel-ankle motor angles (drive a, b). Feed the serial consumers straight from simulator_out and send the
--   serial planner switch to the motor-command interceptor, skipping parallel_mech_input / _output.
package.path = package.path .. ";../../booster_config/robot_config/utils/?.lua"
require('config_utils')

SIM_ANKLE_BYPASS = (os.getenv("SIM_ANKLE_BYPASS") or "1") == "1"

is_real_bot = true          -- keeps the rs_sdk_interface graph and the /opt/booster/Gait/configs paths
simulator = "mujoco"
num_push_up = 3
push_up_time_scale = 0.8

local graph = require('common_graph_define')
graph.init(is_real_bot, simulator)
local options = require('common_module_options')
options.init(is_real_bot, simulator)
options.resetPushUp(num_push_up, push_up_time_scale)

local function con(om, on, im, inn)
    return { output_module = om, output_message_name = on, input_module = im, input_message_name = inn }
end

-- Fix A: PD torques in booster-motion
graph.import.pid = "lib/libmodule_pid.so"
graph.modules.pid = "pid::MITGroupController"
graph.connections.con_jmi_1 = nil                                   -- joint_map_input -> simulator_in (PVT)
graph.connections.sim_jmi_pid = con("joint_map_input", "motor_pvt_commands_mapped", "pid", "motor_commands")
graph.connections.sim_out_pid_1 = con("simulator_out", "joint_states", "pid", "motor_states")
graph.connections.pid_sim_in_1 = con("pid", "force_commands", "simulator_in", "motor_force_commands")
options.simulator_in.use_pvt_ = false
options.simulator_out.is_real_bot = false

-- Fix B: serial ankles
if SIM_ANKLE_BYPASS then
    for name, c in pairs(graph.connections) do
        if c.output_module == "parallel_mech_output" and c.output_message_name == "joint_states_serial"
            and c.input_module ~= "parallel_mech_input" then
            c.output_module, c.output_message_name = "simulator_out", "joint_states"
        elseif c.output_module == "parallel_mech_output" and c.output_message_name == "joint_forces_serial" then
            c.output_module, c.output_message_name = "simulator_out", "joint_forces"
        end
    end
    graph.connections.con7 = con("planner_pvt_switch", "out", "intercept_motor_cmd", "motor_pvt_")
end

values = { options = options, graph = graph }
return values
