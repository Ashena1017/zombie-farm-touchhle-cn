/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at https://mozilla.org/MPL/2.0/.
 */
//! `NSPredicate`.

use super::{ns_string, NSUInteger};
use crate::abi::VaList;
use crate::objc::{
    autorelease, id, msg, msg_class, nil, objc_classes, release, retain, ClassExports, HostObject,
    NSZonePtr,
};

#[derive(Clone, Debug)]
enum PredicateKind {
    /// Fallback used by the previous implementation.
    AlwaysTrue,
    /// Minimal support for CCTableViewSuite, which filters table cells with
    /// predicates like "idx == %d".
    IdxEquals(NSUInteger),
}

struct NSPredicateHostObject {
    /// `NSString *`
    format: id,
    kind: PredicateKind,
}
impl HostObject for NSPredicateHostObject {}

fn parse_predicate_kind(
    env: &mut crate::Environment,
    format: id,
    args: Option<VaList>,
) -> PredicateKind {
    if format == nil {
        return PredicateKind::AlwaysTrue;
    }

    let format_string = ns_string::to_rust_string(env, format).to_string();
    let compact = format_string
        .chars()
        .filter(|ch| !ch.is_whitespace())
        .collect::<String>();

    if compact.contains("idx")
        && (compact.contains("==") || compact.contains('='))
        && (compact.contains("%d")
            || compact.contains("%i")
            || compact.contains("%u")
            || compact.contains("%lu"))
    {
        if let Some(mut args) = args {
            let value: NSUInteger = args.next(env);
            return PredicateKind::IdxEquals(value);
        }
    }

    if compact.contains("idx") {
        for operator in ["==", "="] {
            if let Some((_, rhs)) = compact.split_once(operator) {
                let digits = rhs
                    .chars()
                    .take_while(|ch| ch.is_ascii_digit())
                    .collect::<String>();
                if let Ok(value) = digits.parse::<NSUInteger>() {
                    return PredicateKind::IdxEquals(value);
                }
            }
        }
    }

    PredicateKind::AlwaysTrue
}

fn init_with_format_and_args(
    env: &mut crate::Environment,
    this: id,
    format: id,
    args: Option<VaList>,
) -> id {
    retain(env, format);
    let kind = parse_predicate_kind(env, format, args);
    let host_object = env.objc.borrow_mut::<NSPredicateHostObject>(this);
    host_object.format = format;
    host_object.kind = kind;
    this
}

pub const CLASSES: ClassExports = objc_classes! {

(env, this, _cmd);

@implementation NSPredicate: NSObject

+ (id)allocWithZone:(NSZonePtr)_zone {
    let host_object = Box::new(NSPredicateHostObject {
        format: nil,
        kind: PredicateKind::AlwaysTrue,
    });
    env.objc.alloc_object(this, host_object, &mut env.mem)
}

+ (id)predicateWithFormat:(id)format, ...args {
    let predicate: id = msg_class![env; NSPredicate alloc];
    let predicate = init_with_format_and_args(env, predicate, format, Some(args.start()));
    autorelease(env, predicate)
}

- (id)initWithFormat:(id)format, ...args {
    init_with_format_and_args(env, this, format, Some(args.start()))
}

- (id)predicateFormat {
    env.objc.borrow::<NSPredicateHostObject>(this).format
}

- (bool)evaluateWithObject:(id)object {
    let kind = env.objc.borrow::<NSPredicateHostObject>(this).kind.clone();
    match kind {
        PredicateKind::AlwaysTrue => {
            // Enough for games that use predicates to filter local config arrays.
            true
        }
        PredicateKind::IdxEquals(expected) => {
            if object == nil || !env.objc.object_has_method_named(&env.mem, object, "idx") {
                return false;
            }
            let actual: NSUInteger = msg![env; object idx];
            actual == expected
        }
    }
}

- (())dealloc {
    let host_object = env.objc.borrow_mut::<NSPredicateHostObject>(this);
    let format = std::mem::replace(&mut host_object.format, nil);
    release(env, format);
    env.objc.dealloc_object(this, &mut env.mem)
}

@end

};
