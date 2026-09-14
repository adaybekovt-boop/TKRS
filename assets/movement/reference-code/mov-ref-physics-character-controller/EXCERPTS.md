# Inert excerpts — PhysicsCharacterController (MIT, dthecoolest 2022)
# Full sources: https://github.com/datlass/PhysicsCharacterController
# DO NOT EXECUTE.

## Running.lua — VectorForce walk/run + quadratic drag
WalkSpeed default 16. Movement force counters drag+friction so top speed ~= WalkSpeed.
Drag force on XZ = -unitXZ * (xzSpeed^2) * XZDragFactorVSquared
Ground friction tapers at low speed: FlatFriction * (1 - exp(-2*xzSpeed))
State: Standing --run--> Running when xzSpeed >= 0.1; reverse with stand().

## Jump.lua — impulse jump
JumpPower default 1000 (impulse on AssemblyMass). Debounce JumpDebounceTime 0.2s.
Requires HipHeight.OnGround. Standing -> jump() / Running -> leap().

## Slide.lua — F-key slide addon
Requires HipHeight + AutoRotate.
On start: zero WalkSpeed and XZDrag, raise FlatFriction to 2500, disable AutoRotate,
apply LookVector * SlidePower (default 3000) impulse, 0.2s debounce.
On end: restore WalkSpeed, drag, friction 500, re-enable AutoRotate.

## FSM events (init.lua)
run:  Standing -> Running
jump: Standing -> Jumping
leap: Running -> Jumping
fall: Jumping -> FreeFalling
land: FreeFalling -> Landed
recover: Landed -> Standing
stand: Running -> Standing

HipHeight, FreeFall, AutoRotate, HumanoidOnSeat are additional core components.
