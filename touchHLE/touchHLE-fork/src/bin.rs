/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
// Allow the crate to have a non-snake-case name (touchHLE).
// This also allows items in the crate to have non-snake-case names.
#![allow(non_snake_case)]

// Ask hybrid-GPU Windows drivers to prefer the high-performance GPU for
// touchHLE's OpenGL contexts when the executable is launched.
#[cfg(windows)]
#[allow(non_upper_case_globals)]
#[no_mangle]
#[used]
pub static NvOptimusEnablement: u32 = 0x00000001;

#[cfg(windows)]
#[allow(non_upper_case_globals)]
#[no_mangle]
#[used]
pub static AmdPowerXpressRequestHighPerformance: u32 = 0x00000001;

fn main() -> Result<(), String> {
    touchHLE::main(std::env::args())
}
