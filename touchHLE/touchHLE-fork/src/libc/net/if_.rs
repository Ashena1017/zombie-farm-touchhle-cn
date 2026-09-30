/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
//! `net/if.h`

use crate::dyld::FunctionExports;
use crate::export_c_func;
use crate::mem::{ConstPtr, Ptr};
use crate::Environment;

// TODO: struct definition
#[allow(non_camel_case_types)]
struct if_nameindex {}

fn if_nameindex(_env: &mut Environment) -> ConstPtr<if_nameindex> {
    // TODO: implement
    Ptr::null()
}

fn if_nametoindex(env: &mut Environment, ifname: ConstPtr<u8>) -> u32 {
    if ifname.is_null() {
        return 0;
    }

    let name = env.mem.cstr_at_utf8(ifname);
    match name {
        // Common iPhone OS names. The exact index is not important for apps
        // that only use this as a network-reachability probe.
        Ok("lo0") => 1,
        Ok("en0") | Ok("pdp_ip0") => 2,
        _ => {
            log!("TODO: if_nametoindex({name:?})");
            0
        }
    }
}

pub const FUNCTIONS: FunctionExports = &[
    export_c_func!(if_nameindex()),
    export_c_func!(if_nametoindex(_)),
];
