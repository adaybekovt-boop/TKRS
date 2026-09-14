# PhysicsCharacterController (reference only)

Inert plain-text Roblox Luau/Lua reference for a constraint-based character
controller with Running, Jump, FreeFall, HipHeight, AutoRotate, and Slide
components plus an FSM (Standing/Running/Jumping/FreeFalling/Landed).

Source: https://github.com/datlass/PhysicsCharacterController
Author: dthecoolest (datlass)
License: MIT

DO NOT EXECUTE. Reference for Roblox Studio agents implementing sprint/slide
state machines, acceleration via VectorForce drag, and jump impulses.

Included excerpts (copied as .lua.txt so they stay inert):
- init.lua.txt — controller class, state machine wiring, input
- Running.lua.txt — walk/run VectorForce + quadratic drag
- Jump.lua.txt — jump impulse + debounce
- Slide.lua.txt — slide impulse addon
- fsm.lua.txt — generic FSM used by the controller
