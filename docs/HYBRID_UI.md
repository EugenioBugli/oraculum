# Hybrid display UI

The **Session menu** on Field and Dashboard offers Real session, Simulated session, Real + ghosts, and Settings. Simulated session opens the scenario wizard. Settings reopens it to edit the saved scenario. There is no separate Simulation navigation tab.

The wizard configures field dimensions, ball position, two teams, player numbers, T1/T2/K1 models, roles, positions, and real/ghost slots. It saves the scenario in this browser and can export JSON, a ghost-only Circus scene, field YAML, and the matching simulation config YAML. Install both YAML resources in an isolated Circus instance before running the scene; exports do not start Circus. Circus currently starts the physical simulation ball at field centre, so the wizard's chosen ball position affects the UI preview only.

**Real + ghosts** draws the saved ghost lineup and cyan simulated ball over live telemetry. Real robots and the real ball remain distinguishable. A different scenario field size is scaled to the live field and marked `SCALED PREVIEW`. Ghosts are read-only and do not count as live links. Commands and lock state continue to use live gateway data. The robot never receives simulated ball or ghost data in this version.
