/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
//! `GKLocalPlayer`.

use super::{call_block_one_object, call_block_two_objects, gk_player, BlockLiteral};
use crate::dyld::{ConstantExports, HostConstant};
use crate::frameworks::foundation::{ns_string, ns_url_connection};
use crate::mem::ConstPtr;
use crate::objc::{id, msg, msg_class, nil, objc_classes, release, ClassExports};
use serde::Deserialize;
use sha2::{Digest, Sha256};
use std::time::{SystemTime, UNIX_EPOCH};

const PLAYER_NAME_ENV: &str = "TOUCHHLE_ZOMBIE_FARM_PLAYER_NAME";
const PLAYER_ID_ENV: &str = "TOUCHHLE_ZOMBIE_FARM_PLAYER_ID";
const PLAYER_ID_PATH: &str = "Documents/touchhle_zombie_farm_public_id.txt";

#[derive(Deserialize)]
struct FarmList {
    farms: Vec<FarmIdentity>,
}

#[derive(Deserialize)]
struct FarmIdentity {
    public_id: String,
    username: String,
}

pub const CLASSES: ClassExports = objc_classes! {

(env, this, _cmd);

@implementation GKLocalPlayer: GKPlayer

+ (id)localPlayer {
    get_or_create_local_player(env).unwrap_or(nil)
}

- (bool)isAuthenticated {
    ns_url_connection::zombie_farm_http_base_url(env).is_some()
}

- (bool)isUnderage {
    false
}

- (())authenticateWithCompletionHandler:(ConstPtr<BlockLiteral>)completion_handler {
    call_block_one_object(env, completion_handler, nil);
    post_authentication_notification_once(env, this);
}

- (())loadFriendsWithCompletionHandler:(ConstPtr<BlockLiteral>)completion_handler {
    match load_public_farms(env) {
        Ok((identifiers, players)) => {
            call_block_two_objects(env, completion_handler, identifiers, nil);
            release(env, identifiers);
            release(env, players);
        }
        Err(message) => {
            log!("ZombieFarm public farm list failed: {}", message);
            call_block_two_objects(env, completion_handler, nil, nil);
        }
    }
}

- (())loadFriendPlayersWithCompletionHandler:(ConstPtr<BlockLiteral>)completion_handler {
    match load_public_farms(env) {
        Ok((identifiers, players)) => {
            call_block_two_objects(env, completion_handler, players, nil);
            release(env, identifiers);
            release(env, players);
        }
        Err(message) => {
            log!("ZombieFarm public farm list failed: {}", message);
            call_block_two_objects(env, completion_handler, nil, nil);
        }
    }
}

@end

};

fn get_or_create_local_player(env: &mut crate::Environment) -> Option<id> {
    ns_url_connection::zombie_farm_http_base_url(env)?;
    if let Some(player) = env.framework_state.game_kit.local_player {
        return Some(player);
    }
    let player_id = public_player_id(env)?;
    let alias = std::env::var(PLAYER_NAME_ENV)
        .ok()
        .filter(|name| !name.trim().is_empty())
        .unwrap_or_else(|| "Zombie Farmer".to_string());
    let player: id = msg_class![env; GKLocalPlayer new];
    gk_player::initialize_player(env, player, &player_id, &alias);
    env.framework_state.game_kit.local_player = Some(player);
    log!("ZombieFarm public identity ready: {}", player_id);
    Some(player)
}

fn public_player_id(env: &mut crate::Environment) -> Option<String> {
    if let Ok(value) = std::env::var(PLAYER_ID_ENV) {
        if valid_public_id(value.trim()) {
            return Some(value.trim().to_string());
        }
        log!(
            "ZombieFarm public identity ignored invalid {}; generating a safe public ID instead",
            PLAYER_ID_ENV
        );
    }
    let player_id_path = env.fs.home_directory().join(PLAYER_ID_PATH);
    if let Ok(bytes) = env.fs.read(&player_id_path) {
        if let Ok(value) = String::from_utf8(bytes) {
            let value = value.trim();
            if valid_public_id(value) {
                return Some(value.to_string());
            }
        }
    }

    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .ok()?
        .as_nanos();
    let mut hasher = Sha256::new();
    hasher.update(now.to_le_bytes());
    hasher.update(std::process::id().to_le_bytes());
    hasher.update(env.fs.home_directory().as_str().as_bytes());
    hasher.update(env.bundle.bundle_identifier().as_bytes());
    let digest = hasher.finalize();
    let mut value = String::from("zfr_");
    for byte in &digest[..16] {
        use std::fmt::Write;
        write!(&mut value, "{:02x}", byte).unwrap();
    }
    if env.fs.write(&player_id_path, value.as_bytes()).is_err() {
        log!("ZombieFarm public identity could not be persisted");
        return None;
    }
    Some(value)
}

fn valid_public_id(value: &str) -> bool {
    (1..=80).contains(&value.len())
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_'))
}

fn load_public_farms(env: &mut crate::Environment) -> Result<(id, id), String> {
    let local_player = get_or_create_local_player(env).ok_or("public identity is unavailable")?;
    let local_id: id = msg![env; local_player playerID];
    let local_id = ns_string::to_rust_string(env, local_id).into_owned();
    let base =
        ns_url_connection::zombie_farm_http_base_url(env).ok_or("HTTP base URL is unavailable")?;
    let url = format!("{}/v1/farms?exclude={}&limit=200", base, local_id);
    let response = ns_url_connection::zombie_farm_http_request("GET", &url, &[], Vec::new())?;
    if response.status != 200 {
        return Err(format!("server returned HTTP {}", response.status));
    }
    let list: FarmList = serde_json::from_slice(&response.body)
        .map_err(|error| format!("invalid farm list response: {}", error))?;
    let identifiers: id = msg_class![env; NSMutableArray new];
    let players: id = msg_class![env; NSMutableArray new];
    for farm in list.farms {
        if !valid_public_id(&farm.public_id) || farm.username.trim().is_empty() {
            continue;
        }
        let player = gk_player::player_for_identity(env, &farm.public_id, &farm.username);
        let identifier: id = msg![env; player playerID];
        () = msg![env; identifiers addObject:identifier];
        () = msg![env; players addObject:player];
    }
    let count: u32 = msg![env; players count];
    log!("ZombieFarm public friend list loaded: {} farm(s)", count);
    Ok((identifiers, players))
}

fn post_authentication_notification_once(env: &mut crate::Environment, player: id) {
    if env.framework_state.game_kit.authentication_notified {
        return;
    }
    env.framework_state.game_kit.authentication_notified = true;
    let name = ns_string::get_static_str(env, GKPlayerAuthenticationDidChangeNotificationName);
    let center: id = msg_class![env; NSNotificationCenter defaultCenter];
    () = msg![env; center postNotificationName:name object:player];
}

pub const GKPlayerAuthenticationDidChangeNotificationName: &str =
    "GKPlayerAuthenticationDidChangeNotificationName";

/// `NSNotificationName` values.
pub const CONSTANTS: ConstantExports = &[(
    "_GKPlayerAuthenticationDidChangeNotificationName",
    HostConstant::NSString(GKPlayerAuthenticationDidChangeNotificationName),
)];
