/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
//! Minimal `GKPlayer` support used by Zombie Farm 1.0's experimental public farms.

use super::{call_block_two_objects, BlockLiteral};
use crate::frameworks::foundation::{ns_string, NSUInteger};
use crate::mem::ConstPtr;
use crate::objc::{
    id, msg, msg_class, nil, objc_classes, release, retain, ClassExports, HostObject, NSZonePtr,
};

struct GKPlayerHostObject {
    player_id: id,
    alias: id,
}
impl HostObject for GKPlayerHostObject {}

pub const CLASSES: ClassExports = objc_classes! {

(env, this, _cmd);

@implementation GKPlayer: NSObject

+ (id)allocWithZone:(NSZonePtr)_zone {
    env.objc.alloc_object(this, Box::new(GKPlayerHostObject {
        player_id: nil,
        alias: nil,
    }), &mut env.mem)
}

+ (())loadPlayersForIdentifiers:(id)identifiers
           withCompletionHandler:(ConstPtr<BlockLiteral>)completion_handler {
    let players: id = msg_class![env; NSMutableArray new];
    if identifiers != nil {
        let count: NSUInteger = msg![env; identifiers count];
        for index in 0..count {
            let identifier: id = msg![env; identifiers objectAtIndex:index];
            if identifier == nil {
                continue;
            }
            let identifier = ns_string::to_rust_string(env, identifier).into_owned();
            if let Some(player) = env.framework_state.game_kit.remote_players.get(&identifier).copied() {
                () = msg![env; players addObject:player];
            }
        }
    }
    call_block_two_objects(env, completion_handler, players, nil);
    release(env, players);
}

- (id)initWithPlayerID:(id)player_id alias:(id)alias {
    let player_id = retain(env, player_id);
    let alias = retain(env, alias);
    let host = env.objc.borrow_mut::<GKPlayerHostObject>(this);
    host.player_id = player_id;
    host.alias = alias;
    this
}

- (id)playerID {
    env.objc.borrow::<GKPlayerHostObject>(this).player_id
}

- (id)alias {
    env.objc.borrow::<GKPlayerHostObject>(this).alias
}

- (id)displayName {
    env.objc.borrow::<GKPlayerHostObject>(this).alias
}

- (())dealloc {
    let host = env.objc.borrow::<GKPlayerHostObject>(this);
    let player_id = host.player_id;
    let alias = host.alias;
    release(env, player_id);
    release(env, alias);
    env.objc.dealloc_object(this, &mut env.mem);
}

@end

};

pub(super) fn player_for_identity(
    env: &mut crate::Environment,
    player_id: &str,
    alias: &str,
) -> id {
    if let Some(player) = env
        .framework_state
        .game_kit
        .remote_players
        .get(player_id)
        .copied()
    {
        return player;
    }
    let player_id_object = ns_string::from_rust_string(env, player_id.to_string());
    let alias_object = ns_string::from_rust_string(env, alias.to_string());
    let player: id = msg_class![env; GKPlayer new];
    let player: id = msg![env; player initWithPlayerID:player_id_object alias:alias_object];
    env.framework_state
        .game_kit
        .remote_players
        .insert(player_id.to_string(), player);
    player
}

pub(super) fn initialize_player(
    env: &mut crate::Environment,
    player: id,
    player_id: &str,
    alias: &str,
) {
    let player_id_object = ns_string::from_rust_string(env, player_id.to_string());
    let alias_object = ns_string::from_rust_string(env, alias.to_string());
    let _: id = msg![env; player initWithPlayerID:player_id_object alias:alias_object];
}
