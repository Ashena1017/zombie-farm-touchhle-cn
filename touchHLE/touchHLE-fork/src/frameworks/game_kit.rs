/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
//! GameKit framework.
//!
//! Some features of this framework are only in iOS 4.1+, but some games (like
//! "Cut the Rope") may use it to check for game center availability with
//! a `respondsToSelector:` call to some objects of this framework.
//! Thus, we need to provide some stubs in order to not crash on that call.

mod gk_leaderboard;
mod gk_local_player;
mod gk_player;
mod gk_score;

use crate::abi::{CallFromHost, GuestFunction};
use crate::mem::{ConstPtr, ConstVoidPtr, SafeRead};
use crate::objc::id;
use crate::Environment;
use sha2::{Digest, Sha256};
use std::collections::HashMap;

#[derive(Default)]
pub struct State {
    local_player: Option<id>,
    remote_players: HashMap<String, id>,
    authentication_notified: bool,
}

#[repr(C, packed)]
pub(super) struct BlockLiteral {
    _isa: u32,
    _flags: i32,
    _reserved: i32,
    invoke: GuestFunction,
}
unsafe impl SafeRead for BlockLiteral {}

pub(super) fn call_block_one_object(
    env: &mut Environment,
    block: ConstPtr<BlockLiteral>,
    object: id,
) {
    if block.is_null() {
        return;
    }
    let literal: BlockLiteral = env.mem.read(block);
    let invoke = literal.invoke;
    if invoke.addr_with_thumb_bit() != 0 {
        let block_ptr: ConstVoidPtr = block.cast();
        let _: () = invoke.call_from_host(env, (block_ptr, object));
    }
}

pub(super) fn call_block_two_objects(
    env: &mut Environment,
    block: ConstPtr<BlockLiteral>,
    first: id,
    second: id,
) {
    if block.is_null() {
        return;
    }
    let literal: BlockLiteral = env.mem.read(block);
    let invoke = literal.invoke;
    if invoke.addr_with_thumb_bit() != 0 {
        let block_ptr: ConstVoidPtr = block.cast();
        let _: () = invoke.call_from_host(env, (block_ptr, first, second));
    }
}

/// Download a public farm into the exact neighbor-save path requested by ZFR.
/// Existing files are never replaced; the Foundation caller invokes this only
/// after its first local read reports that the file is absent.
pub(crate) fn materialize_zombie_farm_neighbor_save(
    env: &mut Environment,
    guest_path: &str,
) -> bool {
    if !(guest_path.ends_with(".friend") || guest_path.ends_with(".friend2")) {
        return false;
    }
    let player_id = env
        .framework_state
        .game_kit
        .remote_players
        .keys()
        .filter(|player_id| guest_path.contains(player_id.as_str()))
        .max_by_key(|player_id| player_id.len())
        .cloned();
    let Some(player_id) = player_id else {
        return false;
    };
    let Some(base_url) =
        crate::frameworks::foundation::ns_url_connection::zombie_farm_http_base_url(env)
    else {
        return false;
    };
    let url = format!("{}/v1/farms/{}/save", base_url, player_id);
    let Ok(response) = crate::frameworks::foundation::ns_url_connection::zombie_farm_http_request(
        "GET",
        &url,
        &[],
        Vec::new(),
    ) else {
        log!(
            "ZombieFarm public neighbor download failed for {}",
            player_id
        );
        return false;
    };
    if response.status != 200 || response.body.is_empty() || response.body.len() > 4 << 20 {
        log!(
            "ZombieFarm public neighbor download rejected for {}: HTTP {}, {} bytes",
            player_id,
            response.status,
            response.body.len()
        );
        return false;
    }
    if let Some(expected) = response.headers.iter().find_map(|(name, value)| {
        name.eq_ignore_ascii_case("etag").then(|| {
            value
                .trim_matches('"')
                .strip_prefix("sha256:")
                .unwrap_or("")
                .to_ascii_lowercase()
        })
    }) {
        let actual = Sha256::digest(&response.body);
        let actual = actual
            .iter()
            .map(|byte| format!("{:02x}", byte))
            .collect::<String>();
        if expected.len() != 64 || expected != actual {
            log!(
                "ZombieFarm public neighbor checksum mismatch for {}",
                player_id
            );
            return false;
        }
    }
    if env
        .fs
        .write(crate::fs::GuestPath::new(guest_path), &response.body)
        .is_err()
    {
        log!("ZombieFarm public neighbor write failed for {}", player_id);
        return false;
    }
    log!(
        "ZombieFarm public neighbor save downloaded for {} ({} bytes)",
        player_id,
        response.body.len()
    );
    true
}

pub const DYLIB: crate::dyld::HostDylib = crate::dyld::HostDylib {
    path: "/System/Library/Frameworks/GameKit.framework/GameKit",
    aliases: &[],
    class_exports: &[
        gk_player::CLASSES,
        gk_leaderboard::CLASSES,
        gk_local_player::CLASSES,
        gk_score::CLASSES,
    ],
    constant_exports: &[gk_local_player::CONSTANTS],
    function_exports: &[],
};
